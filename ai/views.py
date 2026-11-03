import logging

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ai.llm import LLMError, generate
from ai.models import AIQueryLog, DocumentChunk
from ai.prompts import RAG_SYSTEM_PROMPT, SYSTEM_PROMPT, build_rag_message, build_user_message
from ai.rag import build_user_index, chunk_text, search_user_index
from ai.serializers import AIQueryLogSerializer, AskAISerializer, IngestDocSerializer, RagQuerySerializer
from api.pagination import StandardPagination

logger = logging.getLogger(__name__)


@api_view(['GET'])
def ping(request):
    return Response({"message": "Hello, world!"})


@api_view(['POST'])
def ask_ai(request):
    serializer = AskAISerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    prompt = serializer.validated_data["prompt"]
    try:
        answer = generate(SYSTEM_PROMPT, build_user_message(prompt))
    except LLMError:
        return Response({"error": "LLM request failed"}, status=502)
    AIQueryLog.objects.create(
        user=request.user,
        endpoint="ask-ai",
        query_text=prompt,
        response_text=answer,
    )
    return Response({"response": answer})


@api_view(['POST'])
def ingest_doc(request):
    serializer = IngestDocSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    document_id = serializer.validated_data["document_id"]
    try:
        document = get_object_or_404(request.user.documents, pk=document_id)
    except Http404:
        return Response({"error": "Not found"}, status=404)
    texts = chunk_text(document.content)
    with transaction.atomic():
        document.chunks.all().delete()
        DocumentChunk.objects.bulk_create([
            DocumentChunk(
                document=document,
                owner=request.user,
                chunk_index=i,
                text=text,
                faiss_row=0,
            )
            for i, text in enumerate(texts)
        ])
        build_user_index(request.user)
    logger.info("Ingested document %d: %d chunks", document_id, len(texts))
    return Response({"status": "ingested", "document_id": document_id, "chunk_count": len(texts)})


NO_CONTEXT_ANSWER = "I don't have any relevant documents to answer your question."


@api_view(['POST'])
def rag_query(request):
    serializer = RagQuerySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data["query"]
    chunks = search_user_index(request.user, query)
    sources = [{"document_id": c.document_id, "chunk_text": c.text} for c in chunks]
    if not chunks:
        answer = NO_CONTEXT_ANSWER
    else:
        try:
            answer = generate(RAG_SYSTEM_PROMPT, build_rag_message(query, chunks))
        except LLMError:
            return Response({"error": "LLM request failed"}, status=502)
    AIQueryLog.objects.create(
        user=request.user,
        endpoint="rag-query",
        query_text=query,
        response_text=answer,
        sources=sources,
    )
    return Response({"answer": answer, "sources": sources})


@api_view(['GET'])
def query_history(request):
    paginator = StandardPagination()
    queryset = request.user.ai_queries.all()
    page = paginator.paginate_queryset(queryset, request)
    serializer = AIQueryLogSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)
