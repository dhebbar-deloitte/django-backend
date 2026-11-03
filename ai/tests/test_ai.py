import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from ai.models import AIQueryLog, DocumentChunk
from ai.rag import chunk_text
from api.models import Document
from api.tests.helpers import auth

User = get_user_model()
CANNED = "This is a canned AI response."


def fake_embed(texts):
    vectors = []
    for text in texts:
        v = np.array([float(ord(c)) for c in text[:384]] + [0.0] * max(0, 384 - len(text)), dtype="float32")
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        vectors.append(v)
    return np.array(vectors, dtype="float32")


def ai_settings():
    return override_settings(INDEX_DIR=Path(tempfile.mkdtemp()))


def _guard_model(test_case):
    guard = patch("ai.rag._get_model", side_effect=AssertionError("tests must not load the real model"))
    guard.start()
    test_case.addCleanup(guard.stop)


class ChunkTextTest(TestCase):
    def test_1200_char_document(self):
        text = "A" * 1200
        chunks = chunk_text(text, size=500, overlap=100)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 500)
        self.assertEqual(len(chunks[1]), 500)
        self.assertEqual(len(chunks[2]), 400)

    def test_overlap_gte_size_raises(self):
        with self.assertRaises(ValueError):
            chunk_text("hello", size=100, overlap=100)
        with self.assertRaises(ValueError):
            chunk_text("hello", size=100, overlap=200)

    def test_empty_returns_empty(self):
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text("   "), [])


@ai_settings()
@patch("ai.views.generate", return_value=CANNED)
class AskAITest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="pass")
        auth(self.client, self.user)

    def test_valid_prompt_returns_200_and_logs(self, mock_gen):
        resp = self.client.post("/api/ask-ai", {"prompt": "hello"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["response"], CANNED)
        self.assertEqual(AIQueryLog.objects.filter(user=self.user).count(), 1)

    def test_blank_prompt_returns_400_no_log(self, mock_gen):
        resp = self.client.post("/api/ask-ai", {"prompt": ""}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AIQueryLog.objects.count(), 0)

    def test_oversized_prompt_returns_400_no_log(self, mock_gen):
        resp = self.client.post("/api/ask-ai", {"prompt": "x" * 2001}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AIQueryLog.objects.count(), 0)

    def test_llm_error_returns_502_no_log(self, mock_gen):
        from ai.llm import LLMError
        mock_gen.side_effect = LLMError("boom")
        resp = self.client.post("/api/ask-ai", {"prompt": "hello"}, format="json")
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(AIQueryLog.objects.count(), 0)

    def test_no_token_returns_401(self, mock_gen):
        self.client.credentials()
        resp = self.client.post("/api/ask-ai", {"prompt": "hello"}, format="json")
        self.assertEqual(resp.status_code, 401)


@ai_settings()
@patch("ai.rag.embed", side_effect=fake_embed)
class IngestDocTest(APITestCase):
    def setUp(self):
        _guard_model(self)
        self.user = User.objects.create_user(username="alice", password="pass")
        self.other = User.objects.create_user(username="bob", password="pass")
        auth(self.client, self.user)
        self.doc = Document.objects.create(
            owner=self.user,
            title="Big Doc",
            content="X" * 1200,
        )

    def test_ingest_returns_200_and_3_chunks(self, mock_embed):
        resp = self.client.post("/api/ingest-doc", {"document_id": self.doc.id}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["chunk_count"], 3)
        self.assertEqual(resp.data["document_id"], self.doc.id)
        self.assertEqual(DocumentChunk.objects.filter(document=self.doc).count(), 3)

    def test_ingest_twice_leaves_3_chunks(self, mock_embed):
        self.client.post("/api/ingest-doc", {"document_id": self.doc.id}, format="json")
        self.client.post("/api/ingest-doc", {"document_id": self.doc.id}, format="json")
        self.assertEqual(DocumentChunk.objects.filter(document=self.doc).count(), 3)

    def test_other_users_doc_returns_404(self, mock_embed):
        other_doc = Document.objects.create(owner=self.other, title="Other", content="x" * 1200)
        resp = self.client.post("/api/ingest-doc", {"document_id": other_doc.id}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data, {"error": "Not found"})

    def test_missing_doc_returns_404(self, mock_embed):
        resp = self.client.post("/api/ingest-doc", {"document_id": 99999}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data, {"error": "Not found"})

    def test_invalid_inputs_return_400(self, mock_embed):
        for payload in [{}, {"document_id": "abc"}, {"document_id": 0}, {"document_id": -1}]:
            with self.subTest(payload=payload):
                resp = self.client.post("/api/ingest-doc", payload, format="json")
                self.assertEqual(resp.status_code, 400)


@ai_settings()
@patch("ai.views.generate", return_value=CANNED)
class RagQueryTest(APITestCase):
    def setUp(self):
        _guard_model(self)
        patcher = patch("ai.rag.embed", side_effect=fake_embed)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user(username="alice", password="pass")
        self.other = User.objects.create_user(username="bob", password="pass")
        auth(self.client, self.user)
        self.doc = Document.objects.create(
            owner=self.user,
            title="Test Doc",
            content="X" * 1200,
        )
        self.client.post("/api/ingest-doc", {"document_id": self.doc.id}, format="json")

    def test_rag_query_returns_answer_and_sources(self, mock_gen):
        resp = self.client.post("/api/rag-query", {"query": "X" * 50}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("answer", resp.data)
        self.assertIn("sources", resp.data)
        sources = resp.data["sources"]
        self.assertTrue(len(sources) > 0)
        self.assertIn("document_id", sources[0])
        self.assertIn("chunk_text", sources[0])

    def test_second_user_sees_no_sources_and_no_generate(self, mock_gen):
        mock_gen.reset_mock()
        self.client.credentials()
        auth(self.client, self.other)
        resp = self.client.post("/api/rag-query", {"query": "X" * 50}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["sources"], [])
        mock_gen.assert_not_called()

    def test_blank_query_returns_400(self, mock_gen):
        resp = self.client.post("/api/rag-query", {"query": ""}, format="json")
        self.assertEqual(resp.status_code, 400)


@ai_settings()
@patch("ai.views.generate", return_value=CANNED)
class QueryHistoryTest(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="pass")
        self.bob = User.objects.create_user(username="bob", password="pass")

    def test_each_user_sees_only_own_entries_newest_first(self, mock_gen):
        auth(self.client, self.alice)
        self.client.post("/api/ask-ai", {"prompt": "first"}, format="json")
        self.client.post("/api/ask-ai", {"prompt": "second"}, format="json")

        auth(self.client, self.bob)
        self.client.post("/api/ask-ai", {"prompt": "bob prompt"}, format="json")

        auth(self.client, self.alice)
        resp = self.client.get("/api/query-history")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("results", data)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["results"][0]["query_text"], "second")
        self.assertEqual(data["results"][1]["query_text"], "first")

        auth(self.client, self.bob)
        resp = self.client.get("/api/query-history")
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["query_text"], "bob prompt")
