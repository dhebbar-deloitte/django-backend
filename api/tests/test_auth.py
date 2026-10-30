from django.test import TestCase
from django.contrib.auth.models import User
from api.models import UserSession
from api.tests.helpers import make_token


class RegisterTests(TestCase):
    def test_gives_201_with_username_no_password(self):
        resp = self.client.post("/register", {"username": "bob", "password": "Str0ng!Pass#99"}, content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("username", data)
        self.assertNotIn("password", data)

    def test_duplicate_username_gives_400(self):
        payload = {"username": "bob", "password": "Str0ng!Pass#99"}
        self.client.post("/register", payload, content_type="application/json")
        resp = self.client.post("/register", payload, content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_weak_password_gives_400(self):
        resp = self.client.post("/register", {"username": "bob", "password": "1"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="Str0ng!Pass#99")

    def test_correct_credentials_gives_200_with_64char_token_and_session_row(self):
        resp = self.client.post("/login", {"username": "alice", "password": "Str0ng!Pass#99"}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        token = resp.json()["token"]
        self.assertEqual(len(token), 64)
        self.assertTrue(UserSession.objects.filter(token=token).exists())

    def test_wrong_password_gives_401(self):
        resp = self.client.post("/login", {"username": "alice", "password": "wrongpass"}, content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_unknown_username_gives_401_same_body_as_wrong_password(self):
        resp_unknown = self.client.post("/login", {"username": "nobody", "password": "whatever"}, content_type="application/json")
        resp_wrong = self.client.post("/login", {"username": "nobody2", "password": "whatever"}, content_type="application/json")
        self.assertEqual(resp_unknown.status_code, 401)
        self.assertEqual(resp_unknown.json(), resp_wrong.json())

    def test_missing_password_gives_400(self):
        resp = self.client.post("/login", {"username": "alice"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)


class DocumentAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="Str0ng!Pass#99")

    def test_no_token_gives_401_with_www_authenticate_header(self):
        resp = self.client.get("/documents")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("WWW-Authenticate", resp.headers)

    def test_wrong_token_gives_401(self):
        resp = self.client.get("/documents", HTTP_AUTHORIZATION="Token deadbeefdeadbeef")
        self.assertEqual(resp.status_code, 401)

    def test_expired_token_gives_401(self):
        token = make_token(self.user, hours=-1)
        resp = self.client.get("/documents", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(resp.status_code, 401)

    def test_valid_token_gives_200(self):
        token = make_token(self.user)
        resp = self.client.get("/documents", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(resp.status_code, 200)

    def test_inactive_user_with_valid_token_gives_401(self):
        token = make_token(self.user)
        self.user.is_active = False
        self.user.save()
        resp = self.client.get("/documents", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(resp.status_code, 401)


class HealthTests(TestCase):
    def test_wrong_token_still_gives_200(self):
        resp = self.client.get("/health", HTTP_AUTHORIZATION="Token deadbeefdeadbeef")
        self.assertEqual(resp.status_code, 200)
