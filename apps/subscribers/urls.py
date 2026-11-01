from django.urls import path

from . import views

app_name = 'subscribers'

urlpatterns = [
    path('', views.SourceList.as_view(), name='list'),
    path('nova/', views.SourceCreateView.as_view(), name='create'),
    path('<int:pk>/editar/', views.SourceUpdateView.as_view(), name='update'),
    path('<int:pk>/excluir/', views.SourceDeleteView.as_view(), name='delete'),
    path('<int:pk>/testar/', views.SourceTestView.as_view(), name='test'),
]
