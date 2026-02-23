import hashlib
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from files import repository

from .helpers import APITestCase, make_file, make_uploaded_file

FILES_URL = '/api/files/'


# ---------------------------------------------------------------------------
# First upload behaviour
# ---------------------------------------------------------------------------

class FirstUploadTests(APITestCase):
    """First upload of new content writes to disk and sets deduplicated=false."""

    def _upload(self, content=b'unique content', name='test.txt'):
        return self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=content, name=name)},
            format='multipart',
        )

    def test_first_upload_returns_201(self):
        self.assertEqual(self._upload().status_code, 201)

    def test_first_upload_not_deduplicated(self):
        self.assertFalse(self._upload().data['deduplicated'])

    def test_first_upload_sha256_hash_populated(self):
        content = b'content for hash check 1234'
        expected = hashlib.sha256(content).hexdigest()
        self.assertEqual(self._upload(content=content).data['sha256_hash'], expected)

    def test_first_upload_file_on_disk(self):
        from files.models import File
        r = self._upload(content=b'disk presence check')
        f = File.objects.get(pk=r.data['id'])
        self.assertTrue(os.path.exists(f.file.path))


# ---------------------------------------------------------------------------
# Duplicate upload
# ---------------------------------------------------------------------------

class DuplicateUploadTests(APITestCase):
    """Uploading identical content a second time reuses the physical file."""

    CONTENT = b'duplicate upload test content'

    def setUp(self):
        self.r1 = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=self.CONTENT, name='first.txt')},
            format='multipart',
        )

    def _upload_again(self, name='second.txt'):
        return self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=self.CONTENT, name=name)},
            format='multipart',
        )

    def test_second_upload_returns_201(self):
        self.assertEqual(self._upload_again().status_code, 201)

    def test_second_upload_is_deduplicated(self):
        self.assertTrue(self._upload_again().data['deduplicated'])

    def test_second_upload_sha256_matches(self):
        expected = hashlib.sha256(self.CONTENT).hexdigest()
        self.assertEqual(self._upload_again().data['sha256_hash'], expected)

    def test_second_upload_returns_new_id(self):
        """Deduplicated upload creates a new record with its own id."""
        self.assertNotEqual(self.r1.data['id'], self._upload_again().data['id'])

    def test_second_upload_uses_new_filename(self):
        """The new record stores the new upload's original filename."""
        r2 = self._upload_again(name='second.txt')
        self.assertEqual(r2.data['original_filename'], 'second.txt')

    def test_only_one_physical_file_on_disk(self):
        """Both records share the same physical file — only one file exists on disk."""
        from files.models import File
        r2 = self._upload_again()
        f1 = File.objects.get(pk=self.r1.data['id'])
        f2 = File.objects.get(pk=r2.data['id'])
        self.assertEqual(f1.file.name, f2.file.name)
        upload_dir = os.path.dirname(f1.file.path)
        base = os.path.basename(f1.file.name)
        matches = [n for n in os.listdir(upload_dir) if n == base]
        self.assertEqual(len(matches), 1)


# ---------------------------------------------------------------------------
# Empty-file deduplication edge case
# ---------------------------------------------------------------------------

class EmptyFileDeduplicationTests(APITestCase):
    """Two uploads of an empty file must be treated as duplicates."""

    def test_empty_files_are_deduplicated(self):
        r1 = self.client.post(
            FILES_URL, {'file': make_uploaded_file(content=b'', name='a.txt')}, format='multipart'
        )
        r2 = self.client.post(
            FILES_URL, {'file': make_uploaded_file(content=b'', name='b.txt')}, format='multipart'
        )
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertFalse(r1.data['deduplicated'])
        self.assertTrue(r2.data['deduplicated'])
        self.assertEqual(r1.data['sha256_hash'], r2.data['sha256_hash'])


# ---------------------------------------------------------------------------
# /duplicates/ endpoint
# ---------------------------------------------------------------------------

