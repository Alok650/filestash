import os
import re
import uuid

from django.db import models

# Single authoritative default; imported by repository.py to avoid duplication.
DEFAULT_STORAGE_QUOTA_BYTES = 1_073_741_824  # 1 GiB


def file_upload_path(instance, filename: str) -> str:
    """Generate a UUID-based storage path for a new upload.

    Only a sanitised extension (alphanumeric, 1–10 chars) is kept.  Any other
    extension — or a filename with no extension — produces a path with no
    suffix.  This prevents path-traversal payloads embedded in the extension
    from reaching the storage backend.
    """
    _, dot_ext = os.path.splitext(filename)
    safe_ext = dot_ext if dot_ext and re.fullmatch(r'\.[a-zA-Z0-9]{1,10}', dot_ext) else ''
    return os.path.join('uploads', f"{uuid.uuid4()}{safe_ext}")


class ApiKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(
        max_length=64,
        unique=True,  # unique=True already creates an index; db_index=True is redundant
        help_text="SHA-256 hash of the raw API key token; the plaintext is never stored.",
    )
    label = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    storage_quota_bytes = models.BigIntegerField(default=DEFAULT_STORAGE_QUOTA_BYTES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self) -> str:
        return self.label


class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=file_upload_path)
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100)
    size = models.BigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    sha256_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    api_key = models.ForeignKey(
        ApiKey,
        null=True,
        blank=True,
        # PROTECT prevents an ApiKey hard-delete while files still reference it,
        # forcing explicit cleanup.  Keys are soft-deleted (is_active=False) in
        # normal operation so this guard is never triggered in practice.
        on_delete=models.PROTECT,
        related_name='files',
        verbose_name="API key",
    )

    class Meta:
        db_table = 'file_record'
        ordering = ['-uploaded_at']

    def __str__(self) -> str:
        return self.original_filename
