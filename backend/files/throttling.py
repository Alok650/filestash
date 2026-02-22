"""
Custom DRF throttle classes for API key and anonymous rate limiting.

Two throttles are applied to every request:
  - ApiKeySecondRateThrottle  : 10/s authenticated, 2/s anonymous
  - ApiKeyMinuteRateThrottle  : 300/min authenticated, 30/min anonymous

Admin requests (request.auth is ADMIN_AUTH) bypass both throttles.

After each allowed request, rate-limit state is stored on request._rate_limit_info
so that X-RateLimit-* headers can be injected by RateLimitHeadersMiddleware.
"""

from rest_framework.throttling import SimpleRateThrottle

from .models import ApiKey
from .repository import ADMIN_AUTH


class _BaseApiKeyThrottle(SimpleRateThrottle):
    """Base class shared by per-second and per-minute throttles."""

    authenticated_rate: str
    anonymous_rate: str

    def get_rate(self):
        # Called in __init__ before the request is available.
        # Return the authenticated rate as a safe default; the actual rate is
        # overridden per-request inside allow_request().
        return self.authenticated_rate

    def get_cache_key(self, request, view):
        if isinstance(request.auth, ApiKey):
            ident = request.auth.key           # throttle by hashed key value
        else:
            ident = self.get_ident(request)    # throttle by client IP
        return self.cache_format % {'scope': self.scope, 'ident': ident}

    def allow_request(self, request, view):
        # Admin requests are never rate-limited.
        if request.auth is ADMIN_AUTH:
            return True

        # Select rate based on auth type.
        if isinstance(request.auth, ApiKey):
            self.rate = self.authenticated_rate
        else:
            self.rate = self.anonymous_rate
        self.num_requests, self.duration = self.parse_rate(self.rate)

        result = super().allow_request(request, view)

        # Store rate-limit state for response headers.
        # self.history reflects the window AFTER the current request was recorded
        # (or before, if the request was rejected).
        remaining = max(0, self.num_requests - len(self.history))
        reset = (
            int(self.history[-1] + self.duration)
            if self.history
            else int(self.now + self.duration)
        )
        # Store state on the underlying Django HttpRequest so that
        # RateLimitHeadersMiddleware (which sees the Django request, not the
        # DRF wrapper) can read it and inject X-RateLimit-* headers.
        django_request = getattr(request, '_request', request)
        existing = getattr(django_request, '_rate_limit_info', None)
        if existing is None or remaining < existing['remaining']:
            django_request._rate_limit_info = {
                'limit': self.num_requests,
                'remaining': remaining,
                'reset': reset,
            }

        return result


class ApiKeySecondRateThrottle(_BaseApiKeyThrottle):
    scope = 'api_key_second'
    authenticated_rate = '10/second'
    anonymous_rate = '2/second'


class ApiKeyMinuteRateThrottle(_BaseApiKeyThrottle):
    scope = 'api_key_minute'
    authenticated_rate = '300/minute'
    anonymous_rate = '30/minute'
