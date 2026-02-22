from rest_framework import viewsets, status
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response

from .filters import FileFilter, FileVaultFilterBackend
from .models import File
from .serializers import FileSerializer

# Fields the client may sort by.  Any other value triggers a 400.
VALID_ORDERING_FIELDS = ['original_filename', 'size', 'uploaded_at']


class FileViewSet(viewsets.ModelViewSet):
    queryset = File.objects.all()
    serializer_class = FileSerializer

    filter_backends = [FileVaultFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = FileFilter
    search_fields = ['original_filename']
    ordering_fields = VALID_ORDERING_FIELDS
    ordering = ['-uploaded_at']

    def filter_queryset(self, queryset):
        # Validate ordering field(s) before delegating to filter backends.
        # DRF's OrderingFilter silently ignores invalid fields; we want a 400.
        ordering_param = self.request.query_params.get('ordering', '').strip()
        if ordering_param:
            for token in ordering_param.split(','):
                field = token.strip().lstrip('-')
                if field and field not in VALID_ORDERING_FIELDS:
                    raise ValidationError({
                        'errors': {
                            'ordering': [
                                f"Invalid ordering field: '{field}'. "
                                f"Valid fields: {', '.join(VALID_ORDERING_FIELDS)}."
                            ]
                        }
                    })

        queryset = super().filter_queryset(queryset)

        # Append 'id' as a tiebreaker so cursor pagination is always stable,
        # even when multiple records share the same value for the sort field.
        current_ordering = list(queryset.query.order_by)
        if not current_ordering:
            # No explicit order_by set; fall back to model Meta ordering.
            meta = queryset.model._meta.ordering
            current_ordering = list(meta) if meta else ['-uploaded_at']

        if 'id' not in current_ordering and '-id' not in current_ordering:
            current_ordering.append('id')

        return queryset.order_by(*current_ordering)

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response(
                {'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST
            )

        data = {
            'file': file_obj,
            'original_filename': file_obj.name,
            'file_type': file_obj.content_type,
            'size': file_obj.size,
        }

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )
