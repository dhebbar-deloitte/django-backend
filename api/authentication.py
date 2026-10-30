from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import UserSession
from django.utils import timezone
class SessionTokenAuthentication(BaseAuthentication):
    keyword = "Token"
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        parts = header.split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0] != self.keyword:
            raise AuthenticationFailed("Invalid authorization header")
        token = parts[1]
        session = UserSession.objects.select_related("user").filter(token=token, expires_at__gt=timezone.now()).first()
        if session is None:
            raise AuthenticationFailed("Invalid or expired token")
        if not session.user.is_active:
            raise AuthenticationFailed("User is inactive")
        return (session.user, session)
    def authenticate_header(self, request):
        return self.keyword