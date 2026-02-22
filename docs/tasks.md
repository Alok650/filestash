# Tasks: File Vault Feature Implementation

> Generated: 2026-02-21
> Source Spec: SPEC.md -- File Vault v1.0 (Deduplication, Search & Filtering, API Keys & Rate Limiting)
> Project Context: CLAUDE.md

## Overview

This task breakdown covers three major features for the File Vault Django REST Framework backend: (1) SHA-256 content-hash-based file deduplication with reference-counted deletion, (2) search, filtering, and cursor-based pagination on the file list endpoint, and (3) API-key-based authentication with per-key rate limiting and storage quotas. Implementation proceeds in four phases aligned with the spec's migration and rollout strategy, each building on the previous phase's data model and logic.

## Task Breakdown

### Phase 1: Data Model Migrations

This phase adds new fields and models without changing any endpoint behavior. All existing API responses remain identical after deployment.

---

#### Task 1.1: Add `sha256_hash` field to File model

**Priority**: High
**Estimated Effort**: 30 minutes
**Prerequisites**: None
**Owner**: Backend

**Description**:
Add a nullable `sha256_hash` CharField to the `File` model in `backend/files/models.py`. Generate the schema migration.

The field definition:
```python
sha256_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
```

After modifying the model, run `python manage.py makemigrations files` from `backend/` to generate the migration file (should be `0002_file_sha256_hash.py`).

**Acceptance Criteria**:
- [ ] `sha256_hash` field exists on the `File` model with `max_length=64`, `null=True`, `blank=True`, `db_index=True`
- [ ] Migration file `backend/files/migrations/0002_file_sha256_hash.py` is generated and applies cleanly via `python manage.py migrate`
- [ ] Existing `File` records have `sha256_hash=NULL` after migration
- [ ] No endpoint behavior changes

**Key Files**:
- `backend/files/models.py` -- add field
- `backend/files/migrations/0002_file_sha256_hash.py` -- generated migration

---

#### Task 1.2: Backfill `sha256_hash` for existing files (data migration)

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 1.1
**Owner**: Backend

**Description**:
Create a data migration that reads every existing `File` record, opens the physical file from `MEDIA_ROOT / file.name`, computes its SHA-256 hash by reading in 8 KB chunks, and stores the hex digest in `sha256_hash`.

Create the migration manually: `python manage.py makemigrations files --empty --name backfill_sha256_hash`. In the migration's `RunPython` operation:

1. Iterate over all `File` records.
2. For each record, resolve the full path: `os.path.join(settings.MEDIA_ROOT, file_record.file.name)`.
3. If the physical file exists, compute SHA-256 in 8 KB chunks using `hashlib.sha256()` and save the hex digest.
4. If the physical file is missing on disk, set `sha256_hash = None` and log a warning using Python's `logging` module: `"WARNING: File missing on disk for File id={id}, path={path}. sha256_hash set to NULL."`.
5. Call `file_record.save(update_fields=['sha256_hash'])` for each record.

Include a no-op reverse migration (`migrations.RunPython.noop`).

**Acceptance Criteria**:
- [ ] Data migration `backend/files/migrations/0003_backfill_sha256_hash.py` exists and applies cleanly
- [ ] All existing files with physical content on disk have their `sha256_hash` populated with a 64-character hex string
- [ ] Files missing from disk have `sha256_hash=NULL` and a warning is logged
- [ ] Migration is reversible (reverse is no-op)
- [ ] Hash computation uses 8 KB chunk streaming, not `file.read()`

**Key Files**:
- `backend/files/migrations/0003_backfill_sha256_hash.py` -- new data migration

**Notes**:
Use `from django.conf import settings` inside the migration function to access `MEDIA_ROOT`. Import `hashlib` and `os` at module level. The `apps.get_model('files', 'File')` pattern must be used to get the historical model.

---

#### Task 1.3: Create `ApiKey` model

**Priority**: High
**Estimated Effort**: 1 hour
**Prerequisites**: Task 1.2 (migration ordering)
**Owner**: Backend

**Description**:
Add a new `ApiKey` model to `backend/files/models.py` with the following fields:

| Field                | Type              | Notes                                          |
|----------------------|-------------------|-------------------------------------------------|
| `id`                 | UUIDField (PK)    | `default=uuid.uuid4, editable=False`            |
| `key`                | CharField(64)     | Unique, `db_index=True`                         |
| `label`              | CharField(100)    | Human-readable name                             |
| `is_active`          | BooleanField      | `default=True`                                  |
| `storage_quota_bytes`| BigIntegerField   | `default=1073741824` (1 GB)                     |
| `created_at`         | DateTimeField     | `auto_now_add=True`                             |

Add a `__str__` method that returns the label. Do NOT add a custom `save()` that auto-generates the key -- key generation will be handled in the view/serializer layer (Task 4.2).

Generate the migration: `python manage.py makemigrations files`.

**Acceptance Criteria**:
- [ ] `ApiKey` model exists in `backend/files/models.py` with all specified fields
- [ ] UUID primary key, unique indexed `key` field, default quota of 1 GB
- [ ] Migration `backend/files/migrations/0004_apikey.py` applies cleanly
- [ ] `__str__` returns the label
- [ ] No endpoint behavior changes

**Key Files**:
- `backend/files/models.py` -- add `ApiKey` model
- `backend/files/migrations/0004_apikey.py` -- generated migration

---

#### Task 1.4: Add `api_key` ForeignKey to File model

**Priority**: High
**Estimated Effort**: 30 minutes
**Prerequisites**: Task 1.3
**Owner**: Backend

**Description**:
Add a nullable ForeignKey from `File` to `ApiKey` in `backend/files/models.py`:

```python
api_key = models.ForeignKey(
    'ApiKey',
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name='files'
)
```

Generate the migration: `python manage.py makemigrations files`.

**Acceptance Criteria**:
- [ ] `api_key` ForeignKey exists on `File` model with `null=True`, `blank=True`, `on_delete=models.SET_NULL`, `related_name='files'`
- [ ] Migration `backend/files/migrations/0005_file_api_key.py` applies cleanly
- [ ] All existing `File` records have `api_key=NULL` after migration
- [ ] No endpoint behavior changes

**Key Files**:
- `backend/files/models.py` -- add field
- `backend/files/migrations/0005_file_api_key.py` -- generated migration

---

#### Task 1.5: Write tests for Phase 1 migrations and models

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 1.4
**Owner**: Backend

**Description**:
Create `backend/files/tests.py` (or `backend/files/tests/` package) with tests covering:

