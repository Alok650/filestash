from .helpers import APITestCase, make_file

FILES_URL = '/api/files/'

VALID_ORDERING_FIELDS = ('original_filename', 'size', 'uploaded_at')


class OrderingTests(APITestCase):
    """?ordering= sorts by valid fields; invalid fields return 400."""

    def setUp(self):
        make_file(name='b.txt', size=200)
        make_file(name='a.txt', size=100)
        make_file(name='c.txt', size=300)

    def test_ordering_by_size_ascending(self):
        response = self.client.get(FILES_URL + '?ordering=size')
        sizes = [f['size'] for f in response.data['results']]
        self.assertEqual(sizes, sorted(sizes))

    def test_ordering_by_size_descending(self):
        response = self.client.get(FILES_URL + '?ordering=-size')
        sizes = [f['size'] for f in response.data['results']]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_ordering_by_original_filename_ascending(self):
        response = self.client.get(FILES_URL + '?ordering=original_filename')
        names = [f['original_filename'] for f in response.data['results']]
        self.assertEqual(names, sorted(names))

    def test_ordering_by_original_filename_descending(self):
        response = self.client.get(FILES_URL + '?ordering=-original_filename')
        names = [f['original_filename'] for f in response.data['results']]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_ordering_by_uploaded_at_returns_200(self):
        response = self.client.get(FILES_URL + '?ordering=uploaded_at')
        self.assertEqual(response.status_code, 200)

    def test_invalid_ordering_field_returns_400(self):
        response = self.client.get(FILES_URL + '?ordering=invalid_field')
        self.assertEqual(response.status_code, 400)

    def test_invalid_ordering_error_has_errors_key(self):
        response = self.client.get(FILES_URL + '?ordering=invalid_field')
        self.assertIn('errors', response.data)
        self.assertIn('ordering', response.data['errors'])

    def test_invalid_ordering_error_names_the_bad_field(self):
        response = self.client.get(FILES_URL + '?ordering=bad_field')
        error_msg = response.data['errors']['ordering'][0]
        self.assertIn('bad_field', error_msg)

    def test_invalid_ordering_error_lists_all_valid_fields(self):
        response = self.client.get(FILES_URL + '?ordering=bad_field')
        error_msg = response.data['errors']['ordering'][0]
        for field in VALID_ORDERING_FIELDS:
            self.assertIn(field, error_msg)


class ComposabilityTests(APITestCase):
    """Multiple filters, ordering, and pagination compose correctly."""

    def setUp(self):
        make_file(name='report-jan.pdf', mime='application/pdf', size=100)
        make_file(name='report-feb.pdf', mime='application/pdf', size=200)
        make_file(name='report-mar.png', mime='image/png', size=150)
        make_file(name='invoice.pdf', mime='application/pdf', size=300)

    def test_search_and_file_type_filter(self):
        response = self.client.get(FILES_URL + '?search=report&file_type=application/pdf')
        self.assertEqual(response.data['count'], 2)
        for f in response.data['results']:
            self.assertIn('report', f['original_filename'])
            self.assertEqual(f['file_type'], 'application/pdf')

    def test_search_and_ordering(self):
        response = self.client.get(FILES_URL + '?search=report&ordering=size')
        self.assertEqual(response.data['count'], 3)
        sizes = [f['size'] for f in response.data['results']]
        self.assertEqual(sizes, sorted(sizes))

    def test_file_type_and_page_size(self):
        response = self.client.get(FILES_URL + '?file_type=application/pdf&page_size=2')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.data['results']), 2)

    def test_search_file_type_ordering_and_page_size_combined(self):
        response = self.client.get(
            FILES_URL + '?search=report&file_type=application/pdf&ordering=size&page_size=1'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # page_size=1 + ascending size → smallest matching record first
        self.assertEqual(response.data['results'][0]['size'], 100)

    def test_empty_result_with_composed_filters(self):
        response = self.client.get(FILES_URL + '?search=invoice&file_type=image/png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])
