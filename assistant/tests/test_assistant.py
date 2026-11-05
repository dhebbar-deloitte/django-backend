import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from ai.tests.test_ai import fake_embed
from api.tests.helpers import make_token
from assistant.agent import CITY_PROMPT, REWRITE_PROMPT, ROUTER_PROMPT
from assistant.models import ChatMessage
from django.core.files.uploadedfile import SimpleUploadedFile

from assistant.agent import NO_CONTEXT_ANSWER
from assistant.constants import MAX_FILE_BYTES
from assistant.models import ChatSession


class FakeLLM:
    """Scripted stand-in for the chat model. It answers each graph node by its system prompt."""

    def __init__(self, route="general", city="London", answer="fake answer", rewrite="rewritten question"):
        self.route, self.city, self.answer, self.rewrite = route, city, answer, rewrite
        self.calls = []

    def invoke(self, messages):
        system = messages[0].content
        self.calls.append((system, messages[-1].content))
        if system == ROUTER_PROMPT:
            text = self.route
        elif system == REWRITE_PROMPT:
            text = self.rewrite
        elif system == CITY_PROMPT:
            text = self.city
        else:
            text = self.answer
        return SimpleNamespace(content=text)


class FakeHTTPResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def fake_httpx_get(url, **kwargs):
    if "geocoding" in url:
        return FakeHTTPResponse({"results": [{"name": "London", "latitude": 51.5, "longitude": -0.12}]})
    return FakeHTTPResponse({"current": {"temperature_2m": 12.5, "relative_humidity_2m": 70, "weather_code": 3}})


class AssistantTestCase(APITestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        override = override_settings(INDEX_DIR=Path(self.tmp))
        override.enable()
        self.addCleanup(override.disable)
        for target, kwargs in [
            ("ai.rag.embed", {"side_effect": fake_embed}),
            ("ai.rag._get_model", {"side_effect": AssertionError("tests must not load the real model")}),
        ]:
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.user = User.objects.create_user("alice", password="Str0ng!Pass#99")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {make_token(self.user)}")

    def use_llm(self, llm):
        patcher = patch("assistant.agent.get_llm", return_value=llm)
        patcher.start()
        self.addCleanup(patcher.stop)
        return llm

    def chat(self, message, session_id=None):
        body = {"message": message}
        if session_id:
            body["session_id"] = session_id
        return self.client.post("/api/chat", body, format="json")


class AgentEndToEndTests(AssistantTestCase):
    def test_weather_question_routes_to_tool_and_answers(self):
        llm = self.use_llm(FakeLLM(route="weather", city="London", answer="It is 12.5°C in London."))
        with patch("assistant.tools.httpx.get", side_effect=fake_httpx_get) as http:
            response = self.chat("What's the weather in London?")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["route"], "weather")
        self.assertEqual(data["steps"], ["route:weather", "weather", "answer"])
        self.assertIn("12.5", data["tool_output"])
        self.assertEqual(http.call_count, 2)
        self.assertIn("12.5", llm.calls[-1][1])
        self.assertEqual(data["answer"], "It is 12.5°C in London.")
        self.assertEqual(ChatMessage.objects.filter(session_id=data["session_id"]).count(), 2)

class RaisingLLM(FakeLLM):
    def invoke(self, messages):
        raise RuntimeError("model down")


class AssistantFlowTests(AssistantTestCase):
    def upload(self, name, content):
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        file = SimpleUploadedFile(name, data)
        return self.client.post("/api/upload-doc", {"file": file}, format="multipart")

    def test_documents_route_retrieves_and_cites(self):
        self.assertEqual(self.upload("zorblax.txt", "The Zorblax project lead is Priya Nair.").status_code, 201)
        self.use_llm(FakeLLM(route="documents", answer="Priya Nair."))
        data = self.chat("Who leads Zorblax?").json()
        self.assertEqual(data["steps"], ["route:documents", "retrieve", "answer"])
        self.assertEqual(len(data["sources"]), 1)
        self.assertEqual(data["sources"][0]["title"], "zorblax.txt")
        self.assertIn("Priya Nair", data["sources"][0]["chunk_text"])
        self.assertIsNone(data["tool_output"])

    def test_general_route_skips_retrieval_and_tool(self):
        self.use_llm(FakeLLM(route="general", answer="An API is a set of rules."))
        with patch("assistant.tools.httpx.get", side_effect=fake_httpx_get) as http:
            data = self.chat("What is an API?").json()
        self.assertEqual(data["steps"], ["route:general", "answer"])
        self.assertEqual(data["sources"], [])
        self.assertIsNone(data["tool_output"])
        self.assertEqual(http.call_count, 0)

    def test_follow_up_uses_memory_through_rewrite(self):
        llm = self.use_llm(FakeLLM(route="general", answer="ok"))
        first = self.chat("My project is called Zorblax.").json()
        second = self.chat("How much was its budget?", session_id=first["session_id"]).json()
        self.assertEqual(second["session_id"], first["session_id"])
        self.assertEqual(second["steps"][0], "rewrite")
        rewrite_inputs = [msg for system, msg in llm.calls if system == REWRITE_PROMPT]
        self.assertEqual(len(rewrite_inputs), 1)
        self.assertIn("My project is called Zorblax.", rewrite_inputs[0])

    def test_sources_come_from_two_documents(self):
        self.upload("zorblax.txt", "The Zorblax project lead is Priya Nair.")
        self.upload("pasta.txt", "To cook pasta, boil salted water for nine minutes.")
        self.use_llm(FakeLLM(route="documents"))
        data = self.chat("Tell me about Zorblax and pasta").json()
        self.assertEqual(len({s["document_id"] for s in data["sources"]}), 2)

    def test_no_documents_gives_fixed_answer_without_answer_call(self):
        llm = self.use_llm(FakeLLM(route="documents"))
        data = self.chat("Anything about Zorblax?").json()
        self.assertEqual(data["answer"], NO_CONTEXT_ANSWER)
        self.assertEqual(data["sources"], [])
        self.assertEqual(len(llm.calls), 1)        # only the router call

    def test_agent_failure_returns_502_and_saves_nothing(self):
        self.use_llm(RaisingLLM())
        response = self.chat("hello")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(ChatMessage.objects.count(), 0)
        self.assertEqual(ChatSession.objects.count(), 0)

    def test_other_users_session_and_bad_input(self):
        bob = User.objects.create_user("bob", password="Str0ng!Pass#99")
        session = ChatSession.objects.create(user=bob, title="private")
        self.use_llm(FakeLLM())
        self.assertEqual(self.chat("hi", session_id=session.id).status_code, 404)
        self.assertEqual(self.client.get(f"/api/chat/sessions/{session.id}").status_code, 404)
        self.assertEqual(self.chat("   ").status_code, 400)

    def test_endpoints_require_a_token(self):
        self.client.credentials()
        self.assertEqual(self.chat("hi").status_code, 401)
        file = SimpleUploadedFile("a.txt", b"hello")
        response = self.client.post("/api/upload-doc", {"file": file}, format="multipart")
        self.assertEqual(response.status_code, 401)

    def test_upload_rules(self):
        self.assertEqual(self.upload("a.txt", "hello world").status_code, 201)
        self.assertEqual(self.upload("pic.png", "x").status_code, 400)
        self.assertEqual(self.upload("fake.pdf", "just text").status_code, 400)
        self.assertEqual(self.upload("big.txt", b"a" * (MAX_FILE_BYTES + 1)).status_code, 413)