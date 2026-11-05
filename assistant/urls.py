from django.shortcuts import render

# Create your views here.
from django.urls import path
from . import views

urlpatterns = [
    path("upload-doc", views.upload_doc),
    path("chat", views.chat),
    path("chat/sessions/<int:pk>", views.chat_session),
]