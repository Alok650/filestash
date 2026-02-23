import secrets
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase as _DRFAPITestCase
from rest_framework.views import APIView

from files import repository
from files.models import DEFAULT_STORAGE_QUOTA_BYTES


class APITestCase(_DRFAPITestCase):
    """DRF APITestCase with throttles disabled and cache cleared per test."""

    def _pre_setup(self):
        super()._pre_setup()
        cache.clear()
        self._throttle_patcher = patch.object(APIView, 'throttle_classes', [])
        self._throttle_patcher.start()

    def _post_teardown(self):
        if hasattr(self, '_throttle_patcher'):
            self._throttle_patcher.stop()
        super()._post_teardown()


VALID_HASH = 'a' * 64
VALID_MIME = 'text/plain'


def make_uploaded_file(content=b'hello world', name='test.txt', mime=VALID_MIME):
    return SimpleUploadedFile(name, content, content_type=mime)


def make_api_key(label='test-key', quota=DEFAULT_STORAGE_QUOTA_BYTES):
    """Create an ApiKey via the repository and return (instance, raw_token)."""
    raw = secrets.token_hex(32)
    key = repository.create_api_key(label=label, key=raw, storage_quota_bytes=quota)
    return key, raw


def make_file(api_key=None, sha256_hash=None, size=11,
              content=b'hello world', name='test.txt', mime=VALID_MIME):
    """Create a File record via the repository and return the instance."""
    if sha256_hash is None:
        sha256_hash = secrets.token_hex(32)
    return repository.create_file(
        file_field=make_uploaded_file(content, name, mime),
        original_filename=name,
        file_type=mime,
        size=size,
        sha256_hash=sha256_hash,
        api_key=api_key,
    )
