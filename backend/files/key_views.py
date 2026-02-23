import logging
import secrets

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import repository
from .models import ApiKey
from .repository import ADMIN_AUTH
from .serializers import ApiKeyCreateInputSerializer, ApiKeyCreateSerializer, ApiKeyDetailSerializer

logger = logging.getLogger(__name__)


class _AdminKeyNotConfigured(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = {'error': 'admin_key_not_configured'}
    default_code = 'admin_key_not_configured'


class IsAdminApiKey(BasePermission):
    def has_permission(self, request, view):
        if not getattr(settings, 'ADMIN_API_KEY', ''):
            raise _AdminKeyNotConfigured()
        if request.auth is not ADMIN_AUTH:
            raise PermissionDenied({'error': 'forbidden'})
        return True


class ApiKeyCreateView(APIView):
    """POST /api/keys/ — create a new API key (admin only)."""

    permission_classes = [IsAdminApiKey]

    def post(self, request):
        input_serializer = ApiKeyCreateInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        label = input_serializer.validated_data['label'].strip()
        quota = input_serializer.validated_data['storage_quota_bytes']

        raw_token = secrets.token_hex(32)
        try:
            api_key = repository.create_api_key(
                label=label, key=raw_token, storage_quota_bytes=quota
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("API key created: id=%s label=%s", api_key.id, api_key.label)
        serializer = ApiKeyCreateSerializer(api_key)
        data = dict(serializer.data)
        data['key'] = raw_token  # replace stored hash with plaintext (returned once only)
        return Response(data, status=status.HTTP_201_CREATED)


class ApiKeyMeView(APIView):
    """GET /api/keys/me/ — return the authenticated key's info and storage usage."""

    def get(self, request):
        if not isinstance(request.auth, ApiKey):
            response = Response(
                {'error': 'authentication_required'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            response['WWW-Authenticate'] = 'ApiKey realm="api"'
            return response
        api_key = request.auth
        used = repository.get_storage_used_bytes(api_key)
        serializer = ApiKeyDetailSerializer(api_key, context={'storage_used_bytes': used})
        return Response(serializer.data)


class ApiKeyDeactivateView(APIView):
    """DELETE /api/keys/{pk}/ — deactivate a key (admin only)."""

    permission_classes = [IsAdminApiKey]

    def delete(self, request, pk):
        api_key = repository.get_api_key_by_id(pk)
        if not api_key:
            return Response({'error': 'not_found'}, status=status.HTTP_404_NOT_FOUND)

        repository.deactivate_api_key(api_key)
        logger.info("API key deactivated: id=%s label=%s", api_key.id, api_key.label)
        return Response(status=status.HTTP_204_NO_CONTENT)
