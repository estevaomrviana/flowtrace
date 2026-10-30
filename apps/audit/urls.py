from django.urls import path

from . import views

app_name = 'audit'

urlpatterns = [
    path('', views.SearchLogListView.as_view(), name='list'),
]
