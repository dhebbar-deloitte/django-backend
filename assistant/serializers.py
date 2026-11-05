from rest_framework import serializers

from assistant.constants import MAX_MESSAGE_LENGTH
from assistant.models import ChatMessage


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=MAX_MESSAGE_LENGTH)
    session_id = serializers.IntegerField(min_value=1, required=False)


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "route", "steps", "tool_output", "sources", "created_at"]
        read_only_fields = fields