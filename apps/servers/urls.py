from django.urls import path
from django.views.generic import RedirectView

from .views import ServerList, FlowSearchView

app_name = 'servers'

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='servers:server_list'), name='home'),
    path('server/', ServerList.as_view(), name='server_list'),
    path('server/<int:pk>/search/', FlowSearchView.as_view(), name='server_flow_search'),
]
