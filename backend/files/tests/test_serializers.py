"""
Tests for files/serializers.py — FileSerializer.

Covers: sha256_hash present in list and detail responses,
null sha256_hash, and read-only enforcement via PATCH.
"""

from rest_framework.test import APITestCase

from files import repository

from .helpers import VALID_MIME, make_file, make_uploaded_file

FILES_URL = '/api/files/'


class Sha256HashSerializerTests(APITestCase):
    """sha256_hash is serialized in responses and is read-only."""

    def test_sha256_hash_present_in_list_response(self):
        make_file(sha256_hash='a' * 64)
        response = self.client.get(FILES_URL)
        self.assertIn('sha256_hash', response.data['results'][0])

    def test_sha256_hash_value_correct_in_list(self):
        make_file(sha256_hash='a' * 64)
        response = self.client.get(FILES_URL)
        self.assertEqual(response.data['results'][0]['sha256_hash'], 'a' * 64)

    def test_sha256_hash_present_in_detail_response(self):
        f = make_file(sha256_hash='b' * 64)
        response = self.client.get(f'{FILES_URL}{f.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('sha256_hash', response.data)
        self.assertEqual(response.data['sha256_hash'], 'b' * 64)

    def test_sha256_hash_null_when_not_set(self):
        f = repository.create_file(
            file_field=make_uploaded_file(),
            original_filename='nosha.txt',
            file_type=VALID_MIME,
            size=5,
            sha256_hash=None,
        )
        response = self.client.get(f'{FILES_URL}{f.pk}/')
        self.assertIsNone(response.data['sha256_hash'])

    def test_sha256_hash_is_read_only_via_patch(self):
        f = make_file(sha256_hash='c' * 64)
        self.client.patch(
            f'{FILES_URL}{f.pk}/', {'sha256_hash': 'd' * 64}, format='json'
        )
        f.refresh_from_db()
        self.assertEqual(f.sha256_hash, 'c' * 64)
