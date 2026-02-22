"""
Tests for Phase 4: API key authentication, key management endpoints,
key-scoped file visibility, and file ownership assignment.

Tasks 4.1, 4.2, 4.3, 4.4.
"""

from django.test import override_settings

from files import repository
from files.models import ApiKey

from .helpers import APITestCase, make_api_key, make_file, make_uploaded_file

FILES_URL = '/api/files/'
KEYS_URL = '/api/keys/'
ADMIN_KEY = 'test-admin-secret-key-for-tests'


# ---------------------------------------------------------------------------
# Authentication class behaviour
# ---------------------------------------------------------------------------

@override_settings(ADMIN_API_KEY=ADMIN_KEY)
class ApiKeyAuthenticationTests(APITestCase):
    """request.auth is set correctly based on the Authorization header."""

    def setUp(self):
        self.key, self.raw_token = make_api_key(label='auth-test')

    def test_no_header_is_anonymous(self):
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)  # allowed, anonymous

    def test_valid_key_returns_200(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.raw_token}')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)

    def test_admin_key_returns_200(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)

    def test_invalid_token_returns_401(self):
        self.client.credentials(HTTP_AUTHORIZATION='ApiKey totally-invalid-token')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('error'), 'invalid_api_key')

    def test_inactive_key_returns_401(self):
        repository.deactivate_api_key(self.key)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.raw_token}')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('error'), 'invalid_api_key')

    def test_wrong_scheme_is_anonymous(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_token}')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)

    def test_malformed_header_no_token_is_anonymous(self):
        self.client.credentials(HTTP_AUTHORIZATION='ApiKey ')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Key management: POST /api/keys/
# ---------------------------------------------------------------------------

