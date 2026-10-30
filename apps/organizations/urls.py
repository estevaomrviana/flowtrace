from django.urls import path

from . import views

app_name = 'organizations'

urlpatterns = [
    path('', views.OrganizationDetailView.as_view(), name='detail'),
    path('membros/', views.MemberListView.as_view(), name='members'),
    path('membros/novo/', views.MemberCreateView.as_view(), name='member_create'),
    path('membros/<int:pk>/editar/', views.MemberUpdateView.as_view(), name='member_update'),
]
