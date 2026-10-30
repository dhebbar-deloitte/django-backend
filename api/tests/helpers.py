import secrets
from datetime import timedelta
from django.utils import timezone
from api.models import Document, UserSession


def make_token(user, hours=24):
    session = UserSession.objects.create(
        user=user,
        token=secrets.token_hex(32),
        expires_at=timezone.now() + timedelta(hours=hours),
    )
    return session.token


def auth(client, user):
    token = make_token(user)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")


def make_documents(user, n):
    for i in range(1, n + 1):
        Document.objects.create(owner=user, title=f"Doc {i}", content=f"Content {i}")