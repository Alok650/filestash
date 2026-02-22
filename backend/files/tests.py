"""
Unit tests for the repository layer (files/repository.py) and crypto module.

Each TestCase class isolates one repository concern.  Tests use the real
SQLite database (Django's TestCase wraps each test in a transaction that is
rolled back afterwards) and Django's SimpleUploadedFile for in-memory files
so no real disk writes are needed for most cases.
"""

import os
import secrets
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from files import repository
from files.crypto import hash_api_key
from files.models import DEFAULT_STORAGE_QUOTA_BYTES, ApiKey, File
from files.repository import ADMIN_AUTH

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

VALID_HASH = 'a' * 64          # 64 lowercase hex chars — valid sha256 format
VALID_MIME = 'text/plain'

def _uploaded_file(content=b'hello world', name='test.txt', mime=VALID_MIME):
    """Return a SimpleUploadedFile suitable for passing to create_file."""
    return SimpleUploadedFile(name, content, content_type=mime)


def _make_key(label='test-key', quota=DEFAULT_STORAGE_QUOTA_BYTES):
    """Create an ApiKey via the repository and return (instance, raw_token)."""
    raw = secrets.token_hex(32)
    key = repository.create_api_key(label=label, key=raw, storage_quota_bytes=quota)
    return key, raw


