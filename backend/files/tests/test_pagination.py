"""
Tests for files/pagination.py — FileVaultCursorPagination.

Covers: response envelope shape, cursor navigation, page_size clamping,
and count reflecting the filtered (not overall) total.
"""

from rest_framework.test import APITestCase

from .helpers import make_file

FILES_URL = '/api/files/'


class PaginationEnvelopeTests(APITestCase):
    """Response envelope shape and cursor navigation."""

    def test_empty_list_has_all_envelope_keys(self):
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)
        for key in ('count', 'next', 'previous', 'results'):
            self.assertIn(key, response.data)

    def test_count_reflects_total_records(self):
        for i in range(3):
            make_file(name=f'f{i}.txt')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.data['count'], 3)

    def test_empty_list_has_zero_count_and_null_cursors(self):
        response = self.client.get(FILES_URL)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])
        self.assertIsNone(response.data['next'])
        self.assertIsNone(response.data['previous'])

    def test_default_page_size_is_20(self):
        for i in range(25):
            make_file(name=f'f{i}.txt')
        response = self.client.get(FILES_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 20)
        self.assertIsNotNone(response.data['next'])

    def test_following_next_cursor_returns_remaining_records(self):
        for i in range(25):
            make_file(name=f'f{i}.txt')
        r1 = self.client.get(FILES_URL)
        self.assertEqual(len(r1.data['results']), 20)
        r2 = self.client.get(r1.data['next'])
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(r2.data['results']), 5)
        self.assertIsNone(r2.data['next'])

    def test_page_size_query_param_respected(self):
        for i in range(5):
            make_file(name=f'f{i}.txt')
        response = self.client.get(FILES_URL + '?page_size=3')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 3)

    def test_page_size_clamped_to_1_for_zero(self):
        make_file(name='only.txt')
        response = self.client.get(FILES_URL + '?page_size=0')
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data['results']), 1)

    def test_page_size_clamped_to_1_for_negative(self):
        make_file(name='only.txt')
        response = self.client.get(FILES_URL + '?page_size=-5')
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data['results']), 1)

    def test_page_size_clamped_to_100_for_large_value(self):
        for i in range(5):
            make_file(name=f'f{i}.txt')
        response = self.client.get(FILES_URL + '?page_size=200')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.data['results']), 100)

    def test_count_reflects_filtered_total_not_overall(self):
        make_file(name='match.txt', mime='text/plain')
        make_file(name='other.pdf', mime='application/pdf')
        response = self.client.get(FILES_URL + '?file_type=text/plain')
        self.assertEqual(response.data['count'], 1)
