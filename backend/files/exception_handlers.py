"""
Custom DRF exception handler.

Formats 429 Throttled responses as:
  {"error": "rate_limit_exceeded", "retry_after": <seconds>}
and adds the standard Retry-After header.
"""

import math

from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None and response.status_code == 429:
        wait = getattr(exc, 'wait', None) or 1
        retry_after = max(1, int(math.ceil(wait)))
        response.data = {
            'error': 'rate_limit_exceeded',
            'retry_after': retry_after,
        }
        response['Retry-After'] = str(retry_after)

    return response
