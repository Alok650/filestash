from __future__ import annotations

import logging
import re
import uuid
from typing import Optional, Union

logger = logging.getLogger(__name__)

from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet, Sum

from .utils import hash_api_key
from .constants import DEFAULT_STORAGE_QUOTA_BYTES
from .models import ApiKey, File


class _AdminSentinel:
    """Singleton placed in request.auth to represent admin-level access.
    Using a typed sentinel (instead of a string or bool) makes isinstance()
    checks unambiguous — no ApiKey value can accidentally match it."""
    __slots__ = ()

    def __repr__(self) -> str:
        return '<AdminAuth>'


ADMIN_AUTH = _AdminSentinel()

# Type alias for the three possible values of request.auth in this project.
AuthContext = Union[_AdminSentinel, ApiKey, None]

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_MIME_RE = re.compile(r'^[a-zA-Z0-9!#$&\-^_]{1,50}/[a-zA-Z0-9!#$&\-^_.+]{1,50}$', re.ASCII)


# Read helpers

def admin_get_file_by_id(file_id: str | uuid.UUID) -> Optional[File]:
    """Return the File with file_id or None."""
    try:
        return File.objects.get(pk=file_id)
    except File.DoesNotExist:
        return None


def get_file_by_id_and_key(
    file_id: str | uuid.UUID,
    api_key: Optional[ApiKey],
) -> Optional[File]:
    try:
        return File.objects.get(pk=file_id, api_key=api_key)
    except File.DoesNotExist:
        return None


def get_files_for_key(api_key: Optional[ApiKey]) -> QuerySet:
    return File.objects.filter(api_key=api_key)


def get_all_files(*, _admin_confirmed: bool = False) -> QuerySet:
    """Return all Files across all API keys. Requires _admin_confirmed=True."""
    if not _admin_confirmed:
        raise RuntimeError(
            "get_all_files() returns data across all tenants. "
            "Pass _admin_confirmed=True to confirm this is intentional."
        )
    return File.objects.all()


def get_queryset_for_auth(auth: AuthContext) -> QuerySet:
    """Return the correct queryset for the given auth context."""
    if auth is ADMIN_AUTH:
        return File.objects.all()
    if isinstance(auth, ApiKey):
        if not auth.is_active:
            return File.objects.filter(api_key__isnull=True)
        return File.objects.filter(api_key=auth)
    return File.objects.filter(api_key__isnull=True)


def get_file_by_hash(sha256_hash: str) -> Optional[File]:
    """Return the first File with sha256_hash across ALL keys, or None."""
    return File.objects.filter(sha256_hash=sha256_hash).first()


def get_file_by_hash_and_key(
    sha256_hash: str,
    api_key: Optional[ApiKey],
) -> Optional[File]:
    return File.objects.filter(sha256_hash=sha256_hash, api_key=api_key).first()


def get_duplicates_for_key(file: File) -> QuerySet:
    """Return Files sharing file's hash and owner, excluding file itself."""
    if not file.sha256_hash:
        return File.objects.none()
    return File.objects.filter(
        sha256_hash=file.sha256_hash,
        api_key=file.api_key,
    ).exclude(pk=file.pk)


def count_references(
    sha256_hash: str,
    exclude_id: str | uuid.UUID | None = None,
) -> int:
    """Count File records across all keys sharing sha256_hash."""
    if not sha256_hash:
        return 0
    qs = File.objects.filter(sha256_hash=sha256_hash)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.count()


def get_storage_used_bytes(api_key: Optional[ApiKey]) -> int:
    """Return total bytes used by files owned by api_key (None = anonymous pool)."""
    result = File.objects.filter(api_key=api_key).aggregate(total=Sum('size'))
    return result['total'] if result['total'] is not None else 0


# Write helpers

def create_file(
    *,
    file_field: Union[UploadedFile, str],
    original_filename: str,
    file_type: str,
    size: int,
    sha256_hash: Optional[str] = None,
    api_key: Optional[ApiKey] = None,
) -> File:
    """Persist a new File record and return it. Raises ValueError for invalid args."""
    original_filename = original_filename.strip()
    if not original_filename:
        raise ValueError("original_filename must not be empty.")
    if len(original_filename) > 255:
        raise ValueError("original_filename must not exceed 255 characters.")

    if size < 0:
        raise ValueError(f"size must be non-negative, got {size}.")

    if sha256_hash is not None and not _SHA256_RE.fullmatch(sha256_hash):
        raise ValueError(
            f"Invalid sha256_hash '{sha256_hash}': must be 64 lowercase hex characters."
        )
    if not _MIME_RE.fullmatch(file_type):
        raise ValueError(
            f"Invalid file_type '{file_type}': must be a valid ASCII MIME type "
            f"(e.g. 'image/png', 'application/pdf')."
        )
    return File.objects.create(
        file=file_field,
        original_filename=original_filename,
        file_type=file_type,
        size=size,
        sha256_hash=sha256_hash,
        api_key=api_key,
    )


def update_file(file: File, *, original_filename: Optional[str] = None) -> File:
    """Update original_filename on file."""
    if original_filename is None:
        return file
    original_filename = original_filename.strip()
    if not original_filename:
        raise ValueError("original_filename must not be empty.")
    if len(original_filename) > 255:
        raise ValueError("original_filename must not exceed 255 characters.")
    file.original_filename = original_filename
    file.save(update_fields=['original_filename'])
    return file


def delete_file(file: File, *, delete_disk_file: bool) -> None:
    """Delete file DB record and optionally the physical file on disk."""
    if delete_disk_file:
        try:
            file.file.delete(save=False)
        except OSError:
            logger.warning("Could not delete disk file: id=%s path=%s", file.pk, file.file.name)
    file.delete()


# ApiKey helpers

def get_api_key_by_token(token: str) -> Optional[ApiKey]:
    """Return an active ApiKey matching token, or None."""
    hashed = hash_api_key(token.strip())
    return ApiKey.objects.filter(key=hashed, is_active=True).first()


def get_api_key_by_id(key_id: str | uuid.UUID) -> Optional[ApiKey]:
    """Return the ApiKey with key_id or None, regardless of is_active state."""
    try:
        return ApiKey.objects.get(pk=key_id)
    except ApiKey.DoesNotExist:
        return None


def create_api_key(
    *,
    label: str,
    key: str,
    storage_quota_bytes: int = DEFAULT_STORAGE_QUOTA_BYTES,
) -> ApiKey:
    """Create and return a new ApiKey. key is the raw token (only its hash is stored)."""
    label = label.strip()
    if not label:
        raise ValueError("label must not be empty.")
    if len(label) > 100:
        raise ValueError("label must not exceed 100 characters.")

    if not key:
        raise ValueError("key (raw token) must not be empty.")

    if storage_quota_bytes <= 0:
        raise ValueError(
            f"storage_quota_bytes must be positive, got {storage_quota_bytes}."
        )

    return ApiKey.objects.create(
        key=hash_api_key(key),
        label=label,
        storage_quota_bytes=storage_quota_bytes,
    )


def deactivate_api_key(api_key: ApiKey) -> ApiKey:
    api_key.is_active = False
    api_key.save(update_fields=['is_active'])
    return api_key
