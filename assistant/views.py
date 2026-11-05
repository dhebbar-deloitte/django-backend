import logging
import os

from django.db import transaction
from pypdf import PdfReader
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ai.rag import ingest_document
from api.models import Document
from assistant.constants import ALLOWED_EXTENSIONS, MAX_FILE_BYTES, MAX_TEXT_CHARS
from django.http import Http404
from django.shortcuts import get_object_or_404
from assistant.agent import AgentError, run_agent
from assistant.models import ChatSession, ChatMessage
from assistant.constants import MAX_HISTORY_MESSAGES
from assistant.serializers import ChatRequestSerializer, ChatMessageSerializer

logger = logging.getLogger(__name__)


class UploadError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status


def _read_txt(uploaded):
    try:
        return uploaded.read().decode("utf-8")
    except UnicodeDecodeError:
        raise UploadError("File is not valid UTF-8 text")


def _read_pdf(uploaded):
    if uploaded.read(5) != b"%PDF-":
        raise UploadError("File is not a valid PDF")
    uploaded.seek(0)
    try:
        reader = PdfReader(uploaded)
        encrypted = reader.is_encrypted
        pages = [] if encrypted else [p.extract_text() or "" for p in reader.pages]
    except Exception:
        logger.warning("PDF parsing failed")
        raise UploadError("Could not read the PDF")
    if encrypted:
        raise UploadError("Encrypted PDFs are not supported")
    return "\n".join(pages), len(pages)


@api_view(["POST"])
def upload_doc(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        return Response({"error": "No file uploaded"}, status=400)
    ext = os.path.splitext(uploaded.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return Response({"error": "Only .pdf and .txt files are allowed"}, status=400)
    if uploaded.size > MAX_FILE_BYTES:
        return Response({"error": "File too large (max 5 MB)"}, status=413)

    page_count = None
    try:
        if ext == ".txt":
            text = _read_txt(uploaded)
        else:
            text, page_count = _read_pdf(uploaded)
    except UploadError as exc:
        return Response({"error": exc.message}, status=exc.status)

    if not text.strip():
        return Response({"error": "No extractable text (a scanned PDF?)"}, status=400)
    if len(text) > MAX_TEXT_CHARS:
        return Response({"error": "Text too long (max 200,000 characters)"}, status=413)

    with transaction.atomic():
        document = Document.objects.create(
            title=uploaded.name[:255], content=text, owner=request.user
        )
        chunk_count = ingest_document(request.user, document)
    logger.info("Uploaded document %d: %d chunks", document.id, chunk_count)

    body = {
        "status": "ingested",
        "document_id": document.id,
        "title": document.title,
        "chunk_count": chunk_count,
    }
    if page_count is not None:
        body["page_count"] = page_count
    return Response(body, status=201)

@api_view(["POST"])
def chat(request):
    serializer = ChatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    message = serializer.validated_data["message"]
    session_id = serializer.validated_data.get("session_id")

    session = None
    history = []
    if session_id is not None:
        try:
            session = get_object_or_404(request.user.chat_sessions, pk=session_id)
        except Http404:
            return Response({"error": "Not found"}, status=404)
        recent = list(session.messages.order_by("-id")[:MAX_HISTORY_MESSAGES])
        history = [{"role": m.role, "content": m.content} for m in reversed(recent)]

    try:
        result = run_agent(request.user, message, history)
    except AgentError:
        return Response({"error": "The assistant failed. Please try again."}, status=502)

    with transaction.atomic():
        if session is None:
            session = ChatSession.objects.create(user=request.user, title=message[:60])
        ChatMessage.objects.create(session=session, role="user", content=message)
        ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=result["answer"],
            route=result["route"],
            steps=result["steps"],
            tool_output=result["tool_output"] or "",
            sources=result["sources"],
        )
        session.save(update_fields=["updated_at"])

    logger.info("Chat session %d: route=%s", session.id, result["route"])
    return Response({
        "session_id": session.id,
        "answer": result["answer"],
        "route": result["route"],
        "steps": result["steps"],
        "tool_output": result["tool_output"],
        "sources": result["sources"],
    })


@api_view(["GET"])
def chat_session(request, pk):
    try:
        session = get_object_or_404(request.user.chat_sessions, pk=pk)
    except Http404:
        return Response({"error": "Not found"}, status=404)
    return Response({
        "session_id": session.id,
        "title": session.title,
        "messages": ChatMessageSerializer(session.messages.all(), many=True).data,
    })