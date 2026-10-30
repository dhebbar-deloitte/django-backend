from django.db import models
from django.conf import settings

# Create your models here.
class Document(models.Model):
    title = models.CharField(max_length=255)
    content = models.TextField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents",)
    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title

class QueryLog(models.Model):
    query_text = models.TextField()
    result_summary= models.TextField(blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="queries")
    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.query_text[:50]}"

class UserSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions")
    token = models.CharField(unique=True, max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"{self.user.username} - {self.token[:10]} - Expires at: {self.expires_at}"