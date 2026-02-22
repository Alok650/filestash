"""
Tests for files/crypto.py — hash_api_key().
"""

from django.test import TestCase

from files.crypto import hash_api_key


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
        # SHA-256 of the empty string is well-defined.
        digest = hash_api_key('')
        self.assertEqual(len(digest), 64)