@override_settings(ADMIN_API_KEY=ADMIN_KEY)
class ApiKeyCreateTests(APITestCase):
    """Admin can create new API keys; others receive 403."""

    def test_admin_creates_key(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.post(KEYS_URL, {'label': 'my-key'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('id', response.data)
        self.assertIn('key', response.data)    # raw token returned once
        self.assertIn('label', response.data)
        self.assertTrue(response.data['is_active'])

    def test_admin_creates_key_with_custom_quota(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.post(
            KEYS_URL,
            {'label': 'quota-key', 'storage_quota_bytes': 512 * 1024 * 1024},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['storage_quota_bytes'], 512 * 1024 * 1024)

    def test_key_is_64_hex_chars(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.post(KEYS_URL, {'label': 'hex-test'}, format='json')
        raw = response.data['key']
        self.assertEqual(len(raw), 64)
        self.assertRegex(raw, r'^[0-9a-f]{64}$')

    def test_anonymous_returns_403(self):
        response = self.client.post(KEYS_URL, {'label': 'x'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_non_admin_key_returns_403(self):
        _, token = make_api_key(label='regular')
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        response = self.client.post(KEYS_URL, {'label': 'x'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_missing_label_returns_400(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.post(KEYS_URL, {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_returned_token_can_authenticate(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        r = self.client.post(KEYS_URL, {'label': 'usable-key'}, format='json')
        new_token = r.data['key']
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {new_token}')
        r2 = self.client.get(FILES_URL)
        self.assertEqual(r2.status_code, 200)


@override_settings(ADMIN_API_KEY='')
class ApiKeyCreateUnconfiguredTests(APITestCase):
    """When ADMIN_API_KEY is not set, the create endpoint returns 503."""

    def test_returns_503_when_admin_key_not_configured(self):
        response = self.client.post(KEYS_URL, {'label': 'x'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data.get('error'), 'admin_key_not_configured')


# ---------------------------------------------------------------------------
# Key management: GET /api/keys/me/
# ---------------------------------------------------------------------------

class ApiKeyMeTests(APITestCase):
    """Authenticated key holders can query their own key info."""

    def setUp(self):
        self.key, self.raw_token = make_api_key(label='me-test')
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.raw_token}')

    def test_returns_key_info(self):
        response = self.client.get(f'{KEYS_URL}me/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data['id']), str(self.key.id))
        self.assertEqual(response.data['label'], 'me-test')
        self.assertTrue(response.data['is_active'])

    def test_includes_storage_used_bytes(self):
        response = self.client.get(f'{KEYS_URL}me/')
        self.assertIn('storage_used_bytes', response.data)
        self.assertEqual(response.data['storage_used_bytes'], 0)

    def test_storage_used_bytes_reflects_uploads(self):
        # Upload a file attributed to this key.
        f = repository.create_file(
            file_field=make_uploaded_file(content=b'x' * 50),
            original_filename='test.txt',
            file_type='text/plain',
            size=50,
            sha256_hash='a' * 64,
            api_key=self.key,
        )
        response = self.client.get(f'{KEYS_URL}me/')
        self.assertEqual(response.data['storage_used_bytes'], 50)

    def test_does_not_include_key_field(self):
        response = self.client.get(f'{KEYS_URL}me/')
        self.assertNotIn('key', response.data)

    def test_anonymous_returns_401(self):
        self.client.credentials()  # clear auth
        response = self.client.get(f'{KEYS_URL}me/')
        self.assertEqual(response.status_code, 401)


# ---------------------------------------------------------------------------
# Key management: DELETE /api/keys/{id}/
# ---------------------------------------------------------------------------

@override_settings(ADMIN_API_KEY=ADMIN_KEY)
class ApiKeyDeactivateTests(APITestCase):
    """Admin can deactivate keys; deactivated keys cannot authenticate."""

    def setUp(self):
        self.target_key, _ = make_api_key(label='to-deactivate')

    def test_admin_deactivates_key(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.delete(f'{KEYS_URL}{self.target_key.id}/')
        self.assertEqual(response.status_code, 204)
        self.target_key.refresh_from_db()
        self.assertFalse(self.target_key.is_active)

    def test_anonymous_returns_403(self):
        response = self.client.delete(f'{KEYS_URL}{self.target_key.id}/')
        self.assertEqual(response.status_code, 403)

    def test_non_admin_returns_403(self):
        _, token = make_api_key(label='regular')
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        response = self.client.delete(f'{KEYS_URL}{self.target_key.id}/')
        self.assertEqual(response.status_code, 403)

    def test_nonexistent_id_returns_404(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.delete(f'{KEYS_URL}00000000-0000-0000-0000-000000000000/')
        self.assertEqual(response.status_code, 404)

    def test_deactivated_key_cannot_authenticate(self):
        _, token = make_api_key(label='soon-inactive')
        key = repository.get_api_key_by_token(token)
        repository.deactivate_api_key(key)
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 401)


@override_settings(ADMIN_API_KEY='')
class ApiKeyDeactivateUnconfiguredTests(APITestCase):
    def test_returns_503_when_admin_key_not_configured(self):
        target, _ = make_api_key(label='target')
        response = self.client.delete(f'{KEYS_URL}{target.id}/')
        self.assertEqual(response.status_code, 503)


# ---------------------------------------------------------------------------
# Key-scoped file visibility (Task 4.3)
# ---------------------------------------------------------------------------

class FileScopingTests(APITestCase):
    """Each key sees only its own files; 404 on cross-key access."""

    def setUp(self):
        self.key_a, self.token_a = make_api_key(label='Key A')
        self.key_b, self.token_b = make_api_key(label='Key B')

        self.file_a = make_file(api_key=self.key_a, name='file_a.txt', content=b'aaa')
        self.file_b = make_file(api_key=self.key_b, name='file_b.txt', content=b'bbb')
        self.anon_file = make_file(api_key=None, name='anon.txt', content=b'ccc')

    def test_key_a_sees_only_its_files_in_list(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.token_a}')
        response = self.client.get(FILES_URL)
        ids = {f['id'] for f in response.data['results']}
        self.assertIn(str(self.file_a.pk), ids)
        self.assertNotIn(str(self.file_b.pk), ids)
        self.assertNotIn(str(self.anon_file.pk), ids)

    def test_key_b_sees_only_its_files_in_list(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.token_b}')
        response = self.client.get(FILES_URL)
        ids = {f['id'] for f in response.data['results']}
        self.assertNotIn(str(self.file_a.pk), ids)
        self.assertIn(str(self.file_b.pk), ids)

    def test_key_a_gets_404_on_key_b_file(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.token_a}')
        response = self.client.get(f'{FILES_URL}{self.file_b.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_anonymous_sees_only_anon_files(self):
        response = self.client.get(FILES_URL)
        ids = {f['id'] for f in response.data['results']}
        self.assertIn(str(self.anon_file.pk), ids)
        self.assertNotIn(str(self.file_a.pk), ids)
        self.assertNotIn(str(self.file_b.pk), ids)

    def test_anonymous_gets_404_on_keyed_file(self):
        response = self.client.get(f'{FILES_URL}{self.file_a.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_key_a_cannot_delete_key_b_file(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.token_a}')
        response = self.client.delete(f'{FILES_URL}{self.file_b.pk}/')
        self.assertEqual(response.status_code, 404)


@override_settings(ADMIN_API_KEY=ADMIN_KEY)
class AdminFileScopingTests(APITestCase):
    """Admin key sees all files across all keys."""

    def setUp(self):
        self.key_a, _ = make_api_key(label='Key A')
        self.file_a = make_file(api_key=self.key_a, name='a.txt', content=b'a')
        self.anon_file = make_file(api_key=None, name='anon.txt', content=b'z')

    def test_admin_sees_all_files(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.get(FILES_URL)
        ids = {f['id'] for f in response.data['results']}
        self.assertIn(str(self.file_a.pk), ids)
        self.assertIn(str(self.anon_file.pk), ids)


# ---------------------------------------------------------------------------
# File ownership on upload (Task 4.4)
# ---------------------------------------------------------------------------

class FileOwnershipTests(APITestCase):
    """Uploaded files are attributed to the requesting key."""

    def test_upload_with_key_sets_api_key(self):
        key, token = make_api_key(label='owner-test')
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {token}')
        response = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'owned content')},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201)
        from files.models import File
        f = File.objects.get(pk=response.data['id'])
        self.assertEqual(f.api_key, key)

    def test_anonymous_upload_has_no_api_key(self):
        response = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'anon content')},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201)
        from files.models import File
        f = File.objects.get(pk=response.data['id'])
        self.assertIsNone(f.api_key)

    @override_settings(ADMIN_API_KEY=ADMIN_KEY)
    def test_admin_upload_has_no_api_key(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'ApiKey {ADMIN_KEY}')
        response = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'admin content')},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201)
        from files.models import File
        f = File.objects.get(pk=response.data['id'])
        self.assertIsNone(f.api_key)

    def test_api_key_not_settable_via_request(self):
        """Client cannot inject an api_key value through the API."""
        other_key, _ = make_api_key(label='other')
        response = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=b'injection attempt'), 'api_key': str(other_key.id)},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201)
        from files.models import File
        f = File.objects.get(pk=response.data['id'])
        self.assertIsNone(f.api_key)  # api_key not set from request data
