from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.views.generic import RedirectView

from apps.core.forms import StyledPasswordChangeForm


admin.site.site_header = 'FlowTrace · Plataforma'
admin.site.site_title = 'FlowTrace'
admin.site.index_title = 'Administração da plataforma'

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'img/favicon.svg', permanent=True)),
    path('admin/', admin.site.urls),
    path(
        'accounts/password_change/',
        auth_views.PasswordChangeView.as_view(form_class=StyledPasswordChangeForm),
        name='password_change',
    ),
    path('accounts/', include('django.contrib.auth.urls')),
    path('organizacao/assinantes/', include('apps.subscribers.urls', namespace='subscribers')),
    path('organizacao/', include('apps.organizations.urls', namespace='organizations')),
    path('requisicoes/', include('apps.cases.urls', namespace='cases')),
    path('historico/', include('apps.audit.urls', namespace='audit')),
    path('', include('apps.servers.urls', namespace='servers')),
]

if settings.DEBUG:
    urlpatterns+= static(settings.STATIC_URL , document_root=settings.STATIC_ROOT)
    urlpatterns+= static(settings.MEDIA_URL , document_root=settings.MEDIA_ROOT)