1. **`File` model field tests**: Verify `sha256_hash` field exists, accepts a 64-char hex string, allows `NULL`, and is indexed.
2. **`ApiKey` model tests**: Create an `ApiKey` instance, verify default `is_active=True`, default `storage_quota_bytes=1073741824`, `key` field uniqueness constraint, `__str__` returns label.
3. **`File.api_key` relationship**: Create a `File` with an `ApiKey` FK, verify `related_name='files'` works, verify `on_delete=SET_NULL` by deleting the `ApiKey` and confirming the `File` still exists with `api_key=None`.
4. **Backfill migration test**: Create a `File` with a real file on disk, run the backfill forward function directly, and verify the `sha256_hash` is correctly computed. Also test the missing-file warning path.

Run: `python manage.py test files.tests` from `backend/`.

**Acceptance Criteria**:
- [ ] All tests pass via `python manage.py test files.tests`
- [ ] Tests cover `sha256_hash` field properties
- [ ] Tests cover `ApiKey` model creation with defaults
- [ ] Tests cover `ApiKey.key` uniqueness constraint
- [ ] Tests cover `File.api_key` FK relationship and `SET_NULL` behavior
- [ ] Tests cover the SHA-256 backfill logic for both existing and missing files

**Key Files**:
- `backend/files/tests.py` -- new test file

---

### Phase 2: Search & Filtering

This phase adds query parameters, filtering, ordering, and cursor-based pagination to `GET /api/files/`. The response shape changes from a bare list to a paginated envelope.

---

#### Task 2.1: Add `django-filter` dependency

**Priority**: High
**Estimated Effort**: 15 minutes
**Prerequisites**: None
**Owner**: Backend

**Description**:
Add `django-filter>=23.0` to `backend/requirements.txt`. Add `'django_filters'` to `INSTALLED_APPS` in `backend/core/settings.py`. Install via `pip install -r requirements.txt`.

**Acceptance Criteria**:
- [ ] `django-filter>=23.0` is in `backend/requirements.txt`
- [ ] `'django_filters'` is in `INSTALLED_APPS` in `backend/core/settings.py`
- [ ] `pip install -r requirements.txt` succeeds
- [ ] `python manage.py check` passes

**Key Files**:
- `backend/requirements.txt` -- add dependency
- `backend/core/settings.py` -- add to `INSTALLED_APPS`

**Notes**:
The pip package is `django-filter` but the Django app name is `django_filters` (with an underscore and plural).

---

#### Task 2.2: Implement custom cursor pagination class

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 2.1
**Owner**: Backend

**Description**:
Create `backend/files/pagination.py` with a `FileVaultCursorPagination` class extending `rest_framework.pagination.CursorPagination`.

Configuration:
- `page_size = 20`
- `max_page_size = 100`
- `page_size_query_param = 'page_size'`
- `ordering = '-uploaded_at'` (default cursor ordering)

Override `paginate_queryset` to capture the queryset, then override `get_paginated_response` and `get_paginated_response_schema` to include a `count` field. The `count` is computed by calling `.count()` on the full filtered queryset (before slicing).

The response envelope shape:
```json
{
  "count": <int>,
  "next": <url|null>,
  "previous": <url|null>,
  "results": [...]
}
```

Page size clamping: values < 1 should be clamped to 1, values > 100 clamped to 100. Override `get_page_size()` to implement clamping instead of raising errors.

**Acceptance Criteria**:
- [ ] `FileVaultCursorPagination` class exists in `backend/files/pagination.py`
- [ ] Default page size is 20, max is 100, query param is `page_size`
- [ ] Response includes `count`, `next`, `previous`, and `results` keys
- [ ] `count` reflects total matching records (not just current page)
- [ ] `page_size` values outside 1-100 are clamped, not rejected
- [ ] Default ordering is `-uploaded_at`

**Key Files**:
- `backend/files/pagination.py` -- new file

**Notes**:
DRF's CursorPagination requires deterministic ordering. The `ordering` attribute on the pagination class sets the fallback. Actual ordering may be overridden by the `OrderingFilter`, but a tiebreaker (`id`) will be added in the view (Task 2.4).

---

#### Task 2.3: Implement FileFilter FilterSet

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 2.1
**Owner**: Backend

**Description**:
Create `backend/files/filters.py` with a `FileFilter` class extending `django_filters.FilterSet`.

Implement the following filters:

1. **`file_type`**: Custom `CharFilter` with `method='filter_file_type'`. If the value ends with `/`, use `file_type__istartswith` (prefix match). Otherwise, use `file_type__exact` (exact match).
2. **`uploaded_after`**: `IsoDateTimeFilter` on `uploaded_at` with `lookup_expr='gte'`.
3. **`uploaded_before`**: `IsoDateTimeFilter` on `uploaded_at` with `lookup_expr='lte'`.

The `search` parameter is handled by DRF's built-in `SearchFilter` (not part of this FilterSet). Ordering is handled by DRF's `OrderingFilter`.

```python
class Meta:
    model = File
    fields = []  # All filters are declared explicitly
```

Add validation: if `uploaded_after` or `uploaded_before` receive unparseable datetime strings, return a 400 error with the format specified in the spec (`{"errors": {"uploaded_after": [...]}}`).

**Acceptance Criteria**:
- [ ] `FileFilter` class exists in `backend/files/filters.py`
- [ ] `file_type` filter supports exact match (`image/png`) and prefix match (`image/`)
- [ ] `uploaded_after` filter applies `gte` on `uploaded_at`
- [ ] `uploaded_before` filter applies `lte` on `uploaded_at`
- [ ] Invalid datetime values return HTTP 400 with structured error response
- [ ] Empty filter values are treated as "no filter"

**Key Files**:
- `backend/files/filters.py` -- new file

---

#### Task 2.4: Update FileViewSet for search, filtering, ordering, and pagination

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Tasks 2.2, 2.3
**Owner**: Backend

**Description**:
Modify `backend/files/views.py` to add filter backends, search fields, and ordering fields to `FileViewSet`.

Add to `FileViewSet`:
```python
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .filters import FileFilter

filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
filterset_class = FileFilter
search_fields = ['original_filename']
ordering_fields = ['original_filename', 'size', 'uploaded_at']
ordering = ['-uploaded_at']
```

Add ordering validation: override `list()` or use a custom `OrderingFilter` subclass that returns HTTP 400 with the spec's error format when an invalid field name is passed in `ordering`. The error message must list valid fields: `"Invalid ordering field: '<field>'. Valid fields: original_filename, size, uploaded_at."`.

Ensure ordering stability for cursor pagination: if the resolved ordering does not include `id`, append `id` as a tiebreaker. This can be done by overriding `filter_queryset` or the ordering filter.

