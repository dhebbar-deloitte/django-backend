import functools

import faiss
import numpy as np
from django.conf import settings

from ai.constants import CHUNK_OVERLAP, CHUNK_SIZE, EMBEDDING_DIM, EMBEDDING_MODEL, TOP_K
from ai.models import DocumentChunk


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if overlap >= size:
        raise ValueError("overlap must be less than size")
    if not text or not text.strip():
        return []
    chunks = []
    start = 0
    step = size - overlap
    while start < len(text):
        chunk = text[start:start + size].strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
        start += step
    return chunks


@functools.lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL)


def embed(texts):
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True).astype("float32")


def _index_path(user):
    index_dir = settings.INDEX_DIR
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir / f"user_{user.id}.index"


def build_user_index(user):
    chunks = list(DocumentChunk.objects.filter(owner=user).order_by("id"))
    path = _index_path(user)
    if not chunks:
        if path.exists():
            path.unlink()
        return 0
    for i, chunk in enumerate(chunks):
        chunk.faiss_row = i
    DocumentChunk.objects.bulk_update(chunks, ["faiss_row"])
    vectors = embed([c.text for c in chunks])
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index.add(vectors)
    faiss.write_index(index, str(path))
    return len(chunks)


def search_user_index(user, query, k=TOP_K):
    path = _index_path(user)
    if not path.exists():
        return []
    index = faiss.read_index(str(path))
    vector = embed([query])
    _, row_ids = index.search(vector, k)
    rows = [r for r in row_ids[0].tolist() if r != -1]
    if not rows:
        return []
    chunks_by_row = {
        c.faiss_row: c
        for c in DocumentChunk.objects.filter(owner=user, faiss_row__in=rows)
    }
    return [chunks_by_row[r] for r in rows if r in chunks_by_row]
