from rest_framework.throttling import SimpleRateThrottle

from .models import ApiKey
from .repository import ADMIN_AUTH


class _BaseApiKeyThrottle(SimpleRateThrottle):
    authenticated_rate: str
    anonymous_rate: str

    def get_rate(self):
        return self.authenticated_rate

    def get_cache_key(self, request, view):
        if isinstance(request.auth, ApiKey):
            ident = request.auth.key
        else:
            ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}

    def allow_request(self, request, view):
        if request.auth is ADMIN_AUTH:
            return True

        if isinstance(request.auth, ApiKey):
            self.rate = self.authenticated_rate
        else:
            self.rate = self.anonymous_rate
        self.num_requests, self.duration = self.parse_rate(self.rate)

        result = super().allow_request(request, view)

        remaining = max(0, self.num_requests - len(self.history))
        reset = (
            int(self.history[-1] + self.duration)
            if self.history
            else int(self.now + self.duration)
        )
        # Store on the underlying Django request for RateLimitHeadersMiddleware.
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
