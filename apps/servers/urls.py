from django.urls import path
from .views import IndexView, ServerDetailView, FlowSearchView

app_name = 'servers'

urlpatterns = [
    path('', IndexView.as_view(), name='index'),
    path('server/<int:pk>/', ServerDetailView.as_view(), name='server_detail'),
    path("search/", FlowSearchView.as_view(), name="flow-search"),
]
