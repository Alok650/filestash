import logging
import secrets

from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import repository
from .filters import FileFilter, FileVaultFilterBackend
from .models import ApiKey, File
from .repository import ADMIN_AUTH
from .serializers import ApiKeyCreateSerializer, ApiKeyDetailSerializer, FileSerializer
from .utils import compute_sha256

logger = logging.getLogger(__name__)


class _AdminKeyNotConfigured(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = {'error': 'admin_key_not_configured'}
    default_code = 'admin_key_not_configured'


class IsAdminApiKey(BasePermission):
    """Allow access only to requests authenticated with the admin API key.

    Raises 503 when ADMIN_API_KEY is not configured, 403 for all other callers
    (including anonymous — admin-only endpoints don't distinguish unauthenticated
    from authenticated-but-unauthorized).
    """

    def has_permission(self, request, view):
        if not getattr(settings, 'ADMIN_API_KEY', ''):
            raise _AdminKeyNotConfigured()
        if request.auth is not ADMIN_AUTH:
            raise PermissionDenied({'error': 'forbidden'})
        return True

# Fields the client may sort by.  Any other value triggers a 400.
VALID_ORDERING_FIELDS = ['original_filename', 'size', 'uploaded_at']


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------

class FileViewSet(viewsets.ModelViewSet):
    serializer_class = FileSerializer

    filter_backends = [FileVaultFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = FileFilter
    search_fields = ['original_filename']
    ordering_fields = VALID_ORDERING_FIELDS
    ordering = ['-uploaded_at']

    def get_queryset(self):
        """Scope file visibility to the requesting key (or anonymous pool)."""
        return repository.get_queryset_for_auth(self.request.auth)

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

        # Determine the owning key (admin uploads are anonymous — no owner key).
        api_key = request.auth if isinstance(request.auth, ApiKey) else None
        is_admin = request.auth is ADMIN_AUTH

        # --- Quota check (before any disk/DB writes) ---
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

        # --- Deduplication ---
        sha256 = compute_sha256(file_obj)
        existing = repository.get_file_by_hash(sha256)
        deduplicated = existing is not None
        new_file = repository.create_file(
            # Reuse the physical file path when a duplicate exists; otherwise
            # pass the uploaded file object so Django writes it to disk.
            file_field=existing.file.name if existing else file_obj,
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
        delete_disk = other_refs == 0
        logger.info(
            "File deleted: id=%s sha256=%.16s... disk_deleted=%s",
            instance.pk, instance.sha256_hash or 'null', delete_disk,
        )
        repository.delete_file(instance, delete_disk_file=delete_disk)

    @action(detail=True, methods=['get'], url_path='duplicates')
    def duplicates(self, request, pk=None):
        """Return files owned by the same API key that share this file's hash."""
        file = self.get_object()  # raises 404 if not found or not owned by requester
        dup_qs = repository.get_duplicates_for_key(file)
        serializer = self.get_serializer(dup_qs, many=True)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# API key management  (admin-only create/deactivate, self-service /me)
# ---------------------------------------------------------------------------

class ApiKeyCreateView(APIView):
    """POST /api/keys/ — create a new API key (admin only)."""

    permission_classes = [IsAdminApiKey]

    def post(self, request):
        label = request.data.get('label', '').strip()
        if not label:
            return Response({'error': 'label is required'}, status=status.HTTP_400_BAD_REQUEST)

        quota = request.data.get(
            'storage_quota_bytes', repository.DEFAULT_STORAGE_QUOTA_BYTES
        )
        try:
            quota = int(quota)
        except (TypeError, ValueError):
            return Response(
                {'error': 'storage_quota_bytes must be an integer'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_token = secrets.token_hex(32)
        try:
            api_key = repository.create_api_key(
                label=label, key=raw_token, storage_quota_bytes=quota
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("API key created: id=%s label=%s", api_key.id, api_key.label)
        # Build response with the raw token visible (cannot be recovered later).
        serializer = ApiKeyCreateSerializer(api_key)
        data = dict(serializer.data)
        data['key'] = raw_token   # replace the stored hash with the plaintext token
        return Response(data, status=status.HTTP_201_CREATED)


class ApiKeyMeView(APIView):
    """GET /api/keys/me/ — return the authenticated key's info and storage usage."""

    def get(self, request):
        if not isinstance(request.auth, ApiKey):
            return Response(
                {'error': 'authentication_required'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        api_key = request.auth
        used = repository.get_storage_used_bytes(api_key)
        serializer = ApiKeyDetailSerializer(api_key, context={'storage_used_bytes': used})
        return Response(serializer.data)


class ApiKeyDeactivateView(APIView):
    """DELETE /api/keys/{pk}/ — deactivate a key (admin only)."""

    permission_classes = [IsAdminApiKey]

    def delete(self, request, pk):
        api_key = repository.get_api_key_by_id(pk)
        if not api_key:
            return Response(status=status.HTTP_404_NOT_FOUND)

        repository.deactivate_api_key(api_key)
        logger.info("API key deactivated: id=%s label=%s", api_key.id, api_key.label)
        return Response(status=status.HTTP_204_NO_CONTENT)
