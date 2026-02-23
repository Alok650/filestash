import hmac
import logging

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .repository import ADMIN_AUTH, get_api_key_by_token

logger = logging.getLogger(__name__)
_SCHEME = 'ApiKey '


class ApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header.startswith(_SCHEME):
            return None

        token = auth_header[len(_SCHEME):]
        if not token:
            return None

        admin_key = getattr(settings, 'ADMIN_API_KEY', '')
        if admin_key and hmac.compare_digest(token, admin_key):
            return (AnonymousUser(), ADMIN_AUTH)

        api_key = get_api_key_by_token(token)
        if api_key:
            return (AnonymousUser(), api_key)

        logger.warning("Authentication failed: invalid or inactive API key")
        raise AuthenticationFailed({'error': 'invalid_api_key'})

    def authenticate_header(self, request):
        # Non-empty string keeps DRF's status as 401 instead of upgrading to 403.
        return 'ApiKey realm="api"'
