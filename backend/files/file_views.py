import logging

from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response

from . import repository
from .filters import FileFilter, FileVaultFilterBackend
from .models import ApiKey
from .repository import ADMIN_AUTH
from .serializers import FileSerializer
from .utils import compute_sha256

logger = logging.getLogger(__name__)

VALID_ORDERING_FIELDS = ['original_filename', 'size', 'uploaded_at']

# File types that can execute or render as markup in browsers.
_BLOCKED_CONTENT_TYPES = frozenset({
    'text/html', 'application/xhtml+xml', 'image/svg+xml',
    'application/javascript', 'text/javascript',
})


class FileViewSet(viewsets.ModelViewSet):
    serializer_class = FileSerializer

    filter_backends = [FileVaultFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = FileFilter
    search_fields = ['original_filename']
    ordering_fields = VALID_ORDERING_FIELDS
    ordering = ['-uploaded_at']

    def get_queryset(self):
        return repository.get_queryset_for_auth(self.request.auth)

    def filter_queryset(self, queryset):
        ordering_param = self.request.query_params.get('ordering', '').strip()
        if ordering_param:
            for token in ordering_param.split(','):
                field = token.strip().lstrip('-')
                if field and field not in self.ordering_fields:
                    raise ValidationError({
                        'errors': {
                            'ordering': [
                                f"Invalid ordering field: '{field}'. "
                                f"Valid fields: {', '.join(self.ordering_fields)}."
                            ]
                        }
                    })

        queryset = super().filter_queryset(queryset)

        # Append 'id' as a tiebreaker for stable cursor pagination.
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
                {'error': 'no_file_provided'}, status=status.HTTP_400_BAD_REQUEST
            )

        if file_obj.content_type in _BLOCKED_CONTENT_TYPES:
            return Response(
                {'error': 'file_type_not_allowed', 'file_type': file_obj.content_type},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        api_key = request.auth if isinstance(request.auth, ApiKey) else None
        is_admin = request.auth is ADMIN_AUTH

        if not is_admin:
            if api_key:
                used = repository.get_storage_used_bytes(api_key)
                quota = api_key.storage_quota_bytes
            else:
                used = repository.get_storage_used_bytes(None)
                quota = settings.ANONYMOUS_STORAGE_QUOTA_MB * 1024 * 1024

            if used + file_obj.size > quota:
                logger.warning(
                    "Storage quota exceeded: api_key=%s used=%d quota=%d file_size=%d",
                    getattr(api_key, 'id', 'anonymous'), used, quota, file_obj.size,
                )
                return Response(
                    {
                        'error': 'storage_quota_exceeded',
                        'used_bytes': used,
                        'quota_bytes': quota,
                    },
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )

        sha256 = compute_sha256(file_obj)

        # Reuse the physical file if the content already exists anywhere.
        # Always create a new DB record so each upload gets its own id,
        # original_filename, and uploaded_at.
        existing = repository.get_file_by_hash(sha256)
        deduplicated = existing is not None
        file_source = existing.file.name if deduplicated else file_obj

        new_file = repository.create_file(
            file_field=file_source,
            original_filename=file_obj.name,
            file_type=file_obj.content_type,
            size=file_obj.size,
            sha256_hash=sha256,
            api_key=api_key,
        )

        logger.info(
            "File created: id=%s sha256=%.16s... deduplicated=%s api_key=%s",
            new_file.pk, sha256, deduplicated, getattr(api_key, 'id', 'anonymous'),
        )
        serializer = self.get_serializer(
            new_file,
            context={**self.get_serializer_context(), 'deduplicated': deduplicated},
        )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        if 'file' in request.data:
            return Response(
                {'error': 'file_content_immutable'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kwargs.pop('partial', False)
        instance = self.get_object()
        # sha256_hash is in read_only_fields — serializer silently ignores it.
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}
        return Response(serializer.data)

    def perform_destroy(self, instance):
        other_refs = repository.count_references(instance.sha256_hash, exclude_id=instance.pk)
        delete_disk = other_refs == 0
        logger.info(
            "File deleted: id=%s sha256=%.16s... disk_deleted=%s",
            instance.pk, instance.sha256_hash or 'null', delete_disk,
        )
        repository.delete_file(instance, delete_disk_file=delete_disk)

    @action(detail=True, methods=['get'], url_path='duplicates')
    def duplicates(self, request, pk=None):
        """Return files owned by the same API key that share this file's hash."""
        file = self.get_object()
        dup_qs = repository.get_duplicates_for_key(file)
        serializer = self.get_serializer(dup_qs, many=True)
        return Response(serializer.data)
