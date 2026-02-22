"""
Shared test fixtures and factory helpers.

Import these into individual test modules instead of duplicating them.
"""

import secrets

from django.core.files.uploadedfile import SimpleUploadedFile

from files import repository
from files.models import DEFAULT_STORAGE_QUOTA_BYTES

VALID_HASH = 'a' * 64   # 64 lowercase hex chars — valid SHA-256 format
VALID_MIME = 'text/plain'


def make_uploaded_file(content=b'hello world', name='test.txt', mime=VALID_MIME):
    """Return a SimpleUploadedFile suitable for passing to create_file."""
    return SimpleUploadedFile(name, content, content_type=mime)


def make_api_key(label='test-key', quota=DEFAULT_STORAGE_QUOTA_BYTES):
    """Create an ApiKey via the repository and return (instance, raw_token)."""
    raw = secrets.token_hex(32)
    key = repository.create_api_key(label=label, key=raw, storage_quota_bytes=quota)
    return key, raw


def make_file(api_key=None, sha256_hash=VALID_HASH, size=11,
              content=b'hello world', name='test.txt', mime=VALID_MIME):
    """Create a File record via the repository and return the instance."""
    return repository.create_file(
        file_field=make_uploaded_file(content, name, mime),
        original_filename=name,
        file_type=mime,
        size=size,
        sha256_hash=sha256_hash,
        api_key=api_key,
    )
