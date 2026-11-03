from django.urls import path
from . import views

urlpatterns = [
    path("ping", views.ping),
    path("ask-ai", views.ask_ai),
    path("ingest-doc", views.ingest_doc),
    path("rag-query", views.rag_query),
    path("query-history", views.query_history),
]