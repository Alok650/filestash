"""
Shared test fixtures and factory helpers.

Import these into individual test modules instead of duplicating them.
"""

import secrets
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase as _DRFAPITestCase
from rest_framework.views import APIView

from files import repository
from files.models import DEFAULT_STORAGE_QUOTA_BYTES


class APITestCase(_DRFAPITestCase):
    """Drop-in replacement for DRF's APITestCase that:
    - Disables all throttle classes so rate-limit behaviour does not
      interfere with non-throttling tests.
    - Clears the cache before each test method for full isolation.

    Design note: DRF sets ``APIView.throttle_classes`` once at class-definition
    time from ``api_settings.DEFAULT_THROTTLE_CLASSES``.  Because this happens
    at import time, ``override_settings`` cannot retroactively change it.  The
    only reliable way to suppress throttling in tests is to directly patch the
    class attribute before each test method (via ``_pre_setup``/``_post_teardown``
    which run before/after ``setUp``/``tearDown`` respectively).

    Tests that specifically exercise throttling (test_rate_limiting.py) must
    import DRF's APITestCase directly and manage cache/timer mocking themselves.
    """

    def _pre_setup(self):
        super()._pre_setup()
        cache.clear()
        # Patch APIView.throttle_classes to [] so no view is throttled.
        self._throttle_patcher = patch.object(APIView, 'throttle_classes', [])
        self._throttle_patcher.start()

    def _post_teardown(self):
        if hasattr(self, '_throttle_patcher'):
            self._throttle_patcher.stop()
        super()._post_teardown()

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