def _make_file(api_key=None, sha256_hash=VALID_HASH, size=11,
               content=b'hello world', name='test.txt', mime=VALID_MIME):
    """Create a File record via the repository and return the instance."""
    return repository.create_file(
        file_field=_uploaded_file(content, name, mime),
        original_filename=name,
        file_type=mime,
        size=size,
        sha256_hash=sha256_hash,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# crypto module
# ---------------------------------------------------------------------------

class HashApiKeyTests(TestCase):

    def test_returns_64_hex_chars(self):
        digest = hash_api_key('any-token')
        self.assertEqual(len(digest), 64)
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_deterministic(self):
        self.assertEqual(hash_api_key('token-x'), hash_api_key('token-x'))

    def test_different_inputs_different_outputs(self):
        self.assertNotEqual(hash_api_key('token-a'), hash_api_key('token-b'))

    def test_empty_string_does_not_raise(self):
        # SHA-256 of empty string is well-defined
        digest = hash_api_key('')
        self.assertEqual(len(digest), 64)


# ---------------------------------------------------------------------------
# ApiKey helpers
# ---------------------------------------------------------------------------

class CreateApiKeyTests(TestCase):

    def test_stores_hash_not_plaintext(self):
        raw = 'super-secret-token'
        key = repository.create_api_key(label='k', key=raw)
        self.assertNotEqual(key.key, raw)
        self.assertEqual(key.key, hash_api_key(raw))

    def test_default_quota(self):
        key, _ = _make_key()
        self.assertEqual(key.storage_quota_bytes, DEFAULT_STORAGE_QUOTA_BYTES)

    def test_custom_quota(self):
        key, _ = _make_key(quota=500)
        self.assertEqual(key.storage_quota_bytes, 500)

    def test_is_active_by_default(self):
        key, _ = _make_key()
        self.assertTrue(key.is_active)

    def test_key_is_unique(self):
        raw = secrets.token_hex(32)
        repository.create_api_key(label='first', key=raw)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            repository.create_api_key(label='second', key=raw)

    def test_str_returns_label(self):
        key, _ = _make_key(label='My Key')
        self.assertEqual(str(key), 'My Key')

    def test_rejects_empty_label(self):
        with self.assertRaises(ValueError):
            repository.create_api_key(label='', key='some-token')

    def test_rejects_whitespace_only_label(self):
        with self.assertRaises(ValueError):
            repository.create_api_key(label='   ', key='some-token')

    def test_strips_whitespace_from_label(self):
        key = repository.create_api_key(label='  My Key  ', key=secrets.token_hex(32))
        self.assertEqual(key.label, 'My Key')

    def test_rejects_empty_raw_key(self):
        with self.assertRaises(ValueError):
            repository.create_api_key(label='test', key='')

    def test_rejects_zero_quota(self):
        with self.assertRaises(ValueError):
            repository.create_api_key(label='test', key='tok', storage_quota_bytes=0)

    def test_rejects_negative_quota(self):
        with self.assertRaises(ValueError):
            repository.create_api_key(label='test', key='tok', storage_quota_bytes=-1)


class GetApiKeyByTokenTests(TestCase):

    def test_finds_active_key(self):
        key, raw = _make_key()
        found = repository.get_api_key_by_token(raw)
        self.assertEqual(found, key)

    def test_returns_none_for_wrong_token(self):
        _make_key()
        self.assertIsNone(repository.get_api_key_by_token('wrong-token'))

    def test_returns_none_for_inactive_key(self):
        key, raw = _make_key()
        repository.deactivate_api_key(key)
        self.assertIsNone(repository.get_api_key_by_token(raw))

    def test_returns_none_for_empty_token(self):
        self.assertIsNone(repository.get_api_key_by_token(''))


class GetApiKeyByIdTests(TestCase):

    def test_finds_existing_key(self):
        key, _ = _make_key()
        self.assertEqual(repository.get_api_key_by_id(key.id), key)

    def test_returns_none_for_missing_id(self):
        self.assertIsNone(repository.get_api_key_by_id(uuid.uuid4()))


class DeactivateApiKeyTests(TestCase):

    def test_sets_is_active_false(self):
        key, _ = _make_key()
        repository.deactivate_api_key(key)
        key.refresh_from_db()
        self.assertFalse(key.is_active)

    def test_does_not_delete_record(self):
        key, _ = _make_key()
        repository.deactivate_api_key(key)
        self.assertTrue(ApiKey.objects.filter(pk=key.pk).exists())

    def test_returns_the_instance(self):
        key, _ = _make_key()
        result = repository.deactivate_api_key(key)
        self.assertEqual(result.pk, key.pk)


# ---------------------------------------------------------------------------
# File — create
# ---------------------------------------------------------------------------

class CreateFileTests(TestCase):

    def test_creates_record_with_correct_fields(self):
        key, _ = _make_key()
        f = _make_file(api_key=key, size=42, name='photo.png', mime='image/png',
                       sha256_hash='b' * 64)
        self.assertEqual(f.original_filename, 'photo.png')
        self.assertEqual(f.file_type, 'image/png')
        self.assertEqual(f.size, 42)
        self.assertEqual(f.sha256_hash, 'b' * 64)
        self.assertEqual(f.api_key, key)

    def test_anonymous_file_has_null_api_key(self):
        f = _make_file(api_key=None)
        self.assertIsNone(f.api_key)

    def test_sha256_hash_can_be_null(self):
        f = repository.create_file(
            file_field=_uploaded_file(),
            original_filename='f.txt',
            file_type=VALID_MIME,
            size=5,
            sha256_hash=None,
        )
        self.assertIsNone(f.sha256_hash)

    def test_rejects_invalid_sha256_hash(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(),
                original_filename='f.txt',
                file_type=VALID_MIME,
                size=5,
                sha256_hash='not-a-hash',
            )

    def test_rejects_uppercase_sha256_hash(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(),
                original_filename='f.txt',
                file_type=VALID_MIME,
                size=5,
                sha256_hash='A' * 64,   # uppercase — invalid
            )

    def test_rejects_short_sha256_hash(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(),
                original_filename='f.txt',
                file_type=VALID_MIME,
                size=5,
                sha256_hash='a' * 63,
            )

    def test_rejects_invalid_mime_type(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(),
                original_filename='f.txt',
                file_type='not-a-mime',
                size=5,
            )

    def test_rejects_empty_mime_type(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(),
                original_filename='f.txt',
                file_type='',
                size=5,
            )

    def test_rejects_empty_original_filename(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(), original_filename='',
                file_type=VALID_MIME, size=5,
            )

    def test_rejects_whitespace_only_original_filename(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(), original_filename='   ',
                file_type=VALID_MIME, size=5,
            )

    def test_strips_whitespace_from_original_filename(self):
        f = repository.create_file(
            file_field=_uploaded_file(), original_filename='  photo.png  ',
            file_type='image/png', size=5,
        )
        self.assertEqual(f.original_filename, 'photo.png')

    def test_rejects_negative_size(self):
        with self.assertRaises(ValueError):
            repository.create_file(
                file_field=_uploaded_file(), original_filename='f.txt',
                file_type=VALID_MIME, size=-1,
            )

    def test_accepts_zero_size(self):
        f = repository.create_file(
            file_field=_uploaded_file(content=b''), original_filename='empty.txt',
            file_type=VALID_MIME, size=0,
        )
        self.assertEqual(f.size, 0)

    def test_accepts_reused_path_string_for_dedup(self):
        """A string path (dedup reuse) is stored without a second disk write."""
        f1 = _make_file(sha256_hash='c' * 64)
        existing_path = f1.file.name  # relative path stored in the DB
        f2 = repository.create_file(
            file_field=existing_path,
            original_filename='copy.txt',
            file_type=VALID_MIME,
            size=11,
            sha256_hash='c' * 64,
        )
        self.assertEqual(f2.file.name, existing_path)
        self.assertNotEqual(f2.pk, f1.pk)


# ---------------------------------------------------------------------------
# File — read
# ---------------------------------------------------------------------------

class AdminGetFileByIdTests(TestCase):

    def test_returns_file_when_found(self):
        f = _make_file()
        self.assertEqual(repository.admin_get_file_by_id(f.pk), f)

    def test_returns_none_when_not_found(self):
        self.assertIsNone(repository.admin_get_file_by_id(uuid.uuid4()))

    def test_ignores_api_key_ownership(self):
        key, _ = _make_key()
        f = _make_file(api_key=key)
        # admin lookup crosses ownership boundaries
        self.assertEqual(repository.admin_get_file_by_id(f.pk), f)


class GetFileByIdAndKeyTests(TestCase):

    def test_returns_file_for_correct_key(self):
        key, _ = _make_key()
        f = _make_file(api_key=key)
        self.assertEqual(repository.get_file_by_id_and_key(f.pk, key), f)

    def test_returns_none_for_wrong_key(self):
        key1, _ = _make_key(label='k1')
        key2, _ = _make_key(label='k2')
        f = _make_file(api_key=key1)
        self.assertIsNone(repository.get_file_by_id_and_key(f.pk, key2))

    def test_returns_none_for_anon_accessing_keyed_file(self):
        key, _ = _make_key()
        f = _make_file(api_key=key)
        self.assertIsNone(repository.get_file_by_id_and_key(f.pk, None))

    def test_returns_anon_file_for_none_key(self):
        f = _make_file(api_key=None)
        self.assertEqual(repository.get_file_by_id_and_key(f.pk, None), f)

    def test_returns_none_when_file_not_found(self):
        key, _ = _make_key()
        self.assertIsNone(repository.get_file_by_id_and_key(uuid.uuid4(), key))


class GetFilesForKeyTests(TestCase):

    def test_returns_only_owned_files(self):
        key1, _ = _make_key(label='k1')
        key2, _ = _make_key(label='k2')
        f1 = _make_file(api_key=key1)
        _make_file(api_key=key2)
        qs = repository.get_files_for_key(key1)
        self.assertQuerySetEqual(qs, [f1], ordered=False)

    def test_returns_anonymous_files_for_none(self):
        key, _ = _make_key()
        anon_file = _make_file(api_key=None)
        _make_file(api_key=key)
        qs = repository.get_files_for_key(None)
        self.assertQuerySetEqual(qs, [anon_file], ordered=False)

    def test_returns_empty_for_key_with_no_files(self):
        key, _ = _make_key()
        self.assertEqual(repository.get_files_for_key(key).count(), 0)


class GetAllFilesTests(TestCase):

    def test_raises_without_admin_flag(self):
        with self.assertRaises(RuntimeError):
            repository.get_all_files()

    def test_returns_all_files_with_flag(self):
        key, _ = _make_key()
        f1 = _make_file(api_key=key)
        f2 = _make_file(api_key=None)
        qs = repository.get_all_files(_admin_confirmed=True)
        self.assertQuerySetEqual(qs, [f1, f2], ordered=False)


class GetQuerysetForAuthTests(TestCase):

    def test_admin_sentinel_sees_all_files(self):
        key, _ = _make_key()
        f1 = _make_file(api_key=key)
        f2 = _make_file(api_key=None)
        qs = repository.get_queryset_for_auth(ADMIN_AUTH)
        self.assertQuerySetEqual(qs, [f1, f2], ordered=False)

    def test_api_key_sees_only_own_files(self):
        key1, _ = _make_key(label='k1')
        key2, _ = _make_key(label='k2')
        f1 = _make_file(api_key=key1)
        _make_file(api_key=key2)
        qs = repository.get_queryset_for_auth(key1)
        self.assertQuerySetEqual(qs, [f1], ordered=False)

    def test_none_sees_only_anonymous_files(self):
        key, _ = _make_key()
        _make_file(api_key=key)
        anon = _make_file(api_key=None)
        qs = repository.get_queryset_for_auth(None)
        self.assertQuerySetEqual(qs, [anon], ordered=False)

    def test_inactive_key_treated_as_anonymous(self):
        key, _ = _make_key()
        keyed_file = _make_file(api_key=key)
        anon_file = _make_file(api_key=None)
        repository.deactivate_api_key(key)
        key.refresh_from_db()
        qs = repository.get_queryset_for_auth(key)
        # Deactivated key must NOT expose its own files
        self.assertNotIn(keyed_file, qs)
        # Falls through to anonymous branch
        self.assertIn(anon_file, qs)


# ---------------------------------------------------------------------------
# File — hash / deduplication helpers
# ---------------------------------------------------------------------------

class GetFileByHashTests(TestCase):

    def test_returns_matching_file(self):
        f = _make_file(sha256_hash='d' * 64)
        self.assertEqual(repository.get_file_by_hash('d' * 64), f)

    def test_returns_none_when_no_match(self):
        self.assertIsNone(repository.get_file_by_hash('e' * 64))

    def test_returns_first_when_multiple_share_hash(self):
        _make_file(sha256_hash='f' * 64)
        _make_file(sha256_hash='f' * 64)
        result = repository.get_file_by_hash('f' * 64)
        self.assertIsNotNone(result)


class GetDuplicatesForKeyTests(TestCase):

    def test_returns_same_hash_files_excluding_self(self):
        key, _ = _make_key()
        f1 = _make_file(api_key=key, sha256_hash='1' * 64, name='a.txt')
        f2 = _make_file(api_key=key, sha256_hash='1' * 64, name='b.txt')
        f3 = _make_file(api_key=key, sha256_hash='1' * 64, name='c.txt')
        dupes = list(repository.get_duplicates_for_key(f1, key))
        self.assertIn(f2, dupes)
        self.assertIn(f3, dupes)
        self.assertNotIn(f1, dupes)

    def test_excludes_other_key_files(self):
        key1, _ = _make_key(label='k1')
        key2, _ = _make_key(label='k2')
        f1 = _make_file(api_key=key1, sha256_hash='2' * 64)
        _make_file(api_key=key2, sha256_hash='2' * 64)  # same hash, different key
        dupes = list(repository.get_duplicates_for_key(f1, key1))
        self.assertEqual(dupes, [])

    def test_returns_empty_when_no_duplicates(self):
        key, _ = _make_key()
        f = _make_file(api_key=key, sha256_hash='3' * 64)
        self.assertEqual(repository.get_duplicates_for_key(f, key).count(), 0)

    def test_null_hash_returns_empty_queryset(self):
        key, _ = _make_key()
        f1 = repository.create_file(
            file_field=_uploaded_file(), original_filename='x.txt',
            file_type=VALID_MIME, size=5, sha256_hash=None, api_key=key,
        )
        # Create another NULL-hash file — must NOT be returned as a duplicate
        repository.create_file(
            file_field=_uploaded_file(), original_filename='y.txt',
            file_type=VALID_MIME, size=5, sha256_hash=None, api_key=key,
        )
        result = repository.get_duplicates_for_key(f1, key)
        self.assertEqual(result.count(), 0)


class CountReferencesTests(TestCase):

    def test_counts_all_keys(self):
        key1, _ = _make_key(label='k1')
        key2, _ = _make_key(label='k2')
        _make_file(api_key=key1, sha256_hash='4' * 64)
        _make_file(api_key=key2, sha256_hash='4' * 64)
        self.assertEqual(repository.count_references('4' * 64), 2)

    def test_excludes_given_id(self):
        key, _ = _make_key()
        f = _make_file(api_key=key, sha256_hash='5' * 64)
        _make_file(api_key=key, sha256_hash='5' * 64)
        self.assertEqual(repository.count_references('5' * 64, exclude_id=f.pk), 1)

    def test_returns_zero_for_unknown_hash(self):
        self.assertEqual(repository.count_references('9' * 64), 0)

    def test_returns_zero_for_null_hash(self):
        self.assertEqual(repository.count_references(None), 0)
        self.assertEqual(repository.count_references(''), 0)


# ---------------------------------------------------------------------------
# File — storage quota
# ---------------------------------------------------------------------------

class GetStorageUsedBytesTests(TestCase):

    def test_sums_sizes_for_key(self):
        key, _ = _make_key()
        _make_file(api_key=key, size=100)
        _make_file(api_key=key, size=200)
        self.assertEqual(repository.get_storage_used_bytes(key), 300)

    def test_excludes_other_keys(self):
        key1, _ = _make_key(label='k1')
        key2, _ = _make_key(label='k2')
        _make_file(api_key=key1, size=500)
        _make_file(api_key=key2, size=999)
        self.assertEqual(repository.get_storage_used_bytes(key1), 500)

    def test_returns_zero_for_key_with_no_files(self):
        key, _ = _make_key()
        self.assertEqual(repository.get_storage_used_bytes(key), 0)

    def test_sums_anonymous_files_with_none(self):
        _make_file(api_key=None, size=50)
        _make_file(api_key=None, size=75)
        self.assertEqual(repository.get_storage_used_bytes(None), 125)

    def test_anonymous_excludes_keyed_files(self):
        key, _ = _make_key()
        _make_file(api_key=key, size=999)
        _make_file(api_key=None, size=10)
        self.assertEqual(repository.get_storage_used_bytes(None), 10)


# ---------------------------------------------------------------------------
# File — update
# ---------------------------------------------------------------------------

class UpdateFileTests(TestCase):

    def test_updates_original_filename(self):
        f = _make_file(name='old.txt')
        repository.update_file(f, original_filename='new.txt')
        f.refresh_from_db()
        self.assertEqual(f.original_filename, 'new.txt')

    def test_no_op_when_no_args_given(self):
        f = _make_file(name='unchanged.txt')
        result = repository.update_file(f)
        f.refresh_from_db()
        self.assertEqual(f.original_filename, 'unchanged.txt')
        self.assertIs(result, f)

    def test_does_not_change_other_fields(self):
        key, _ = _make_key()
        f = _make_file(api_key=key, sha256_hash='6' * 64, size=42)
        repository.update_file(f, original_filename='renamed.txt')
        f.refresh_from_db()
        self.assertEqual(f.sha256_hash, '6' * 64)
        self.assertEqual(f.size, 42)
        self.assertEqual(f.api_key, key)


# ---------------------------------------------------------------------------
# File — delete
# ---------------------------------------------------------------------------

class DeleteFileTests(TestCase):

    def test_deletes_db_record(self):
        f = _make_file()
        pk = f.pk
        repository.delete_file(f, delete_disk_file=False)
        self.assertFalse(File.objects.filter(pk=pk).exists())

    def test_delete_disk_false_leaves_physical_file(self):
        f = _make_file()
        path = f.file.path
        self.assertTrue(os.path.exists(path))
        repository.delete_file(f, delete_disk_file=False)
        self.assertTrue(os.path.exists(path))
        # cleanup
        os.remove(path)

    def test_delete_disk_true_removes_physical_file(self):
        f = _make_file()
        path = f.file.path
        self.assertTrue(os.path.exists(path))
        repository.delete_file(f, delete_disk_file=True)
        self.assertFalse(os.path.exists(path))

    def test_count_references_drives_correct_delete_choice(self):
        """Simulate the dedup deletion contract end-to-end."""
        key1, _ = _make_key(label='k1')
        key2, _ = _make_key(label='k2')
        shared_hash = '7' * 64

        f1 = _make_file(api_key=key1, sha256_hash=shared_hash)
        # Dedup: f2 reuses f1's path instead of writing a new file
        f2 = repository.create_file(
            file_field=f1.file.name,
            original_filename='copy.txt',
            file_type=VALID_MIME,
            size=11,
            sha256_hash=shared_hash,
            api_key=key2,
        )
        path = f1.file.path

        # Deleting f1: another reference exists, so keep the file on disk
        refs_before = repository.count_references(shared_hash, exclude_id=f1.pk)
        self.assertEqual(refs_before, 1)
        repository.delete_file(f1, delete_disk_file=(refs_before == 0))
        self.assertTrue(os.path.exists(path))

        # Deleting f2: last reference, delete disk file too
        refs_before = repository.count_references(shared_hash, exclude_id=f2.pk)
        self.assertEqual(refs_before, 0)
        repository.delete_file(f2, delete_disk_file=(refs_before == 0))
        self.assertFalse(os.path.exists(path))