**Acceptance Criteria**:
- [ ] `GET /api/files/` supports `search`, `file_type`, `uploaded_after`, `uploaded_before`, `ordering`, and `page_size` query parameters
- [ ] `search` performs case-insensitive substring match on `original_filename`
- [ ] Invalid `ordering` field names return HTTP 400 with structured error listing valid fields
- [ ] Ordering includes `id` as a tiebreaker when not explicitly provided
- [ ] All filters compose correctly (can use search + file_type + date range + ordering simultaneously)
- [ ] Response uses paginated envelope with `count`, `next`, `previous`, `results`

**Key Files**:
- `backend/files/views.py` -- modify `FileViewSet`

---

#### Task 2.5: Update DRF settings for pagination and filter backends

**Priority**: High
**Estimated Effort**: 15 minutes
**Prerequisites**: Task 2.2
**Owner**: Backend

**Description**:
Update the `REST_FRAMEWORK` dict in `backend/core/settings.py` to add:

```python
'DEFAULT_PAGINATION_CLASS': 'files.pagination.FileVaultCursorPagination',
'PAGE_SIZE': 20,
```

Do NOT add `DEFAULT_FILTER_BACKENDS` globally -- keep the filter backends on the viewset level (Task 2.4) to avoid affecting future viewsets that may not need them.

**Acceptance Criteria**:
- [ ] `DEFAULT_PAGINATION_CLASS` is set to `files.pagination.FileVaultCursorPagination` in settings
- [ ] `PAGE_SIZE` is set to `20` in settings
- [ ] Pagination is active on `GET /api/files/`

**Key Files**:
- `backend/core/settings.py` -- update `REST_FRAMEWORK`

---

#### Task 2.6: Add `sha256_hash` to FileSerializer as read-only field

**Priority**: Medium
**Estimated Effort**: 15 minutes
**Prerequisites**: Task 1.1
**Owner**: Backend

**Description**:
Update `backend/files/serializers.py` to add `sha256_hash` to the `FileSerializer` fields list and to the `read_only_fields` tuple.

```python
fields = ['id', 'file', 'original_filename', 'file_type', 'size', 'uploaded_at', 'sha256_hash']
read_only_fields = ['id', 'uploaded_at', 'sha256_hash']
```

**Acceptance Criteria**:
- [ ] `sha256_hash` appears in API responses for `GET /api/files/` and `GET /api/files/{id}/`
- [ ] `sha256_hash` cannot be set or modified via the API (read-only)
- [ ] Existing records show `sha256_hash: null` if not yet backfilled

**Key Files**:
- `backend/files/serializers.py` -- modify `FileSerializer`

---

#### Task 2.7: Write tests for search, filtering, ordering, and pagination

**Priority**: High
**Estimated Effort**: 2-3 hours
**Prerequisites**: Tasks 2.4, 2.5, 2.6
**Owner**: Backend

**Description**:
Add tests to `backend/files/tests.py` covering:

1. **Pagination**: Verify response envelope has `count`, `next`, `previous`, `results`. Create 25 files, request with default `page_size=20`, verify 20 results and `next` is not null. Follow `next` link, verify remaining 5 results.
2. **Page size clamping**: Request with `page_size=0`, verify clamped to 1. Request with `page_size=200`, verify clamped to 100.
3. **Search**: Create files with names `report-q1.pdf`, `report-q2.pdf`, `invoice.pdf`. Search `?search=report`, verify only the two reports are returned. Search `?search=REPORT`, verify case-insensitive.
4. **File type filter (exact)**: `?file_type=image/png` returns only PNGs.
5. **File type filter (prefix)**: `?file_type=image/` returns both `image/png` and `image/jpeg` files.
6. **Date range**: Create files at known timestamps using `uploaded_at` override. Filter with `uploaded_after` and `uploaded_before`, verify correct results.
7. **Ordering**: `?ordering=size` returns ascending by size. `?ordering=-size` returns descending. `?ordering=original_filename` returns alphabetical.
8. **Invalid ordering**: `?ordering=invalid_field` returns HTTP 400 with error message listing valid fields.
9. **Composability**: Combine search + file_type + date range + ordering + page_size in one request, verify correct filtering.
10. **Empty results**: Filter that matches nothing returns `200` with `count: 0, results: []`.
11. **`sha256_hash` in response**: Verify the field appears in list and detail responses.

**Acceptance Criteria**:
- [ ] All tests pass via `python manage.py test files.tests`
- [ ] Tests cover all filter parameters individually and in combination
- [ ] Tests cover pagination envelope structure and cursor navigation
- [ ] Tests cover page_size clamping behavior
- [ ] Tests cover error responses for invalid ordering fields
- [ ] Tests cover empty result sets

**Key Files**:
- `backend/files/tests.py` -- add test cases

---

### Phase 3: File Deduplication

This phase implements SHA-256 hash computation on upload, duplicate detection, disk-write skipping, the `/duplicates/` endpoint, and reference-counted deletion.

---

#### Task 3.1: Implement SHA-256 hash computation utility

**Priority**: High
**Estimated Effort**: 30 minutes
**Prerequisites**: Task 1.1
**Owner**: Backend

**Description**:
Create a utility function in `backend/files/utils.py` (new file):

```python
def compute_sha256(file_obj):
    """Compute SHA-256 hash of a Django UploadedFile using 8KB chunks.
    Returns the hex digest string (64 chars).
    Resets file pointer to 0 after reading.
    """
```

The function must:
1. Use `hashlib.sha256()`.
2. Read the file using `file_obj.chunks(chunk_size=8192)`.
3. Call `file_obj.seek(0)` after reading to reset the file pointer (so the file can still be saved to disk afterward).
4. Return the hex digest.

**Acceptance Criteria**:
- [ ] `compute_sha256()` function exists in `backend/files/utils.py`
- [ ] Uses 8 KB chunk streaming via `chunks()`
- [ ] Resets file pointer to 0 after computation
- [ ] Returns a 64-character lowercase hex string
- [ ] Produces correct SHA-256 for known test inputs

**Key Files**:
- `backend/files/utils.py` -- new file

---

#### Task 3.2: Add `deduplicated` field to FileSerializer

**Priority**: High
**Estimated Effort**: 30 minutes
**Prerequisites**: Task 2.6
**Owner**: Backend

**Description**:
Add a `SerializerMethodField` named `deduplicated` to `FileSerializer` in `backend/files/serializers.py`.

The method `get_deduplicated` returns `self.context.get('deduplicated', False)`. The view will set this context value to `True` when a duplicate disk-reuse occurs during upload.

Add `deduplicated` to the `fields` list. It should NOT be in `read_only_fields` (it is already read-only by virtue of being a `SerializerMethodField`).

**Acceptance Criteria**:
- [ ] `deduplicated` appears in all File API responses
- [ ] Defaults to `false` when no context is set
- [ ] Returns `true` when `context['deduplicated']` is `True`
- [ ] Field is not writable via the API

