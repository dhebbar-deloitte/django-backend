from django.urls import path
from . import views

urlpatterns = [
    path("health", views.health),
    path("register", views.register),
    path("login", views.login),
    path("documents", views.documents),
    path("documents/<int:pk>", views.document_detail),
    path("query", views.query),
    path("queries", views.queries),
]