import datetime

from django.test import TestCase

from files import repository
from files.models import File

from .helpers import VALID_MIME, APITestCase, make_file, make_uploaded_file

FILES_URL = '/api/files/'


class SearchTests(APITestCase):
    """?search= performs case-insensitive substring match on original_filename."""

    def setUp(self):
        make_file(name='report-q1.pdf', mime='application/pdf')
        make_file(name='report-q2.pdf', mime='application/pdf')
        make_file(name='invoice.pdf', mime='application/pdf')

    def test_search_returns_matching_files(self):
        response = self.client.get(FILES_URL + '?search=report')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        names = {f['original_filename'] for f in response.data['results']}
        self.assertEqual(names, {'report-q1.pdf', 'report-q2.pdf'})

    def test_search_is_case_insensitive(self):
        response = self.client.get(FILES_URL + '?search=REPORT')
        self.assertEqual(response.data['count'], 2)

    def test_search_no_match_returns_empty_results(self):
        response = self.client.get(FILES_URL + '?search=nonexistent')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

    def test_search_empty_string_returns_all(self):
        response = self.client.get(FILES_URL + '?search=')
        self.assertEqual(response.data['count'], 3)


class FileTypeFilterTests(APITestCase):
    """?file_type= supports exact match and prefix (trailing '/') match."""

    def setUp(self):
        make_file(name='photo.png', mime='image/png')
        make_file(name='photo.jpg', mime='image/jpeg')
        make_file(name='doc.pdf', mime='application/pdf')

    def test_exact_type_match(self):
        response = self.client.get(FILES_URL + '?file_type=image/png')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['file_type'], 'image/png')

    def test_exact_type_excludes_other_subtypes(self):
        response = self.client.get(FILES_URL + '?file_type=image/png')
        types = [f['file_type'] for f in response.data['results']]
        self.assertNotIn('image/jpeg', types)

    def test_prefix_type_match_returns_all_subtypes(self):
        response = self.client.get(FILES_URL + '?file_type=image/')
        self.assertEqual(response.data['count'], 2)
        types = {f['file_type'] for f in response.data['results']}
        self.assertEqual(types, {'image/png', 'image/jpeg'})

    def test_prefix_excludes_other_top_level_types(self):
        response = self.client.get(FILES_URL + '?file_type=image/')
        types = [f['file_type'] for f in response.data['results']]
        self.assertNotIn('application/pdf', types)

    def test_no_match_returns_empty(self):
        response = self.client.get(FILES_URL + '?file_type=video/mp4')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)


class DateRangeFilterTests(APITestCase):
    """?uploaded_after= and ?uploaded_before= filter on uploaded_at."""

    def setUp(self):
        self.f_old = make_file(name='old.txt')
        self.f_mid = make_file(name='mid.txt')
        self.f_new = make_file(name='new.txt')
        # Override auto_now_add timestamps to known fixed values.
        old_ts = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        mid_ts = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
        new_ts = datetime.datetime(2024, 12, 1, tzinfo=datetime.timezone.utc)
        File.objects.filter(pk=self.f_old.pk).update(uploaded_at=old_ts)
        File.objects.filter(pk=self.f_mid.pk).update(uploaded_at=mid_ts)
        File.objects.filter(pk=self.f_new.pk).update(uploaded_at=new_ts)

    def test_uploaded_after_is_inclusive(self):
        response = self.client.get(FILES_URL + '?uploaded_after=2024-06-01T00:00:00Z')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_uploaded_before_is_inclusive(self):
        response = self.client.get(FILES_URL + '?uploaded_before=2024-06-01T00:00:00Z')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_date_range_combined_narrows_results(self):
        response = self.client.get(
            FILES_URL
            + '?uploaded_after=2024-03-01T00:00:00Z'
            + '&uploaded_before=2024-09-01T00:00:00Z'
        )
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['original_filename'], 'mid.txt')

    def test_invalid_uploaded_after_returns_400(self):
        response = self.client.get(FILES_URL + '?uploaded_after=not-a-date')
        self.assertEqual(response.status_code, 400)
        self.assertIn('errors', response.data)
        self.assertIn('uploaded_after', response.data['errors'])

    def test_invalid_uploaded_before_returns_400(self):
        response = self.client.get(FILES_URL + '?uploaded_before=not-a-date')
        self.assertEqual(response.status_code, 400)
        self.assertIn('errors', response.data)
        self.assertIn('uploaded_before', response.data['errors'])
