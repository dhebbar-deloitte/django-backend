from rest_framework import serializers
from ai.constants import MAX_PROMPT_LENGTH
from ai.models import AIQueryLog


class AskAISerializer(serializers.Serializer):
    prompt = serializers.CharField(required=True, max_length=MAX_PROMPT_LENGTH)


class IngestDocSerializer(serializers.Serializer):
    document_id = serializers.IntegerField(min_value=1)


class RagQuerySerializer(serializers.Serializer):
    query = serializers.CharField(max_length=MAX_PROMPT_LENGTH)


class AIQueryLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIQueryLog
        fields = ["id", "endpoint", "query_text", "response_text", "sources", "created_at"]
        read_only_fields = fields