**Key Files**:
- `backend/files/serializers.py` -- modify `FileSerializer`

---

#### Task 3.3: Implement deduplication logic in FileViewSet.create()

**Priority**: High
**Estimated Effort**: 2-3 hours
**Prerequisites**: Tasks 3.1, 3.2
**Owner**: Backend

**Description**:
Modify the `create()` method in `backend/files/views.py` to implement deduplication:

1. Extract the uploaded file object from `request.FILES.get('file')`.
2. Call `compute_sha256(file_obj)` to get the hash.
3. Query `File.objects.filter(sha256_hash=computed_hash).first()` to check for an existing file on disk.
4. **If a duplicate exists**:
   - Do NOT save the file to disk. Instead, create the `File` record manually using `File.objects.create()` with the `file` field set to the existing record's `file.name` (the relative path). This reuses the physical file.
   - Set `deduplicated = True` in the serializer context.
5. **If no duplicate exists**:
   - Save the file normally (let Django's `FileField` handle the disk write).
   - Set `deduplicated = False` in the serializer context.
6. Always set `sha256_hash = computed_hash` on the new record.
7. Return `201 Created` with the serialized new record.

Important: When reusing an existing file path, you need to set the `File.file.name` attribute directly rather than assigning a file object, to prevent Django from writing to disk. Use `File(file=existing_record.file.name, ...)` in the constructor or `instance.file.name = existing_path` before saving.

**Acceptance Criteria**:
- [ ] First upload of new content writes to disk, `deduplicated: false` in response
- [ ] Second upload of identical content does NOT write a new file to disk, `deduplicated: true` in response
- [ ] Both uploads return `201 Created`
- [ ] New DB record is always created with unique `id`, correct `original_filename`, and the requesting key's `api_key`
- [ ] `sha256_hash` is populated on all new uploads
- [ ] Deduplicated uploads reuse the physical file path from the first upload
- [ ] Cross-key deduplication works (key A uploads, key B uploads same content -- one file on disk, two DB records)

**Key Files**:
- `backend/files/views.py` -- modify `FileViewSet.create()`

**Notes**:
Be careful with the FileField. Assigning a string path (not a File object) to a FileField and calling `save()` will store the path in the DB without triggering a new disk write. Test this behavior explicitly.

---

#### Task 3.4: Implement reference-counted deletion in FileViewSet.perform_destroy()

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 3.3
**Owner**: Backend

**Description**:
Override `perform_destroy()` in `FileViewSet` in `backend/files/views.py`:

1. Before deleting, check if any OTHER `File` records (across ALL API keys) share the same `sha256_hash`:
   ```python
   has_other_refs = File.objects.filter(sha256_hash=instance.sha256_hash).exclude(id=instance.id).exists()
   ```
2. If `has_other_refs` is `True`: delete only the DB record. Do NOT delete the physical file.
3. If `has_other_refs` is `False`: delete both the DB record AND the physical file from disk.
4. For the DB record deletion: call `instance.delete()`.
5. For the physical file deletion: call `instance.file.delete(save=False)` BEFORE `instance.delete()`, or use `os.remove()` on the file path after deletion.

Handle the edge case where `sha256_hash` is `NULL` (legacy files before backfill). If `sha256_hash` is `NULL`, always delete the physical file (no deduplication possible).

**Acceptance Criteria**:
- [ ] Deleting a file with no other references removes both DB record and physical file
- [ ] Deleting a file with other references (same hash) removes only the DB record, leaves physical file
- [ ] Reference counting is global (not scoped to API key)
- [ ] Files with `sha256_hash=NULL` always have their physical file deleted
- [ ] After deletion, the file path on disk is correct (file exists or is removed as expected)

**Key Files**:
- `backend/files/views.py` -- add `perform_destroy()` override

---

#### Task 3.5: Implement `/duplicates/` detail route

**Priority**: High
**Estimated Effort**: 1 hour
**Prerequisites**: Task 3.3
**Owner**: Backend

**Description**:
Add a `@action` detail route on `FileViewSet` in `backend/files/views.py`:

```python
from rest_framework.decorators import action

@action(detail=True, methods=['get'], url_path='duplicates')
def duplicates(self, request, pk=None):
    ...
```

Logic:
1. Get the file by PK. If it does not exist or does not belong to the requesting API key, return `404`.
2. Query all `File` records owned by the same API key with the same `sha256_hash`, excluding the file itself.
3. Serialize and return the list. Return `[]` if no duplicates found.

This route is auto-registered by `DefaultRouter` at `/api/files/{id}/duplicates/`.

**Acceptance Criteria**:
- [ ] `GET /api/files/{id}/duplicates/` returns duplicate files owned by the same API key
- [ ] The file itself is excluded from the results
- [ ] Returns `404` if the file does not exist
- [ ] Returns `404` if the file belongs to a different API key (key-scoped visibility)
- [ ] Returns `[]` (empty list) with `200` status if no duplicates exist
- [ ] Does not expose files owned by other API keys

**Key Files**:
- `backend/files/views.py` -- add `duplicates` action

---

#### Task 3.6: Handle file replacement on PUT/PATCH with deduplication

**Priority**: Medium
**Estimated Effort**: 1-2 hours
**Prerequisites**: Tasks 3.3, 3.4
**Owner**: Backend

**Description**:
Override `update()` (or `perform_update()`) in `FileViewSet` to handle the case where a file's content is replaced via `PUT` or `PATCH`.

Per the spec's open question (item 4), the recommended approach is to **disallow file content replacement** -- make `file` and `sha256_hash` read-only on update, allowing only `original_filename` to be edited.

Implementation: Add `file` to `read_only_fields` in the serializer for update operations. This can be done by:
- Creating an `UpdateFileSerializer` that extends `FileSerializer` with `file` in `read_only_fields`, OR
- Overriding `get_serializer_class()` to return a different serializer for PUT/PATCH, OR
- Overriding `update()` in the view to strip the `file` field from incoming data.

Choose the simplest approach: add `file` to `read_only_fields` and override `update()` to ignore any `file` field in the request data.

**Acceptance Criteria**:
- [ ] `PUT /api/files/{id}/` with a new file in the request ignores the file and only updates allowed fields
- [ ] `PATCH /api/files/{id}/` with `original_filename` works correctly
- [ ] `sha256_hash` cannot be modified via the API
- [ ] `file` content cannot be replaced after initial upload

**Key Files**:
- `backend/files/views.py` -- modify update behavior
- `backend/files/serializers.py` -- potentially add update serializer

**Notes**:
The spec's Open Question 4 recommends disallowing file replacement. Implement this recommendation. If stakeholders later decide to allow replacement, it would require reference count decrement on the old hash and dedup check on the new content.

---

#### Task 3.7: Write tests for deduplication

**Priority**: High
**Estimated Effort**: 2-3 hours
**Prerequisites**: Tasks 3.3, 3.4, 3.5, 3.6
**Owner**: Backend

**Description**:
Add tests to `backend/files/tests.py` covering:

1. **First upload**: Upload a file, verify `deduplicated: false`, file exists on disk, `sha256_hash` is populated.
2. **Duplicate upload (same key)**: Upload identical content again with the same API key. Verify `deduplicated: true`, `sha256_hash` matches, `original_filename` reflects the new upload's name, new `id` is assigned, only one physical file on disk.
3. **Duplicate upload (different key)**: Upload identical content with a different API key. Verify deduplication occurs, each key has its own record, file path is shared.
4. **`/duplicates/` endpoint**: Upload 3 identical files with the same key, call `/duplicates/` on one, verify the other 2 are returned.
5. **`/duplicates/` cross-key isolation**: Key A and Key B upload identical content. Key A calls `/duplicates/` -- should NOT see Key B's record.
6. **`/duplicates/` for non-existent file**: Returns `404`.
7. **Reference-counted deletion (last reference)**: Upload a file, delete it, verify physical file is removed.
8. **Reference-counted deletion (not last reference)**: Upload identical content twice (same or different key), delete one, verify physical file still exists. Delete the last one, verify physical file is removed.
9. **Empty file deduplication**: Two empty files are treated as duplicates.
10. **SHA-256 computation**: Verify correct hash for known content.
11. **File replacement disallowed**: `PUT/PATCH` with a new file does not change the stored file content.

**Acceptance Criteria**:
- [ ] All tests pass via `python manage.py test files.tests`
- [ ] Tests cover deduplication on upload (same key, cross-key)
- [ ] Tests cover the `deduplicated` flag in responses
- [ ] Tests cover the `/duplicates/` endpoint including key isolation
- [ ] Tests cover reference-counted deletion (last ref vs. not last ref)
- [ ] Tests cover empty file edge case
- [ ] Tests verify file replacement is disallowed on update

**Key Files**:
- `backend/files/tests.py` -- add test cases

---

### Phase 4: API Keys, Rate Limiting, and Quotas

This phase introduces authentication, rate limiting, storage quotas, and key-scoped file visibility. It affects all existing endpoints.

---

#### Task 4.1: Implement ApiKeyAuthentication class

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 1.3
**Owner**: Backend

**Description**:
Create `backend/files/authentication.py` with a custom DRF authentication class:

```python
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings
from .models import ApiKey

class ApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        ...
```

Logic:
1. Read the `Authorization` header.
2. If no header or header does not start with `ApiKey `, return `None` (anonymous -- let the request through).
3. Extract the token after `ApiKey `.
4. First check if the token matches `settings.ADMIN_API_KEY` (env var). If so, return `(AnonymousUser(), 'admin')`. Use a sentinel value or string `'admin'` for `request.auth` to distinguish admin access.
5. Look up `ApiKey.objects.filter(key=token, is_active=True).first()`.
6. If found, return `(AnonymousUser(), api_key_instance)`. This sets `request.auth = api_key_instance`.
7. If not found (token provided but invalid), raise `AuthenticationFailed({'error': 'invalid_api_key'})`.

Add `ADMIN_API_KEY = os.environ.get('ADMIN_API_KEY', '')` to `backend/core/settings.py`.

Register the authentication class in `REST_FRAMEWORK` settings:
```python
'DEFAULT_AUTHENTICATION_CLASSES': [
    'files.authentication.ApiKeyAuthentication',
],
```

**Acceptance Criteria**:
- [ ] Requests with `Authorization: ApiKey <valid_token>` set `request.auth` to the `ApiKey` instance
- [ ] Requests with `Authorization: ApiKey <admin_token>` set `request.auth` to `'admin'`
- [ ] Requests with no `Authorization` header proceed as anonymous (`request.auth = None`)
- [ ] Malformed headers (wrong scheme, missing token) are treated as anonymous
- [ ] Requests with a valid format but unknown/inactive token return `401` with `{"error": "invalid_api_key"}`
- [ ] `ADMIN_API_KEY` setting is read from environment variable

**Key Files**:
- `backend/files/authentication.py` -- new file
- `backend/core/settings.py` -- add `ADMIN_API_KEY` and update `REST_FRAMEWORK`

---

#### Task 4.2: Implement API key management endpoints

**Priority**: High
**Estimated Effort**: 2-3 hours
**Prerequisites**: Task 4.1
**Owner**: Backend

**Description**:
Create a new `ApiKeyViewSet` (or use separate views) in `backend/files/views.py` and register routes in `backend/files/urls.py`.

**Endpoints:**

1. **`POST /api/keys/`** -- Create a new API key. Admin-only.
   - Check `request.auth == 'admin'`. If not, return `403`.
   - If `ADMIN_API_KEY` is not configured (empty), return `503` with `{"error": "admin_key_not_configured"}`.
   - Accept `{"label": "...", "storage_quota_bytes": ...}` (quota optional, default 1 GB).
   - Generate key using `secrets.token_hex(32)`.
   - Return `201` with the full key object INCLUDING the `key` field.

2. **`GET /api/keys/me/`** -- Get current key info + usage.
   - Requires a valid (non-admin) API key. Return `401` for anonymous.
   - Return the key's info (id, label, is_active, storage_quota_bytes, created_at) plus computed `storage_used_bytes`.
   - `storage_used_bytes = File.objects.filter(api_key=request.auth).aggregate(Sum('size'))['size__sum'] or 0`.
   - Do NOT return the `key` field.

3. **`DELETE /api/keys/{id}/`** -- Deactivate a key. Admin-only.
   - Set `is_active = False`. Do NOT delete the record.
   - Return `204 No Content`.
   - If `ADMIN_API_KEY` is not configured, return `503`.

Create an `ApiKeySerializer` in `backend/files/serializers.py` for the response. Consider having a `ApiKeyCreateSerializer` (includes `key` in response) and `ApiKeyDetailSerializer` (excludes `key`).

Register URL routes in `backend/files/urls.py`:
```python
path('keys/', ApiKeyCreateView.as_view(), name='api-key-create'),
path('keys/me/', ApiKeyMeView.as_view(), name='api-key-me'),
path('keys/<uuid:pk>/', ApiKeyDeactivateView.as_view(), name='api-key-deactivate'),
```

**Acceptance Criteria**:
- [ ] `POST /api/keys/` with admin key creates a new API key and returns it with the `key` field visible
- [ ] `POST /api/keys/` without admin key returns `403`
- [ ] `POST /api/keys/` when `ADMIN_API_KEY` is not set returns `503` with `{"error": "admin_key_not_configured"}`
- [ ] `GET /api/keys/me/` with valid API key returns key info with `storage_used_bytes`, without `key` field
- [ ] `GET /api/keys/me/` without API key returns `401`
- [ ] `DELETE /api/keys/{id}/` with admin key deactivates the key (sets `is_active=False`), returns `204`
- [ ] `DELETE /api/keys/{id}/` without admin key returns `403`
- [ ] Key is generated using `secrets.token_hex(32)` (64-char hex string)

**Key Files**:
- `backend/files/views.py` -- add API key views
- `backend/files/serializers.py` -- add API key serializers
- `backend/files/urls.py` -- register key management routes

---

#### Task 4.3: Implement key-scoped file visibility

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Tasks 4.1, 1.4
**Owner**: Backend

**Description**:
Override `get_queryset()` on `FileViewSet` in `backend/files/views.py` to scope file visibility:

```python
def get_queryset(self):
    if self.request.auth == 'admin':
        return File.objects.all()
    elif isinstance(self.request.auth, ApiKey):
        return File.objects.filter(api_key=self.request.auth)
    else:
        # Anonymous
        return File.objects.filter(api_key__isnull=True)
```

This scoping affects `list`, `retrieve`, `update`, `destroy`, and the `duplicates` action. A key can only see, modify, and delete its own files. Attempting to access another key's file returns `404` (not `403`).

**Acceptance Criteria**:
- [ ] Authenticated requests see only files associated with their API key
- [ ] Anonymous requests see only files with `api_key=NULL`
- [ ] Admin key sees all files across all API keys
- [ ] `GET /api/files/{id}/` returns `404` for files belonging to another key
- [ ] `DELETE /api/files/{id}/` returns `404` for files belonging to another key
- [ ] `GET /api/files/{id}/duplicates/` is scoped to the requesting key's files

**Key Files**:
- `backend/files/views.py` -- modify `FileViewSet.get_queryset()`

---

#### Task 4.4: Associate uploaded files with requesting API key

**Priority**: High
**Estimated Effort**: 30 minutes
**Prerequisites**: Tasks 4.1, 1.4
**Owner**: Backend

**Description**:
Modify `FileViewSet.create()` in `backend/files/views.py` to set the `api_key` field on new `File` records:

```python
api_key = request.auth if isinstance(request.auth, ApiKey) else None
```

Pass `api_key` when creating the `File` instance. Ensure the `api_key` field is excluded from the serializer's writable fields (clients cannot set it directly).

**Acceptance Criteria**:
- [ ] Files uploaded with a valid API key have `api_key` set to that key
- [ ] Files uploaded anonymously have `api_key=NULL`
- [ ] Files uploaded with the admin key have `api_key=NULL` (admin does not own files)
- [ ] `api_key` cannot be set or modified by the client via the API

**Key Files**:
- `backend/files/views.py` -- modify `create()`
- `backend/files/serializers.py` -- ensure `api_key` is not writable

---

#### Task 4.5: Implement throttle classes for rate limiting

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 4.1
**Owner**: Backend

**Description**:
Create `backend/files/throttling.py` with two custom throttle classes extending `rest_framework.throttling.SimpleRateThrottle`:

1. **`ApiKeySecondRateThrottle`**:
   - `scope = 'api_key_second'`
   - Override `get_cache_key()`: use the API key value for authenticated requests, client IP for anonymous.
   - Rate: `'10/second'` for authenticated, `'2/second'` for anonymous.

2. **`ApiKeyMinuteRateThrottle`**:
   - `scope = 'api_key_minute'`
   - Same `get_cache_key()` logic.
   - Rate: `'300/minute'` for authenticated, `'30/minute'` for anonymous.

Override `get_rate()` to return different rates based on whether the request is authenticated or anonymous.

Admin key requests should NOT be rate limited. Override `allow_request()` to return `True` immediately if `request.auth == 'admin'`.

Add to `backend/core/settings.py`:

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'rate-limit-cache',
    }
}
```

Register throttle classes in `REST_FRAMEWORK` settings:
```python
'DEFAULT_THROTTLE_CLASSES': [
    'files.throttling.ApiKeySecondRateThrottle',
    'files.throttling.ApiKeyMinuteRateThrottle',
],
```

**Acceptance Criteria**:
- [ ] Authenticated requests are limited to 10/second and 300/minute
- [ ] Anonymous requests are limited to 2/second and 30/minute
- [ ] Admin key requests are not rate limited
- [ ] Throttle key is API key value for authenticated requests, IP for anonymous
- [ ] Rate-limited requests return HTTP `429`
- [ ] `LocMemCache` is configured as the cache backend

**Key Files**:
- `backend/files/throttling.py` -- new file
- `backend/core/settings.py` -- add `CACHES` and throttle classes

---

#### Task 4.6: Implement rate limit response headers and 429 body

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Task 4.5
**Owner**: Backend

**Description**:
Add rate limit headers to every response and format 429 responses per the spec.

**429 response body**: Create a custom exception handler or override the throttle's `throttle_failure` behavior. When throttled, the response should be:
```json
{
  "error": "rate_limit_exceeded",
  "retry_after": 12
}
```
With `Retry-After` header set to the integer seconds.

**Rate limit headers on every response**: Add a custom middleware (`backend/files/middleware.py`) or override `finalize_response()` on the viewsets to inject:
- `X-RateLimit-Limit`: The applicable rate limit
- `X-RateLimit-Remaining`: Requests remaining in the current window
- `X-RateLimit-Reset`: Unix timestamp when the current window resets

Implementation approach: Override `finalize_response` in the viewset or create middleware that inspects `request.META` for throttle state. DRF throttle classes store state in `self.history` and `self.now` after `allow_request()` is called. Access the throttle instances via `request.throttles` or by inspecting the view's `throttle_classes`.

A simpler approach: create a custom DRF exception handler in `backend/files/exception_handlers.py` and set `'EXCEPTION_HANDLER': 'files.exception_handlers.custom_exception_handler'` in `REST_FRAMEWORK` settings to format 429 responses. For the headers, use middleware.

**Acceptance Criteria**:
- [ ] `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers are present on every API response
- [ ] `429` responses include the JSON body with `error` and `retry_after`
- [ ] `429` responses include the `Retry-After` header
- [ ] Header values are numerically correct (remaining decrements, reset is a future timestamp)

