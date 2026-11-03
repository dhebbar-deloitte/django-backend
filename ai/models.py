from django.db import models
from django.conf import settings


class AIQueryLog(models.Model):
    ENDPOINT_CHOICES = [("ask-ai", "ask-ai"), ("rag-query", "rag-query")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_queries")
    endpoint = models.CharField(max_length=20, choices=ENDPOINT_CHOICES)
    query_text = models.TextField()
    response_text = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.endpoint} - {self.query_text[:50]}"


class DocumentChunk(models.Model):
    document = models.ForeignKey("api.Document", on_delete=models.CASCADE, related_name="chunks")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    faiss_row = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.document.title} - chunk {self.chunk_index}"
