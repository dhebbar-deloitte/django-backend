from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from django.http import Http404
from rest_framework.response import Response
from rest_framework import status
from api.constants import MAX_TITLES_IN_SUMMARY
from api.pagination import StandardPagination
from api.serializers import DocumentSerializer, RegisterSerializer, QueryLogSerializer
import secrets
from datetime import timedelta
import os
from django.db.models import Q
from django.contrib.auth import authenticate
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import Document, UserSession

SESSION_LIFETIME_HOURS = 24
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json"}
MAX_UPLOAD_BYTES = 1 * 1024 * 1024  # 1 MB

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "healthy"})

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    return Response({"id": user.id, "username": user.username}, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")
    if not username or not password:
        return Response({"error": "Username and password are required"}, status=status.HTTP_400_BAD_REQUEST)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
    token = secrets.token_hex(32)
    expires_at = timezone.now() + timedelta(hours=SESSION_LIFETIME_HOURS)
    UserSession.objects.create(
        user=user,
        token=token,
        expires_at=expires_at
    )
    return Response({
        "message": "Login successful",
        "token": token,
        "expires_at": expires_at
    }, status=status.HTTP_200_OK)

def _create_document(request):
    uploaded = request.FILES.get("file")
    if uploaded is not None:
        ext = os.path.splitext(uploaded.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Response({"error": "Invalid file extension"}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded.size > MAX_UPLOAD_BYTES:
            return Response({"error": "Payload too large (max 1 MB)"}, status=413)
        try:
            text = uploaded.read().decode("utf-8")
        except UnicodeDecodeError:
            return Response({"error": "File is not valid UTF-8 text"}, status=status.HTTP_400_BAD_REQUEST)
        data = {"title": request.data.get("title") or uploaded.name, "content": text}
    else:
        data = request.data
    serializer = DocumentSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    if len(serializer.validated_data.get("content", "").encode("utf-8")) > MAX_UPLOAD_BYTES:
        return Response({"error": "Payload too large (max 1 MB)"}, status=413)
    document = serializer.save(owner=request.user)
    return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED)

def _list_documents(request):
    paginator = StandardPagination()
    queryset = request.user.documents.all()
    page = paginator.paginate_queryset(queryset, request)
    serializer = DocumentSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)

@api_view(['POST', 'GET'])
def documents(request):
    if request.method == "POST":
        return _create_document(request)
    elif request.method == "GET":
        return _list_documents(request)


@api_view(['GET', 'DELETE'])
def document_detail(request, pk):
    try:
        if request.method == "GET":
            document = get_object_or_404(request.user.documents, pk=pk)
            serializer = DocumentSerializer(document)
            return Response(serializer.data, status=status.HTTP_200_OK)
        elif request.method == "DELETE":
            document = get_object_or_404(Document, pk=pk)
            if document.owner != request.user:
                return Response({"error": "Forbidden"}, status=403)
            document.delete()
            return Response(status=204)
    except Http404:
        return Response({"error": "Not found"}, status=404)

@api_view(['POST'])
def query(request):
    serializer = QueryLogSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    query_text = serializer.validated_data.get("query_text")
    matches = request.user.documents.filter(Q(title__icontains=query_text) | Q(content__icontains=query_text))
    total_matches = matches.count()
    
    if not total_matches:
        result_summary = "No documents matched"
    else:
        titles = ", ".join(doc.title for doc in matches[:MAX_TITLES_IN_SUMMARY])
        if total_matches > MAX_TITLES_IN_SUMMARY:
            titles += "..."
        result_summary = f"{total_matches} document{'s' if total_matches > 1 else ''} matched: {titles}"
    query_log =serializer.save(user=request.user, result_summary=result_summary)
    return Response(QueryLogSerializer(query_log).data, status=status.HTTP_201_CREATED)

@api_view(['GET'])
def queries(request):
    paginator = StandardPagination()
    queryset = request.user.queries.all()
    page = paginator.paginate_queryset(queryset, request)
    serializer = QueryLogSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)
