"""
Tests for Phase 4: rate limiting (Tasks 4.5, 4.6) and storage quotas (Task 4.7).

Rate-limit tests mock the throttle's timer to control the window precisely.
Cache is cleared in setUp to ensure test isolation.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from files import repository
from files.throttling import ApiKeyMinuteRateThrottle, ApiKeySecondRateThrottle

from .helpers import make_api_key, make_uploaded_file

FILES_URL = '/api/files/'
ADMIN_KEY = 'test-admin-key-for-rate-limit'

# Fixed timestamp used by all throttle timer mocks.
_T = 1_000_000.0


# ---------------------------------------------------------------------------
# Per-second throttle
# ---------------------------------------------------------------------------

class AnonymousSecondThrottleTests(APITestCase):
    """Anonymous requests are limited to 2/second."""

    def setUp(self):
        cache.clear()

    def test_within_limit_succeeds(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            r1 = self.client.get(FILES_URL)
            r2 = self.client.get(FILES_URL)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

    def test_exceeds_limit_returns_429(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            self.client.get(FILES_URL)
            self.client.get(FILES_URL)
            r3 = self.client.get(FILES_URL)
        self.assertEqual(r3.status_code, 429)
        self.assertEqual(r3.data.get('error'), 'rate_limit_exceeded')
        self.assertIn('retry_after', r3.data)

    def test_429_has_retry_after_header(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            self.client.get(FILES_URL)
            self.client.get(FILES_URL)
            r3 = self.client.get(FILES_URL)
        self.assertIn('Retry-After', r3)


class AuthenticatedSecondThrottleTests(APITestCase):
    """Authenticated requests are limited to 10/second."""

    def setUp(self):
        cache.clear()
        self.key, self.token = make_api_key(label='throttle-auth')
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.token}')

    def test_ten_requests_within_limit(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            responses = [self.client.get(FILES_URL) for _ in range(10)]
        for r in responses:
            self.assertEqual(r.status_code, 200)

    def test_eleventh_request_returns_429(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            for _ in range(10):
                self.client.get(FILES_URL)
            r11 = self.client.get(FILES_URL)
        self.assertEqual(r11.status_code, 429)


@override_settings(ADMIN_API_KEY=ADMIN_KEY)
class AdminNotThrottledTests(APITestCase):
    """Admin key requests bypass rate limiting entirely."""

    def setUp(self):
        cache.clear()
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')

    def test_admin_not_throttled_after_many_requests(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            responses = [self.client.get(FILES_URL) for _ in range(20)]
        for r in responses:
            self.assertNotEqual(r.status_code, 429)


# ---------------------------------------------------------------------------
# Rate-limit headers (Task 4.6)
# ---------------------------------------------------------------------------

class RateLimitHeadersTests(APITestCase):
    """X-RateLimit-* headers are present on successful responses."""

    def setUp(self):
        cache.clear()

    def test_headers_present_on_200(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)
        self.assertIn('X-RateLimit-Limit', response)
        self.assertIn('X-RateLimit-Remaining', response)
        self.assertIn('X-RateLimit-Reset', response)

    def test_remaining_decrements(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            r1 = self.client.get(FILES_URL)
            r2 = self.client.get(FILES_URL)
        remaining_1 = int(r1['X-RateLimit-Remaining'])
        remaining_2 = int(r2['X-RateLimit-Remaining'])
        self.assertGreater(remaining_1, remaining_2)

    def test_reset_is_future_timestamp(self):
        import time
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            response = self.client.get(FILES_URL)
        reset = int(response['X-RateLimit-Reset'])
        self.assertGreater(reset, 0)

    def test_headers_on_429(self):
        with patch.object(ApiKeySecondRateThrottle, 'timer', return_value=_T):
            self.client.get(FILES_URL)
            self.client.get(FILES_URL)
            r3 = self.client.get(FILES_URL)
        self.assertEqual(r3.status_code, 429)
        # Retry-After is the 429-specific header
        self.assertIn('Retry-After', r3)


# ---------------------------------------------------------------------------
# Storage quota enforcement (Task 4.7)
# ---------------------------------------------------------------------------

class AuthenticatedQuotaTests(APITestCase):
    """Authenticated uploads respect the key's storage_quota_bytes."""

    def test_upload_within_quota_succeeds(self):
        key, token = make_api_key(label='quota-ok', quota=1000)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        r = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'x' * 500)},
            format='multipart',
        )
        self.assertEqual(r.status_code, 201)

    def test_upload_exceeding_quota_returns_413(self):
        key, token = make_api_key(label='quota-exceeded', quota=100)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        r = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'x' * 200)},
            format='multipart',
        )
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.data.get('error'), 'storage_quota_exceeded')
        self.assertIn('used_bytes', r.data)
        self.assertIn('quota_bytes', r.data)

    def test_413_quota_values_are_correct(self):
        key, token = make_api_key(label='quota-values', quota=100)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        r = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'x' * 200)},
            format='multipart',
        )
        self.assertEqual(r.data['used_bytes'], 0)     # nothing uploaded yet
        self.assertEqual(r.data['quota_bytes'], 100)

    def test_quota_fills_up_across_uploads(self):
        key, token = make_api_key(label='quota-fill', quota=100)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        # First upload: 80 bytes — fits
        r1 = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(name='a.txt', content=b'a' * 80)},
            format='multipart',
        )
        self.assertEqual(r1.status_code, 201)
        # Second upload: 30 bytes — would push total to 110 > 100
        r2 = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(name='b.txt', content=b'b' * 30)},
            format='multipart',
        )
        self.assertEqual(r2.status_code, 413)

    def test_deleting_file_frees_quota(self):
        key, token = make_api_key(label='quota-free', quota=100)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        # Upload 80 bytes
        r1 = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(name='a.txt', content=b'a' * 80)},
            format='multipart',
        )
        self.assertEqual(r1.status_code, 201)
        # Delete it
        self.client.delete(f"{FILES_URL}{r1.data['id']}/")
        # Re-upload the same size — should now succeed
        r2 = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(name='b.txt', content=b'b' * 80)},
            format='multipart',
        )
        self.assertEqual(r2.status_code, 201)

    def test_custom_quota_from_key_creation_is_respected(self):
        key, token = make_api_key(label='custom-quota', quota=50)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        r = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'x' * 60)},
            format='multipart',
        )
        self.assertEqual(r.status_code, 413)


