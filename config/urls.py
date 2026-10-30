from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


admin.site.site_header = 'FlowTrace · Plataforma'
admin.site.site_title = 'FlowTrace'
admin.site.index_title = 'Administração da plataforma'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('organizacao/', include('apps.organizations.urls', namespace='organizations')),
    path('historico/', include('apps.audit.urls', namespace='audit')),
    path('', include('apps.servers.urls', namespace='servers')),
]

if settings.DEBUG:
    urlpatterns+= static(settings.STATIC_URL , document_root=settings.STATIC_ROOT)
    urlpatterns+= static(settings.MEDIA_URL , document_root=settings.MEDIA_ROOT)
