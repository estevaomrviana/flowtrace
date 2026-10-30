from django.urls import path

from . import views

app_name = 'servers'

urlpatterns = [
    path('', views.ServerList.as_view(), name='list'),
    path('servidores/<int:pk>/busca/', views.FlowSearchView.as_view(), name='search'),

    path('organizacao/servidores/', views.ServerManageList.as_view(), name='manage'),
    path('organizacao/servidores/novo/', views.ServerCreateView.as_view(), name='create'),
    path('organizacao/servidores/<int:pk>/editar/', views.ServerUpdateView.as_view(), name='update'),
    path('organizacao/servidores/<int:pk>/excluir/', views.ServerDeleteView.as_view(), name='delete'),
    path('organizacao/servidores/<int:pk>/testar/', views.ServerTestView.as_view(), name='test'),
    path('organizacao/servidores/<int:pk>/redefinir-chave/', views.ServerResetHostKeyView.as_view(), name='reset_host_key'),
]
