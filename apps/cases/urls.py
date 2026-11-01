from django.urls import path

from . import views

app_name = 'cases'

urlpatterns = [
    path('', views.CaseListView.as_view(), name='list'),
    path('nova/', views.CaseCreateView.as_view(), name='create'),
    path('<int:pk>/', views.CaseDetailView.as_view(), name='detail'),
    path('<int:pk>/editar/', views.CaseUpdateView.as_view(), name='update'),
    path('<int:pk>/situacao/', views.CaseStatusView.as_view(), name='status'),
    path('<int:pk>/resposta.pdf', views.CaseReportView.as_view(), name='report'),
    path('<int:pk>/consultas/<int:item_pk>/executar/', views.CaseItemRunView.as_view(), name='item_run'),
    path('<int:pk>/consultas/<int:item_pk>/excluir/', views.CaseItemDeleteView.as_view(), name='item_delete'),
]
