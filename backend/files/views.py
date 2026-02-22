from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response

from . import repository
from .filters import FileFilter, FileVaultFilterBackend
from .models import File
from .serializers import FileSerializer
from .utils import compute_sha256

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

        sha256 = compute_sha256(file_obj)
        existing = repository.get_file_by_hash(sha256)

        if existing:
            # Reuse the physical file already on disk; only a new DB record is created.
            new_file = repository.create_file(
                file_field=existing.file.name,
                original_filename=file_obj.name,
                file_type=file_obj.content_type,
                size=file_obj.size,
                sha256_hash=sha256,
            )
            deduplicated = True
        else:
            new_file = repository.create_file(
                file_field=file_obj,
                original_filename=file_obj.name,
                file_type=file_obj.content_type,
                size=file_obj.size,
                sha256_hash=sha256,
            )
            deduplicated = False

        context = self.get_serializer_context()
        context['deduplicated'] = deduplicated
        serializer = self.get_serializer(new_file, context=context)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        kwargs.pop('partial', False)  # we always treat as partial (see below)
        instance = self.get_object()
        # File content and sha256_hash cannot be replaced after initial upload.
        # We strip both from incoming data; using partial=True avoids the
        # "file is required" validation error that would otherwise fire on PUT.
        data = {k: v for k, v in request.data.items() if k not in ('file', 'sha256_hash')}
        serializer = self.get_serializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}
        return Response(serializer.data)

    def perform_destroy(self, instance):
        # Delete the physical file only when no other DB record shares the same hash.
        # A NULL hash means no deduplication — always delete the file from disk.
        other_refs = repository.count_references(instance.sha256_hash, exclude_id=instance.pk)
        repository.delete_file(instance, delete_disk_file=(other_refs == 0))

    @action(detail=True, methods=['get'], url_path='duplicates')
    def duplicates(self, request, pk=None):
        """Return files owned by the same API key that share this file's hash."""
        file = self.get_object()  # raises 404 if not found
        dup_qs = repository.get_duplicates_for_key(file, file.api_key)
        serializer = self.get_serializer(dup_qs, many=True)
        return Response(serializer.data)
