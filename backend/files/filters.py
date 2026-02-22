"""
FilterSet for the File list endpoint.

Registered on FileViewSet via filterset_class.  Filter backends are kept on
the viewset (not in REST_FRAMEWORK settings) so future viewsets are unaffected.

Filter parameters:
  file_type      - exact MIME type ("image/png") or prefix ("image/")
  uploaded_after - ISO-8601 datetime; returns files uploaded at or after
  uploaded_before - ISO-8601 datetime; returns files uploaded at or before

The ``search`` parameter (filename substring) is handled by DRF's SearchFilter.
The ``ordering`` parameter is handled by DRF's OrderingFilter.
"""

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.exceptions import ValidationError as DRFValidationError

from .models import File


class FileFilter(django_filters.FilterSet):
    file_type = django_filters.CharFilter(method='filter_file_type')
    uploaded_after = django_filters.IsoDateTimeFilter(
        field_name='uploaded_at', lookup_expr='gte'
    )
    uploaded_before = django_filters.IsoDateTimeFilter(
        field_name='uploaded_at', lookup_expr='lte'
    )

    class Meta:
        model = File
        fields = []  # All filters are declared explicitly above

    def filter_file_type(self, queryset, name, value):
        """Prefix match when value ends with '/', exact match otherwise."""
        if value.endswith('/'):
            return queryset.filter(file_type__istartswith=value)
        return queryset.filter(file_type__exact=value)


class FileVaultFilterBackend(DjangoFilterBackend):
    """DjangoFilterBackend subclass that wraps validation errors in {"errors": {…}}.

    This keeps the error envelope consistent with the ordering-validation errors
    raised directly in FileViewSet.filter_queryset().
    """

    def filter_queryset(self, request, queryset, view):
        filterset = self.get_filterset(request, queryset, view)
        if filterset is None:
            return queryset
        if not filterset.is_valid():
            raise DRFValidationError({'errors': filterset.errors})
        return filterset.qs
