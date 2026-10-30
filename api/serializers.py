from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Document, QueryLog
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from api.constants import MAX_QUERY_LENGTH


class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id','username','password')
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password']
        )
        return user

    def validate(self, attrs):
        candidate = User(username=attrs.get("username"))
        value = attrs.get("password")
        try:
            password_validation.validate_password(value, candidate)
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})
        return attrs

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ('id', 'title', 'content', 'owner', 'uploaded_at')
        extra_kwargs = {'owner': {'read_only': True}}

class QueryLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = QueryLog
        fields = ('id', 'query_text', 'result_summary', 'created_at', 'user')
        extra_kwargs = {'query_text':{'max_length': MAX_QUERY_LENGTH}, 'user': {'read_only': True}, 'result_summary': {'read_only': True}, 'created_at': {'read_only': True}}
