"""
Middleware that injects X-RateLimit-* headers into every API response.

The throttle classes store state on request._rate_limit_info after each
allowed request.  This middleware reads that state and adds the headers.

No-op when _rate_limit_info is absent (admin requests, static files, etc.).
"""


class RateLimitHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        info = getattr(request, '_rate_limit_info', None)
        if info:
            response['X-RateLimit-Limit'] = str(info['limit'])
            response['X-RateLimit-Remaining'] = str(info['remaining'])
            response['X-RateLimit-Reset'] = str(info['reset'])
        return response
