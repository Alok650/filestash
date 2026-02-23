import hashlib

from django.test import TestCase

from files.utils import compute_sha256, hash_api_key

from .helpers import make_uploaded_file


class HashApiKeyTests(TestCase):

    def test_returns_64_hex_chars(self):
        digest = hash_api_key('any-token')
        self.assertEqual(len(digest), 64)
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_deterministic(self):
        self.assertEqual(hash_api_key('token-x'), hash_api_key('token-x'))

    def test_different_inputs_produce_different_outputs(self):
        self.assertNotEqual(hash_api_key('token-a'), hash_api_key('token-b'))

    def test_empty_string_does_not_raise(self):
        self.assertEqual(len(hash_api_key('')), 64)


class ComputeSha256Tests(TestCase):

    def test_known_content_matches_hashlib(self):
        content = b'hello world'
        expected = hashlib.sha256(content).hexdigest()
        self.assertEqual(compute_sha256(make_uploaded_file(content=content)), expected)

    def test_returns_64_lowercase_hex_chars(self):
        result = compute_sha256(make_uploaded_file(content=b'test'))
        self.assertEqual(len(result), 64)
        self.assertRegex(result, r'^[0-9a-f]{64}$')

    def test_resets_file_pointer_after_hashing(self):
        content = b'some data here'
        f = make_uploaded_file(content=content)
        compute_sha256(f)
        self.assertEqual(f.read(), content)

    def test_empty_file_hash(self):
        expected = hashlib.sha256(b'').hexdigest()
        self.assertEqual(compute_sha256(make_uploaded_file(content=b'')), expected)