class DuplicatesEndpointTests(APITestCase):
    """/duplicates/ lists other files with the same hash (same api_key scope)."""

    CONTENT = b'duplicates endpoint test content xyz'

    def setUp(self):
        # Use the repository directly to create 3 records with the same hash
        # (bypassing view-layer deduplication), so we can test the /duplicates/
        # endpoint which must surface the other records sharing the same hash.
        import hashlib
        from django.core.files.uploadedfile import SimpleUploadedFile
        from files import repository as repo

        sha = hashlib.sha256(self.CONTENT).hexdigest()

        upload = SimpleUploadedFile('file1.txt', self.CONTENT, content_type='text/plain')
        self.f1 = repo.create_file(
            file_field=upload, original_filename='file1.txt',
            file_type='text/plain', size=len(self.CONTENT), sha256_hash=sha,
        )
        self.f2 = repo.create_file(
            file_field=self.f1.file.name, original_filename='file2.txt',
            file_type='text/plain', size=len(self.CONTENT), sha256_hash=sha,
        )
        self.f3 = repo.create_file(
            file_field=self.f1.file.name, original_filename='file3.txt',
            file_type='text/plain', size=len(self.CONTENT), sha256_hash=sha,
        )
        # Wrap ids in a response-like dict so the test assertions below
        # can stay readable.
        class _R:
            def __init__(self, f): self.data = {'id': str(f.pk)}
        self.r1, self.r2, self.r3 = _R(self.f1), _R(self.f2), _R(self.f3)

    def test_returns_200(self):
        response = self.client.get(f"{FILES_URL}{self.r1.data['id']}/duplicates/")
        self.assertEqual(response.status_code, 200)

    def test_returns_other_duplicates(self):
        response = self.client.get(f"{FILES_URL}{self.r1.data['id']}/duplicates/")
        ids = {f['id'] for f in response.data}
        self.assertIn(self.r2.data['id'], ids)
        self.assertIn(self.r3.data['id'], ids)

    def test_excludes_self(self):
        response = self.client.get(f"{FILES_URL}{self.r1.data['id']}/duplicates/")
        ids = {f['id'] for f in response.data}
        self.assertNotIn(self.r1.data['id'], ids)

    def test_returns_empty_list_for_unique_file(self):
        unique = self.client.post(
            FILES_URL, {'file': make_uploaded_file(content=b'completely unique 9999')}, format='multipart'
        )
        response = self.client.get(f"{FILES_URL}{unique.data['id']}/duplicates/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_404_for_nonexistent_file(self):
        response = self.client.get(f"{FILES_URL}00000000-0000-0000-0000-000000000000/duplicates/")
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# /duplicates/ cross-key isolation
# ---------------------------------------------------------------------------

class DuplicatesKeyIsolationTests(TestCase):
    """Duplicates endpoint only surfaces files owned by the same API key."""

    def test_cross_key_files_not_in_duplicates(self):
        content = b'cross key isolation content abc'
        expected_hash = hashlib.sha256(content).hexdigest()

        key_a = repository.create_api_key(label='Key A', key='token_key_a_isolation')
        key_b = repository.create_api_key(label='Key B', key='token_key_b_isolation')

        upload = SimpleUploadedFile('file.txt', content, content_type='text/plain')
        file_a = repository.create_file(
            file_field=upload,
            original_filename='file_a.txt',
            file_type='text/plain',
            size=len(content),
            sha256_hash=expected_hash,
            api_key=key_a,
        )
        # file_b shares the same hash/path (simulates cross-key deduplication)
        file_b = repository.create_file(
            file_field=file_a.file.name,
            original_filename='file_b.txt',
            file_type='text/plain',
            size=len(content),
            sha256_hash=expected_hash,
            api_key=key_b,
        )

        # Key A's duplicates should not include Key B's file
        dup_qs = repository.get_duplicates_for_key(file_a)
        self.assertEqual(dup_qs.count(), 0)
        self.assertNotIn(file_b.pk, dup_qs.values_list('pk', flat=True))



# ---------------------------------------------------------------------------
# Reference-counted deletion
# ---------------------------------------------------------------------------

class ReferenceCountedDeletionTests(APITestCase):
    """Physical file is deleted only when the last DB reference is removed."""

    def _upload(self, content):
        return self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=content)},
            format='multipart',
        )

    def _file_path(self, file_id):
        from files.models import File
        return File.objects.get(pk=file_id).file.path

    def test_last_reference_deletes_physical_file(self):
        r = self._upload(b'last ref delete test content abc')
        path = self._file_path(r.data['id'])
        self.assertTrue(os.path.exists(path))

        self.client.delete(f"{FILES_URL}{r.data['id']}/")
        self.assertFalse(os.path.exists(path))

    def test_not_last_reference_keeps_physical_file(self):
        """Deleting one of two records sharing a hash keeps the physical file."""
        import hashlib
        from files import repository as repo
        from files.models import File
        from .helpers import make_api_key

        content = b'not last ref delete test xyz'
        sha = hashlib.sha256(content).hexdigest()

        # First record: created via the API (anonymous)
        r1 = self._upload(content)
        f1 = File.objects.get(pk=r1.data['id'])
        path = f1.file.path

        # Second record: different API key, same hash — satisfies the unique
        # constraint (sha256_hash, api_key) while sharing the physical file.
        key2, _ = make_api_key(label='key2-not-last-ref')
        repo.create_file(
            file_field=f1.file.name, original_filename='copy.txt',
            file_type='text/plain', size=len(content),
            sha256_hash=sha, api_key=key2,
        )

        # Deleting the first record must NOT remove the disk file (another ref exists).
        self.client.delete(f"{FILES_URL}{r1.data['id']}/")
        self.assertTrue(os.path.exists(path))

    def test_deleting_last_duplicate_removes_physical_file(self):
        """Deleting the last record sharing a hash removes the physical file."""
        import hashlib
        from files import repository as repo
        from files.models import File
        from .helpers import make_api_key
        from rest_framework.test import APIClient

        content = b'both refs delete test abc xyz'
        sha = hashlib.sha256(content).hexdigest()

        # First record: anonymous upload via the API.
        r1 = self._upload(content)
        f1 = File.objects.get(pk=r1.data['id'])
        path = f1.file.path

        # Second record: different API key, same hash.
        key2, raw2 = make_api_key(label='key2-last-ref')
        f2 = repo.create_file(
            file_field=f1.file.name, original_filename='copy.txt',
            file_type='text/plain', size=len(content),
            sha256_hash=sha, api_key=key2,
        )

        # Delete r1 — f2 still references the file, so disk file must survive.
        self.client.delete(f"{FILES_URL}{r1.data['id']}/")
        self.assertTrue(os.path.exists(path))

        # Delete f2 using its own API key — this is the last reference.
        client2 = APIClient()
        client2.credentials(HTTP_AUTHORIZATION=f'ApiKey {raw2}')
        client2.delete(f"{FILES_URL}{f2.pk}/")
        self.assertFalse(os.path.exists(path))

    def test_null_hash_file_deletes_physical_file(self):
        """Files without sha256_hash (legacy) always have their disk file removed."""
        content = b'null hash content for deletion test'
        upload = SimpleUploadedFile('null_hash.txt', content, content_type='text/plain')
        file = repository.create_file(
            file_field=upload,
            original_filename='null_hash.txt',
            file_type='text/plain',
            size=len(content),
            sha256_hash=None,
        )
        path = file.file.path
        self.assertTrue(os.path.exists(path))

        from rest_framework.test import APIClient
        client = APIClient()
        client.delete(f"{FILES_URL}{file.pk}/")
        self.assertFalse(os.path.exists(path))


