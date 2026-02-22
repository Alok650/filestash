"""
Repository layer for the File model.

Centralises all database access for File records so that views and
business-logic code never build raw ORM queries themselves.  Every method
returns model instances or None; callers are responsible for serialisation
and HTTP response construction.
"""

from __future__ import annotations

import re
import uuid
from typing import Optional, Union

from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet, Sum

from .crypto import hash_api_key
from .models import DEFAULT_STORAGE_QUOTA_BYTES, ApiKey, File

# ---------------------------------------------------------------------------
# Admin auth sentinel
# A dedicated object avoids the fragility of the bare string 'admin' (which is
# case-sensitive, typo-prone, and can be confused with other string values).
# Phase 4's ApiKeyAuthentication class must set request.auth = ADMIN_AUTH for
# admin requests; all other code should check `auth is ADMIN_AUTH`.
# ---------------------------------------------------------------------------

class _AdminSentinel:
    """Singleton sentinel representing admin authentication context."""
    __slots__ = ()

    def __repr__(self) -> str:
        return '<AdminAuth>'


ADMIN_AUTH = _AdminSentinel()

# ---------------------------------------------------------------------------
# Compiled validation patterns (module-level — compiled once, not per call).
# SHA-256: 64 lowercase hex characters.
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
# MIME type per RFC 2045 tokens: ASCII printable excluding spaces and specials.
# re.ASCII ensures \w only matches [a-zA-Z0-9_], not Unicode word characters.
_MIME_RE = re.compile(r'^[a-zA-Z0-9!#$&\-^_]{1,50}/[a-zA-Z0-9!#$&\-^_.+]{1,50}$', re.ASCII)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def admin_get_file_by_id(file_id: str | uuid.UUID) -> Optional[File]:
    """Return the File with *file_id* or None.

    WARNING: performs NO ownership check.  Use only in admin/internal
    contexts.  For tenant-scoped access use ``get_file_by_id_and_key()``.
    """
    try:
        return File.objects.get(pk=file_id)
    except File.DoesNotExist:
        return None


def get_file_by_id_and_key(
    file_id: str | uuid.UUID,
    api_key: Optional[ApiKey],
) -> Optional[File]:
    """Return the File only when it is owned by *api_key*.

    For anonymous callers (api_key=None) the file must have no owning key.
    Returns None if the file does not exist or belongs to a different key.
    """
    try:
        return File.objects.get(pk=file_id, api_key=api_key)
    except File.DoesNotExist:
        return None


def get_files_for_key(api_key: Optional[ApiKey]) -> QuerySet:
    """Return a queryset of all Files owned by *api_key*.

    Pass None for anonymous access (files with no api_key).
    """
    return File.objects.filter(api_key=api_key)


def get_all_files(*, _admin_confirmed: bool = False) -> QuerySet:
    """Return a queryset of every File across all API keys.

    Callers MUST pass ``_admin_confirmed=True`` to acknowledge this is an
    admin-only operation.  The guard prevents accidental use in tenant-facing
    views.
    """
    if not _admin_confirmed:
        raise RuntimeError(
            "get_all_files() returns data across all tenants. "
            "Pass _admin_confirmed=True to confirm this is intentional."
        )
    return File.objects.all()


def get_queryset_for_auth(auth: Union[_AdminSentinel, ApiKey, None]) -> QuerySet:
    """Return the correct File queryset for the given authentication context.

    This is the single place that encodes the visibility rules:

    - ``auth is ADMIN_AUTH``       → all files across every key (admin access)
    - ``isinstance(auth, ApiKey)`` → files owned by that key only;
                                     inactive keys are treated as anonymous
    - ``auth is None``             → files with no api_key (anonymous uploads)

    The view layer's ``get_queryset()`` override should be a one-liner that
    calls this function, keeping branching logic out of the view entirely.
    """
    if auth is ADMIN_AUTH:
        return File.objects.all()
    if isinstance(auth, ApiKey):
        # Guard against a deactivated ApiKey being passed (e.g., retrieved via
        # get_api_key_by_id rather than get_api_key_by_token).  Deactivated
        # keys are treated as anonymous rather than exposing their files.
        if not auth.is_active:
            return File.objects.filter(api_key__isnull=True)
        return File.objects.filter(api_key=auth)
    return File.objects.filter(api_key__isnull=True)


