"""
ApiKey-based HTTP authentication for Django REST Framework.

Header format:  Authorization: ApiKey <token>

- Token matching settings.ADMIN_API_KEY  → request.auth = ADMIN_AUTH sentinel
- Token matching an active ApiKey record → request.auth = ApiKey instance
- No / malformed Authorization header   → request.auth = None  (anonymous)
- Valid format but unknown/inactive key → 401 AuthenticationFailed
"""

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
            return None  # no header or wrong scheme — anonymous

        token = auth_header[len(_SCHEME):]
        if not token:
            return None  # malformed (no token after scheme) — anonymous

        # Admin key check (short-circuit before DB lookup).
        # Use constant-time comparison to prevent timing side-channel attacks.
        admin_key = getattr(settings, 'ADMIN_API_KEY', '')
        if admin_key and hmac.compare_digest(token, admin_key):
            return (AnonymousUser(), ADMIN_AUTH)

        # Regular API key lookup (hashes the token before querying)
        api_key = get_api_key_by_token(token)
        if api_key:
            return (AnonymousUser(), api_key)

        logger.warning("Authentication failed: invalid or inactive API key")
        raise AuthenticationFailed({'error': 'invalid_api_key'})

    def authenticate_header(self, request):
        # Returning a non-empty string keeps DRF's status code as 401 instead
        # of silently upgrading AuthenticationFailed to 403.
        return 'ApiKey realm="api"'