**Key Files**:
- `backend/files/middleware.py` -- new file (or modify views)
- `backend/files/exception_handlers.py` -- new file (optional)
- `backend/core/settings.py` -- register middleware and/or exception handler

---

#### Task 4.7: Implement storage quota enforcement on upload

**Priority**: High
**Estimated Effort**: 1-2 hours
**Prerequisites**: Tasks 4.1, 4.4
**Owner**: Backend

**Description**:
Add quota checking to `FileViewSet.create()` in `backend/files/views.py`, BEFORE the file is saved:

1. **Authenticated request**: Compute `used = File.objects.filter(api_key=request.auth).aggregate(Sum('size'))['size__sum'] or 0`. If `used + file_obj.size > request.auth.storage_quota_bytes`, return HTTP `413`:
   ```json
   {
     "error": "storage_quota_exceeded",
     "used_bytes": <used>,
     "quota_bytes": <quota>
   }
   ```

2. **Anonymous request**: Compute `used = File.objects.filter(api_key__isnull=True).aggregate(Sum('size'))['size__sum'] or 0`. Compare against `settings.ANONYMOUS_STORAGE_QUOTA_MB * 1024 * 1024`. If exceeded, return `413`.

3. **Admin key**: No quota check.

4. **Deduplication interaction**: Per the spec's correction in the deduplication feature: "On a deduplicated upload, the size of the file is still charged to the requesting key's storage quota." However, the spec also states in the rate limiting section: "When a duplicate upload is detected, no new File record is created and no disk space is consumed. Therefore, the quota is not charged for a deduplicated upload." These contradict each other. The deduplication spec (Feature 1) says a new record IS always created. Following Feature 1's design (new record always created, quota charged based on `SUM(size)` of all records owned by the key), quota IS charged for deduplication because a new `File` row with `size` is inserted.

