"""
Cursor-based pagination for the File Vault API.

Uses DRF's CursorPagination with two additions:
  - A ``count`` field in every response (total matching records, not just current page)
  - Page-size clamping (values outside 1–100 are silently clamped, not rejected)
"""

from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class FileVaultCursorPagination(CursorPagination):
    page_size = 20
    max_page_size = 100
    page_size_query_param = 'page_size'
    ordering = '-uploaded_at'  # default; view/OrderingFilter may override

    # Captured in paginate_queryset() so get_paginated_response() can COUNT it.
    _full_queryset = None

    def get_page_size(self, request):
        """Clamp page_size to [1, max_page_size] instead of raising on bad input."""
        if self.page_size_query_param:
            try:
                raw = int(request.query_params[self.page_size_query_param])
                return max(1, min(raw, self.max_page_size))
            except (KeyError, ValueError, TypeError):
                pass
        return self.page_size

    def paginate_queryset(self, queryset, request, view=None):
        # Capture the full filtered queryset before CursorPagination slices it.
        self._full_queryset = queryset
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        count = self._full_queryset.count() if self._full_queryset is not None else None
        return Response({
            'count': count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
        })

    def get_paginated_response_schema(self, schema):
        return {
            'type': 'object',
            'properties': {
                'count': {'type': 'integer', 'example': 123},
                'next': {'type': 'string', 'nullable': True, 'format': 'uri'},
                'previous': {'type': 'string', 'nullable': True, 'format': 'uri'},
                'results': schema,
            },
        }
