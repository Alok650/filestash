import logging
import math

from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled exception in %s", context.get('view'))

    if response is not None:
        if response.status_code == 429:
            wait = getattr(exc, 'wait', None) or 1
            retry_after = max(1, int(math.ceil(wait)))
            response.data = {
                'error': 'rate_limit_exceeded',
                'retry_after': retry_after,
            }
            response['Retry-After'] = str(retry_after)
        elif isinstance(response.data, dict) and set(response.data.keys()) == {'detail'}:
            response.data = {'error': str(response.data['detail'])}

    return response