Add `ANONYMOUS_STORAGE_QUOTA_MB = int(os.environ.get('ANONYMOUS_STORAGE_QUOTA_MB', '100'))` to `backend/core/settings.py`.

**Acceptance Criteria**:
- [ ] Upload that would exceed authenticated key's `storage_quota_bytes` returns `413` with `used_bytes` and `quota_bytes`
- [ ] Upload that would exceed anonymous quota returns `413`
- [ ] Admin key uploads are not quota-checked
- [ ] Quota is computed dynamically from `SUM(size)` of owned files
- [ ] Deleting files immediately frees quota (no separate counter)
- [ ] `ANONYMOUS_STORAGE_QUOTA_MB` environment variable is read with default of 100

**Key Files**:
- `backend/files/views.py` -- modify `create()`
- `backend/core/settings.py` -- add `ANONYMOUS_STORAGE_QUOTA_MB`

**Notes**:
The quota check must happen BEFORE the file is saved to disk or the DB record is created. Place it early in `create()`, after file validation but before deduplication logic.

---

#### Task 4.8: Write tests for API keys, authentication, and key management

**Priority**: High
**Estimated Effort**: 2-3 hours
**Prerequisites**: Tasks 4.1, 4.2, 4.3, 4.4
**Owner**: Backend

**Description**:
Add tests to `backend/files/tests.py` covering:

