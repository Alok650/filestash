from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ApiKeyCreateView, ApiKeyDeactivateView, ApiKeyMeView, FileViewSet

router = DefaultRouter()
router.register(r'files', FileViewSet, basename='file')

urlpatterns = [
    path('', include(router.urls)),
    path('keys/', ApiKeyCreateView.as_view(), name='api-key-create'),
    path('keys/me/', ApiKeyMeView.as_view(), name='api-key-me'),
    path('keys/<uuid:pk>/', ApiKeyDeactivateView.as_view(), name='api-key-deactivate'),
]