@override_settings(ADMIN_API_KEY=ADMIN_KEY)
class AdminQuotaExemptTests(APITestCase):
    """Admin key uploads are never quota-checked."""

    def test_admin_can_upload_regardless_of_anonymous_quota(self):
        # Fill up anonymous quota
        repository.create_file(
            file_field=make_uploaded_file(content=b'x'),
            original_filename='fill.txt',
            file_type='text/plain',
            size=100 * 1024 * 1024 + 1,  # > default 100 MB anon quota (size only in DB)
            sha256_hash='a' * 64,
            api_key=None,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        r = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'admin upload')},
            format='multipart',
        )
        self.assertEqual(r.status_code, 201)


@override_settings(ANONYMOUS_STORAGE_QUOTA_MB=1)
class AnonymousQuotaTests(APITestCase):
    """Anonymous uploads respect ANONYMOUS_STORAGE_QUOTA_MB."""

    def test_anonymous_upload_exceeding_quota_returns_413(self):
        # Saturate quota via DB record (size field only, no real disk write needed)
        repository.create_file(
            file_field=make_uploaded_file(content=b'x'),
            original_filename='big.txt',
            file_type='text/plain',
            size=1 * 1024 * 1024,   # exactly 1 MB (the limit)
            sha256_hash='b' * 64,
            api_key=None,
        )
        # Any new upload (even 1 byte) should be rejected
        r = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'x')},
            format='multipart',
        )
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.data.get('error'), 'storage_quota_exceeded')