1. **Authentication**:
   - Request with valid `Authorization: ApiKey <token>` sets `request.auth` correctly
   - Request with invalid token returns `401` with `{"error": "invalid_api_key"}`
   - Request with no header proceeds as anonymous
   - Request with malformed header (e.g., `Bearer <token>`) proceeds as anonymous
   - Request with inactive key returns `401`
   - Request with admin key authenticates as admin

2. **Key management**:
   - `POST /api/keys/` with admin key creates key, returns full key in response
   - `POST /api/keys/` without admin key returns `403`
   - `POST /api/keys/` when `ADMIN_API_KEY` is unset returns `503`
   - `GET /api/keys/me/` returns key info with `storage_used_bytes`, without `key` field
   - `GET /api/keys/me/` without key returns `401`
   - `DELETE /api/keys/{id}/` with admin key deactivates key
   - Deactivated key can no longer authenticate

3. **File visibility scoping**:
   - Key A uploads a file, Key B cannot see it in `GET /api/files/`
   - Key A uploads a file, Key B gets `404` on `GET /api/files/{id}/`
   - Anonymous uploads are visible only to anonymous requests
   - Admin key sees all files

4. **File ownership**:
   - Files uploaded with a key have `api_key` set
   - Files uploaded anonymously have `api_key=NULL`

**Acceptance Criteria**:
- [ ] All tests pass via `python manage.py test files.tests`
- [ ] Tests cover all authentication scenarios (valid, invalid, anonymous, admin, inactive)
- [ ] Tests cover all key management endpoints
- [ ] Tests cover file visibility scoping per API key
- [ ] Tests cover file ownership assignment

**Key Files**:
- `backend/files/tests.py` -- add test cases

---

#### Task 4.9: Write tests for rate limiting and quotas

**Priority**: High
**Estimated Effort**: 2-3 hours
**Prerequisites**: Tasks 4.5, 4.6, 4.7
**Owner**: Backend

**Description**:
Add tests to `backend/files/tests.py` covering:

1. **Rate limiting**:
   - Anonymous requests exceeding 2/second receive `429`
   - Authenticated requests can make up to 10/second without `429`
   - `429` response body contains `error: "rate_limit_exceeded"` and `retry_after`
   - `Retry-After` header is present on `429` responses
   - Admin key requests are not rate limited
   - Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are present on successful responses

2. **Storage quota**:
   - Upload exceeding key's quota returns `413` with `used_bytes` and `quota_bytes`
   - Upload within quota succeeds
   - Deleting a file frees quota (subsequent upload within freed space succeeds)
   - Anonymous quota enforcement works correctly
   - Admin uploads are not quota-checked
   - Custom `storage_quota_bytes` on key creation is respected

**Acceptance Criteria**:
- [ ] All tests pass via `python manage.py test files.tests`
- [ ] Tests cover rate limiting for anonymous and authenticated requests
- [ ] Tests cover `429` response format (body and headers)
- [ ] Tests cover rate limit headers on all responses
- [ ] Tests cover storage quota enforcement and the `413` response format
- [ ] Tests cover quota reclamation on file deletion
- [ ] Tests cover admin exemption from rate limits and quotas

**Key Files**:
- `backend/files/tests.py` -- add test cases

**Notes**:
Rate limiting tests may need to clear the cache between test cases to ensure isolation. Use `from django.core.cache import cache; cache.clear()` in `setUp()` or between tests. For per-second rate limit tests, you may need to make requests in rapid succession or mock the time.

---

#### Task 4.10: End-to-end integration tests (cross-feature)

**Priority**: Medium
**Estimated Effort**: 2-3 hours
**Prerequisites**: All previous tasks
**Owner**: Backend

**Description**:
Add integration tests to `backend/files/tests.py` that exercise interactions between all three features:

