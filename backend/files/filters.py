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
        fields = []

    def filter_file_type(self, queryset, name, value):
        """Prefix match when value ends with '/', exact match otherwise."""
        if value.endswith('/'):
            return queryset.filter(file_type__istartswith=value)
        return queryset.filter(file_type__exact=value)


class FileVaultFilterBackend(DjangoFilterBackend):
    """DjangoFilterBackend that wraps validation errors in {"errors": {…}}."""

    def filter_queryset(self, request, queryset, view):
        filterset = self.get_filterset(request, queryset, view)
        if filterset is None:
            return queryset
        if not filterset.is_valid():
            raise DRFValidationError({'errors': filterset.errors})
        return filterset.qs
