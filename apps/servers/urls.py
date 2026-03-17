from django.urls import path
from .views import ServerList, ServerDetailView, FlowSearchView

app_name = 'servers'

urlpatterns = [
    path('server/', ServerList.as_view(), name='server_list'),
    # path('server/<int:pk>/', ServerDetailView.as_view(), name='server_detail'),
    path('server/<int:pk>/search/', FlowSearchView.as_view(), name='server_flow_search'),
    # path("search/", FlowSearchView.as_view(), name="flow-search"),
]