1. **Deduplication + quotas**: Key A uploads a 500 KB file. Key A uploads the same file again (deduplicated). Verify quota reflects both records' sizes (1 MB used). Delete one copy, verify quota drops to 500 KB.
2. **Deduplication + key scoping**: Key A uploads a file. Key B uploads the same content. Key A lists files -- sees only their record. Key B lists files -- sees only their record. Both records point to the same physical file.
3. **Search + key scoping**: Key A and Key B both upload files named "report.pdf". Key A searches `?search=report` -- sees only their file.
4. **Deduplication + deletion + key scoping**: Key A and Key B upload identical content. Key A deletes their record. Physical file persists. Key B deletes their record. Physical file is removed.
5. **Pagination + filtering**: Upload 30 files with varying types and dates. Apply filters that narrow to 15 results, paginate with `page_size=10`, verify first page has 10 results, second page has 5.
6. **Quota exceeded then freed**: Upload files until quota is full. Get `413`. Delete a file. Upload again successfully.

**Acceptance Criteria**:
- [ ] All integration tests pass
- [ ] Tests verify correct interaction between deduplication and quota accounting
- [ ] Tests verify key-scoped visibility with deduplication
- [ ] Tests verify pagination works correctly with filters
- [ ] Tests verify quota reclamation enables subsequent uploads

**Key Files**:
- `backend/files/tests.py` -- add integration test cases

---

## Dependency Graph

```
Phase 1 (Data Model):
  1.1 (sha256_hash field)
    --> 1.2 (backfill migration)
      --> 1.3 (ApiKey model)
        --> 1.4 (api_key FK)
          --> 1.5 (Phase 1 tests)

Phase 2 (Search & Filtering):
  2.1 (django-filter dep)
    --> 2.2 (pagination class)
    --> 2.3 (FilterSet)
    --> 2.5 (DRF settings)
  2.2 + 2.3 --> 2.4 (ViewSet updates)
  1.1 --> 2.6 (sha256_hash in serializer)
  2.4 + 2.5 + 2.6 --> 2.7 (Phase 2 tests)

Phase 3 (Deduplication):
  1.1 --> 3.1 (SHA-256 utility)
  2.6 --> 3.2 (deduplicated field in serializer)
  3.1 + 3.2 --> 3.3 (dedup in create)
  3.3 --> 3.4 (ref-counted deletion)
  3.3 --> 3.5 (/duplicates/ route)
  3.3 + 3.4 --> 3.6 (PUT/PATCH handling)
  3.3 + 3.4 + 3.5 + 3.6 --> 3.7 (Phase 3 tests)

Phase 4 (API Keys & Rate Limiting):
  1.3 --> 4.1 (authentication class)
  4.1 --> 4.2 (key management endpoints)
  4.1 + 1.4 --> 4.3 (key-scoped visibility)
  4.1 + 1.4 --> 4.4 (file ownership on upload)
  4.1 --> 4.5 (throttle classes)
  4.5 --> 4.6 (rate limit headers)
  4.1 + 4.4 --> 4.7 (storage quota)
  4.1 + 4.2 + 4.3 + 4.4 --> 4.8 (auth & key tests)
  4.5 + 4.6 + 4.7 --> 4.9 (rate limit & quota tests)
  All --> 4.10 (integration tests)
```

## Out of Scope

- Client-provided hashes for upload verification
- Content-addressable storage (renaming files to their hash)
- Cross-server or distributed deduplication
- File compression
- Full-text search with relevance ranking (PostgreSQL SearchVector)
- Saved searches or search history
- Faceted search
- Size-based filtering (`min_size`/`max_size`)
- Filtering by `sha256_hash`
- Offset-based pagination
- Full user accounts or OAuth
- Key rotation or expiration
- Per-endpoint rate limits
- Bandwidth quotas
- Usage analytics or dashboards
- Billing integration
- Redis-backed rate limiting
- Transferring file ownership between keys
- Automatic anonymous file expiration/TTL

## Resolved Implementation Decisions (Phase 1)

- **`on_delete=PROTECT` on `File.api_key`** — Spec required `SET_NULL`; implementation uses `PROTECT` to prevent silent data orphaning when an `ApiKey` is hard-deleted. Since the `DELETE /api/keys/{id}/` endpoint only sets `is_active=False` (never hard-deletes), PROTECT is never triggered in normal operation. **Stakeholder approved: keep PROTECT.**
- **API keys stored as SHA-256 hashes** — Spec described storing the raw 64-char token; implementation stores `sha256(raw_token)` instead to prevent plaintext credential exposure. Raw token is returned to the caller once at creation and never again. **Security improvement; accepted as-is.**
- **Single consolidated `0001_initial.py`** — Spec described four sequential migrations for a rolling production deployment. Collapsed to one migration because the database is greenfield (no existing data to backfill). Backfill migration should be re-introduced if deploying against an existing database with files.
- **`db_table = 'file_record'`** — Table renamed from Django's default `files_file` for readability. Not in spec; cosmetic change with no functional impact.

## Open Questions

1. **PUT/PATCH with file replacement (Spec Open Question 4)**: The spec recommends disallowing file content replacement after creation, making `file` and `sha256_hash` read-only on update. Task 3.6 implements this recommendation. Stakeholder confirmation needed -- if file replacement IS allowed, reference counting and hash recomputation add significant complexity.

2. **Cursor pagination `count` field (Spec Open Question 5)**: The spec shows `count` in the response envelope but notes DRF's CursorPagination does not provide it natively. The spec recommends making it opt-in (`?include_count=true`). Task 2.2 implements `count` on every request (option a) as shown in the API contract. If this proves expensive, convert to opt-in in a follow-up.

3. **Deduplication + quota contradiction**: The spec contains contradictory guidance. Feature 1 says "the size of the file IS still charged to the requesting key's storage quota" for deduplicated uploads. Feature 3 says "the quota is NOT charged for a deduplicated upload." Since Feature 1 specifies that a new `File` record is ALWAYS created (with `size`), and quota is computed via `SUM(size)`, the new record's size will be counted. Task 4.7 follows Feature 1's approach (quota IS charged). This needs stakeholder resolution.

4. **Admin key behavior on upload**: The spec does not clearly define what happens when the admin key uploads a file. Since admin does not correspond to an `ApiKey` record, files uploaded with admin key would have `api_key=NULL` (same as anonymous). Is this intended? Task 4.4 implements this behavior.

5. **Anonymous file visibility with API keys**: Once API keys are introduced, anonymous requests see only `api_key=NULL` files. Existing files (pre-migration) all have `api_key=NULL`. This means anonymous users can still see all legacy files, but authenticated users cannot see them. Is this the desired behavior for legacy data?

6. **Django version in requirements.txt**: The current `requirements.txt` specifies `Django>=4.0,<5.0` but the spec says Django 5.1 is in use. The requirements should be updated to `Django>=5.0,<6.0` or pinned to `Django==5.1.*`. This is not part of the spec but is a correctness issue.