def get_file_by_hash(sha256_hash: str) -> Optional[File]:
    """Return the first File whose sha256_hash matches, or None."""
    return File.objects.filter(sha256_hash=sha256_hash).first()


def get_duplicates_for_key(file: File, api_key: Optional[ApiKey]) -> QuerySet:
    """Return Files owned by *api_key* that share *file*'s hash, excluding *file* itself.

    Returns an empty queryset when *file* has no sha256_hash (NULL hashes must
    not be treated as matching each other).
    """
    if not file.sha256_hash:
        return File.objects.none()
    return File.objects.filter(
        sha256_hash=file.sha256_hash,
        api_key=api_key,
    ).exclude(pk=file.pk)


def count_references(
    sha256_hash: str,
    exclude_id: str | uuid.UUID | None = None,
) -> int:
    """Count how many File records across ALL keys share *sha256_hash*.

    Optionally excludes one record by *exclude_id* (used before deletion to
    determine whether the physical file is still needed by other records).

    Returns 0 immediately for a falsy *sha256_hash* — NULL hashes must not be
    treated as globally shared content.
    """
    if not sha256_hash:
        return 0
    qs = File.objects.filter(sha256_hash=sha256_hash)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.count()


def get_storage_used_bytes(api_key: Optional[ApiKey]) -> int:
    """Return the total bytes consumed by files owned by *api_key*.

    Pass None to compute usage for anonymous (keyless) uploads.
    Django translates ``filter(api_key=None)`` to ``WHERE api_key_id IS NULL``.
    """
    result = File.objects.filter(api_key=api_key).aggregate(total=Sum('size'))
    # Use explicit None check rather than `or 0` — the latter would mask a
    # negative aggregate caused by corrupt size values, hiding quota errors.
    return result['total'] if result['total'] is not None else 0


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def create_file(
    *,
    file_field: Union[UploadedFile, str],
    original_filename: str,
    file_type: str,
    size: int,
    sha256_hash: Optional[str] = None,
    api_key: Optional[ApiKey] = None,
) -> File:
    """Persist a new File record and return it.

    *file_field* is ``UploadedFile`` for a fresh upload or a ``str`` path for a
    deduplicated upload that reuses an existing file on disk.  Django's FileField
    stores a string path as-is without triggering a second disk write.

    Raises ValueError for invalid arguments.
    """
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
    """Update allowed mutable fields on *file* and save.

    Only *original_filename* is editable after creation.  File content,
    sha256_hash, and api_key are intentionally excluded.

    Returns *file* unchanged (no DB write) when no fields are provided.
    """
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
    """Delete the *file* DB record and optionally the physical file on disk.

    *delete_disk_file* must be True only when no other File record references
    the same physical content (determined by the caller via count_references).

    If the physical file is already absent from disk, the deletion proceeds
    gracefully — the DB record is still removed.
    """
    if delete_disk_file:
        try:
            file.file.delete(save=False)
        except OSError:
            # File already absent from disk (manually deleted, prior failed
            # cleanup, etc.).  Continue to delete the DB record.
            pass
    file.delete()


# ---------------------------------------------------------------------------
# ApiKey helpers
# ---------------------------------------------------------------------------

def get_api_key_by_token(token: str) -> Optional[ApiKey]:
    """Return an active ApiKey matching *token*, or None.

    The raw *token* is stripped of leading/trailing whitespace and then hashed
    before the DB lookup so that the plaintext secret is never compared directly
    against stored values, eliminating timing-attack and plaintext-exposure risks.
    """
    hashed = hash_api_key(token.strip())
    return ApiKey.objects.filter(key=hashed, is_active=True).first()


def get_api_key_by_id(key_id: str | uuid.UUID) -> Optional[ApiKey]:
    """Return the ApiKey with *key_id* or None.

    NOTE: returns the key regardless of its ``is_active`` state — this is
    intentional for admin use cases (e.g., viewing or deactivating a key by
    its UUID).  Do not use this function as an authentication source.
    """
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
    """Create and return a new ApiKey record.

    *key* is the raw token; only its SHA-256 hash is stored.  The caller must
    return the original *key* to the API consumer in the creation response —
    it cannot be recovered from the database afterwards.

    Raises ValueError for invalid arguments.
    """
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
    """Set *api_key* as inactive and persist.  Does not delete the record."""
    api_key.is_active = False
    api_key.save(update_fields=['is_active'])
    return api_key
