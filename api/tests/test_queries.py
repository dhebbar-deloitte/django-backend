from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from api.models import Document
from api.tests.helpers import auth


class QueryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="Str0ng!Pass#99")
        self.other = User.objects.create_user(username="bob", password="Str0ng!Pass#99")
        auth(self.client, self.user)
        Document.objects.create(owner=self.user, title="Django tips", content="Use select_related.")

    def test_matching_query_ignores_forged_fields(self):
        payload = {"query_text": "Django", "user": self.other.id, "result_summary": "FORGED"}
        resp = self.client.post("/query", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["result_summary"].startswith("1"))
        self.assertEqual(data["user"], self.user.id)

    def test_blank_query_text_gives_400(self):
        resp = self.client.post("/query", {"query_text": ""}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_each_user_sees_only_their_own_queries_newest_first(self):
        self.client.post("/query", {"query_text": "Django"}, format="json")
        self.client.post("/query", {"query_text": "tips"}, format="json")

        other_client = self.client_class()
        auth(other_client, self.other)
        other_client.post("/query", {"query_text": "Django"}, format="json")

        resp = self.client.get("/queries")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(set(data.keys()), {"count", "next", "previous", "results"})
        self.assertEqual(data["count"], 2)
        ids = [r["user"] for r in data["results"]]
        self.assertTrue(all(uid == self.user.id for uid in ids))
        texts = [r["query_text"] for r in data["results"]]
        self.assertEqual(texts[0], "tips")
