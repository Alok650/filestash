from django.contrib import admin
from django.urls import path, include
from django.conf import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('files.urls')),
]

if settings.DEBUG:
    from django.views.static import serve as _static_serve

    def _media_view(request, path):
        response = _static_serve(request, path, document_root=settings.MEDIA_ROOT)
        response['Content-Disposition'] = 'attachment'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    urlpatterns += [path('media/<path:path>', _media_view)]
