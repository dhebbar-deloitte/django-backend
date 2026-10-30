from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from api.models import Document
from api.tests.helpers import auth, make_documents
from api.views import MAX_UPLOAD_BYTES


class DocumentCreateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="Str0ng!Pass#99")
        self.other = User.objects.create_user(username="bob", password="Str0ng!Pass#99")
        auth(self.client, self.user)

    def test_json_create_owner_is_requester_not_forged_id(self):
        payload = {"title": "My Doc", "content": "Hello", "owner": self.other.id}
        resp = self.client.post("/documents", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["owner"], self.user.id)

    def test_upload_txt_file(self):
        file_content = b"Hello from notes"
        uploaded = SimpleUploadedFile("notes.txt", file_content, content_type="text/plain")
        resp = self.client.post("/documents", {"file": uploaded}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["title"], "notes.txt")
        self.assertEqual(data["content"], file_content.decode())

    def test_upload_png_gives_400(self):
        uploaded = SimpleUploadedFile("pic.png", b"\x89PNG\r\n", content_type="image/png")
        resp = self.client.post("/documents", {"file": uploaded}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_upload_oversized_file_gives_413(self):
        big = SimpleUploadedFile("big.txt", b"x" * (MAX_UPLOAD_BYTES + 1), content_type="text/plain")
        resp = self.client.post("/documents", {"file": big}, format="multipart")
        self.assertEqual(resp.status_code, 413)


class DocumentListTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="Str0ng!Pass#99")
        self.other = User.objects.create_user(username="bob", password="Str0ng!Pass#99")
        auth(self.client, self.user)

    def test_pagination_shape_with_25_documents(self):
        make_documents(self.user, 25)
        resp = self.client.get("/documents")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(set(data.keys()), {"count", "next", "previous", "results"})
        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 10)
        self.assertIsNotNone(data["next"])
        self.assertIsNone(data["previous"])

    def test_each_user_sees_only_their_own_documents(self):
        make_documents(self.user, 3)
        make_documents(self.other, 5)
        resp = self.client.get("/documents")
        self.assertEqual(resp.json()["count"], 3)


class DocumentDetailTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="Str0ng!Pass#99")
        self.other = User.objects.create_user(username="bob", password="Str0ng!Pass#99")
        auth(self.client, self.user)
        self.own_doc = Document.objects.create(owner=self.user, title="Mine", content="mine")
        self.other_doc = Document.objects.create(owner=self.other, title="Theirs", content="theirs")

    def test_get_another_users_document_gives_404(self):
        resp = self.client.get(f"/documents/{self.other_doc.pk}")
        self.assertEqual(resp.status_code, 404)

    def test_delete_own_document_gives_204_and_subsequent_get_is_404(self):
        resp = self.client.delete(f"/documents/{self.own_doc.pk}")
        self.assertEqual(resp.status_code, 204)
        resp = self.client.get(f"/documents/{self.own_doc.pk}")
        self.assertEqual(resp.status_code, 404)

    def test_delete_another_users_document_gives_403_and_row_still_exists(self):
        resp = self.client.delete(f"/documents/{self.other_doc.pk}")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Document.objects.filter(pk=self.other_doc.pk).exists())