# ---------------------------------------------------------------------------
# File content replacement disallowed on PUT / PATCH
# ---------------------------------------------------------------------------

class FileReplacementDisallowedTests(APITestCase):
    """PUT and PATCH cannot replace file content after initial upload."""

    def setUp(self):
        self.original_content = b'original immutable file content'
        r = self.client.post(
            FILES_URL,
            {'file': make_uploaded_file(content=self.original_content, name='orig.txt')},
            format='multipart',
        )
        self.file_id = r.data['id']
        self.original_hash = r.data['sha256_hash']

    def test_put_with_file_returns_400(self):
        new_upload = make_uploaded_file(content=b'completely different content xyz', name='new.txt')
        response = self.client.put(
            f"{FILES_URL}{self.file_id}/",
            {'file': new_upload, 'original_filename': 'updated.txt'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'file_content_immutable')

    def test_patch_original_filename_works(self):
        response = self.client.patch(
            f"{FILES_URL}{self.file_id}/",
            {'original_filename': 'renamed.txt'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['original_filename'], 'renamed.txt')

    def test_patch_sha256_hash_not_modifiable(self):
        fake_hash = 'b' * 64
        response = self.client.patch(
            f"{FILES_URL}{self.file_id}/",
            {'sha256_hash': fake_hash},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['sha256_hash'], self.original_hash)
