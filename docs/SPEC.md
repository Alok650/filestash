# Product Specification: File Vault

**Date:** 2026-02-21
**Version:** 1.0

File Vault is a Django REST Framework API-only backend for file hosting. This specification defines three new features -- content-hash-based file deduplication, search and filtering with cursor-based pagination, and API-key-based rate limiting with per-key storage quotas -- to be implemented on top of the existing upload/download/list/delete API. The goal is to transform File Vault from a naive file store into a production-grade API that prevents wasted disk space, supports efficient file discovery, and enforces fair-use limits without requiring a full user-management system.

---

## Current State

### Stack
- Django 5.1, Django REST Framework, SQLite (`backend/data/db.sqlite3`), WhiteNoise (static files), Gunicorn
- No frontend; API-only at `http://localhost:8000/api/`
- Media files served via Django's `static()` helper in development at `/media/uploads/`

### Data Model (`files.File`)

| Field              | Type                  | Notes                                      |
|--------------------|-----------------------|--------------------------------------------|
| `id`               | UUIDField (PK)        | Auto-generated, not editable               |
| `file`             | FileField             | Stored at `uploads/<uuid>.<ext>`           |
| `original_filename`| CharField(255)        | Preserved from the uploaded file name      |
| `file_type`        | CharField(100)        | Populated from `content_type`              |
| `size`             | BigIntegerField       | Bytes                                      |
| `uploaded_at`      | DateTimeField         | `auto_now_add=True`                        |

Default ordering: `-uploaded_at`.

### Existing Endpoints

| Method        | Path                 | Behavior                                   |
|---------------|----------------------|--------------------------------------------|
| `GET`         | `/api/files/`        | List all files (no pagination, no filters) |
| `POST`        | `/api/files/`        | Upload file (multipart `file` field)       |
| `GET`         | `/api/files/{id}/`   | Retrieve single file record                |
| `PUT/PATCH`   | `/api/files/{id}/`   | Update file record                         |
| `DELETE`      | `/api/files/{id}/`   | Delete file record and file from disk      |

### What Does Not Exist Yet
- Authentication or identity of any kind (permission is `AllowAny`)
- Rate limiting
- Storage quotas
- Content hashing or deduplication
- Search, filtering, or pagination
- Any concept of file ownership

---

## Feature 1: File Deduplication

### Motivation

Identical files uploaded multiple times waste disk space and make management harder. A SHA-256 content hash computed server-side allows the system to detect duplicates at upload time and skip the redundant disk write — even across different API keys. Crucially, each uploading key still receives its own `File` record so that file visibility remains fully key-scoped: User A never sees User B's records, even if both uploaded the same bytes.

### User Story

> As an API consumer, I want duplicate file uploads to be recognized automatically so that disk space is not wasted, while still receiving my own file record that I can manage independently.

### Key Design Decision (Resolved)

**Cross-key deduplication with per-key records.** When two different API keys upload identical content:
- The physical file is written to disk **only once** (the first upload wins).
- Subsequent uploads of the same content by **any** key create a new `File` database record pointing to the same physical file path on disk. No second disk write occurs.
- Each key always receives its **own** `File` record in the response (`201 Created`). The caller never sees another key's record.
- `deduplicated: true` in the response signals that no new bytes were written to disk, even though a new DB record was created.

This separates the two concerns cleanly: **storage efficiency** (one file on disk per unique content hash) and **data isolation** (each key has its own independent record, with its own `id`, `original_filename`, and `uploaded_at`).

### Functional Requirements

1. **Hash computation:** On every upload, compute the SHA-256 hash of the file content server-side by reading the file in 8 KB chunks via `UploadedFile.chunks()`. Store the hex-encoded hash in a new `sha256_hash` field on the `File` model.
2. **Duplicate disk detection:** Before writing the file to disk, query `File.objects.filter(sha256_hash=computed_hash).first()`. If a record exists, the physical file is already on disk at that record's `file.name` path. **Skip the disk write** and reuse that path for the new `File` record's `file` field.
3. **New record always created:** A new `File` row is **always** inserted into the database for each upload, regardless of whether the content is a duplicate. The new record is owned by the requesting API key and has its own `id`, `original_filename`, `uploaded_at`, and `api_key`.
4. **Response on duplicate:** Return HTTP `201 Created` (always) with the **newly created** record. Include `deduplicated: true` when the disk write was skipped; `deduplicated: false` when a new file was written to disk.
5. **Hash field:** Add `sha256_hash` (CharField, max_length=64, db_index=True) to the `File` model. This field is read-only in the API; clients cannot set or modify it.
6. **Duplicates endpoint:** Add `GET /api/files/{id}/duplicates/` as a detail route on `FileViewSet`. It returns all `File` records owned by the **requesting API key** that share the same `sha256_hash` as the given file, excluding the file itself. Cross-key records are never exposed. If the file ID does not exist or does not belong to the requesting key, return `404`. If no duplicates exist within the caller's own records, return `[]`.
7. **Serializer change:** Add `sha256_hash` and `deduplicated` to the `FileSerializer` response fields. `deduplicated` is a `SerializerMethodField` that defaults to `false`; the view sets it contextually to `true` when a disk-reuse occurred.
8. **Backfill migration:** Provide a data migration that computes `sha256_hash` for all existing files on disk. Files whose physical file is missing on disk should have `sha256_hash` set to `NULL` and log a warning.

### API Contract Changes

#### Upload (existing `POST /api/files/`)

The response is always `201 Created`. The only difference between a fresh upload and a deduplicated upload is the `deduplicated` flag and whether a new file appears on disk.

**New upload (first time this content is seen) — 201 Created:**
```json
{
  "id": "a1b2c3d4-...",
  "file": "http://localhost:8000/media/uploads/a1b2c3d4.png",
  "original_filename": "photo.png",
  "file_type": "image/png",
  "size": 204800,
  "uploaded_at": "2026-02-21T10:00:00Z",
  "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "deduplicated": false
}
```

**Duplicate content upload (disk write skipped, new DB record created) — 201 Created:**
```json
{
  "id": "new-uuid-for-this-key-...",
  "file": "http://localhost:8000/media/uploads/a1b2c3d4.png",
  "original_filename": "my-copy-of-photo.png",
  "file_type": "image/png",
  "size": 204800,
  "uploaded_at": "2026-02-21T14:00:00Z",
  "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "deduplicated": true
}
```

Note: The `id` and `uploaded_at` are the caller's **new** record. The `file` URL resolves to the same physical file that was first written by whichever key originally uploaded this content. The `original_filename` reflects what the current caller uploaded, not the original uploader's name. The `file` URL is shared but record ownership is not.

#### Duplicates endpoint (new)

**`GET /api/files/{id}/duplicates/`**

Returns all records **owned by the requesting API key** that share the same hash as the given file, excluding the file itself. This lets a user discover if they have uploaded the same content under different filenames.

Response `200 OK` (two records by the same key with identical content):
```json
[
  {
    "id": "another-uuid-same-key-...",
    "file": "http://localhost:8000/media/uploads/a1b2c3d4.png",
    "original_filename": "backup-photo.png",
    "file_type": "image/png",
    "size": 204800,
    "uploaded_at": "2026-02-21T16:00:00Z",
    "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "deduplicated": true
  }
]
```

Response `404 Not Found` if the file ID does not exist **or does not belong to the requesting key**. Cross-key records are never surfaced here.

### Data Model Changes

Add to `files.File`:

```python
sha256_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
```

`null=True` is necessary to allow the backfill migration to handle files whose physical content is missing. Once the backfill completes successfully, a follow-up migration can make the field non-nullable if desired, but that is out of scope for this iteration.

### Deletion Behavior and Reference Counting

Because multiple `File` records across different keys can point to the same physical file on disk, deletion must be reference-counted **globally across all keys**.

When a file record is deleted:
1. Count all other `File` records (across all API keys) sharing the same `sha256_hash`: `File.objects.filter(sha256_hash=instance.sha256_hash).exclude(id=instance.id).exists()`.
2. If any other records exist (any key), delete only the database record. Leave the physical file on disk — other records still reference it.
3. If no other records exist globally (this was the last record pointing to this content), delete both the database record and the physical file from disk.

Implementation approach: Override `perform_destroy` in `FileViewSet`. Authorization check ensures the caller can only delete their own records (i.e., records where `api_key == request.auth`). The reference-count check is global (no key filter), because physical disk files are shared cross-key.

**Permission:** A key can only delete its own `File` records. Attempting to delete another key's record returns `404` (the record is invisible to them, per the key-scoped visibility rule).

### Edge Cases and Constraints

- **Empty files:** An empty file has a well-defined SHA-256 hash (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`). Two empty files of different names should be treated as duplicates. This is correct behavior.
- **Large files:** Hash computation should stream the file in chunks (8 KB) to avoid loading the entire file into memory. Django's `UploadedFile` supports `chunks()`.
- **Race condition:** Two concurrent uploads of the same new file could both pass the duplicate check and both write to disk. This is acceptable for the MVP on SQLite (single-writer). The second write creates a redundant file on disk, but both records will have the same hash, so future uploads will dedup correctly. No data corruption occurs.
- **File content changes via PUT/PATCH:** If a user replaces the file content via `PUT/PATCH`, the `sha256_hash` must be recomputed, a new duplicate check must run, and if the new content already exists on disk the disk write is skipped (same logic as `create`). The old content's reference count must be decremented (same logic as deletion).
- **Quota interaction:** On a deduplicated upload (`deduplicated: true`), the `size` of the file **is still charged** to the requesting key's storage quota. The key owns a new record pointing to real bytes, even if those bytes were not written a second time. This is the correct behavior: quota reflects what a key is responsible for, not the physical bytes on disk.

### Out of Scope

- Client-provided hashes for upload verification (the server always computes the hash)
- Content-addressable storage (renaming files on disk to their hash)
- Cross-server deduplication
- Compression of stored files
- Returning another key's record in any response

---

## Feature 2: Search & Filtering

### Motivation

The current `GET /api/files/` endpoint returns every file in the database with no filtering or pagination. This is unusable at scale. Adding search, filtering, and cursor-based pagination enables clients to efficiently find and browse files.

### User Story

> As an API consumer, I want to search for files by name, filter by type and date, and page through results efficiently so that I can find and manage files without downloading the entire catalog.

### Functional Requirements

1. **Key-scoped results:** `GET /api/files/` always returns only files owned by the requesting API key (`api_key == request.auth`). Anonymous requests see only files uploaded without an API key (`api_key IS NULL`). The admin key sees all files across all keys. This scoping is applied before any search or filter parameters and is not user-controllable.
2. **Search:** The `search` query parameter performs a case-insensitive substring match on `original_filename`. Example: `?search=report` matches `Q1-Report.pdf` and `report_final.docx`. Search is scoped to the caller's own files.
3. **File type filter:** The `file_type` query parameter supports both exact match and prefix match. Exact: `?file_type=image/png`. Prefix: `?file_type=image/` matches `image/png`, `image/jpeg`, etc. The trailing slash signals prefix mode.
4. **Date range:** `uploaded_after` and `uploaded_before` query parameters accept ISO 8601 datetime strings (e.g., `2026-02-01T00:00:00Z`). Both bounds are inclusive. Either can be used independently.
5. **Ordering:** The `ordering` query parameter accepts a comma-separated list of fields: `original_filename`, `size`, `uploaded_at`. Prefix with `-` for descending. Default ordering remains `-uploaded_at`. Invalid field names return `400`.
6. **Pagination:** Cursor-based pagination with a default page size of 20 and a maximum of 100 (controlled by `page_size` query parameter). The response envelope includes `count`, `next`, and `previous`.
7. **Validation:** All filter parameters must be validated. Invalid values return HTTP `400` with a JSON body containing a machine-readable `errors` object.
8. **Composability:** All filters, search, ordering, and pagination work together. For example: `?search=report&file_type=application/pdf&uploaded_after=2026-01-01T00:00:00Z&ordering=-uploaded_at&page_size=10`.

### API Contract Changes

#### `GET /api/files/`

**New query parameters:**

| Parameter        | Type     | Description                                      | Example                        |
|------------------|----------|--------------------------------------------------|--------------------------------|
| `search`         | string   | Case-insensitive substring match on filename     | `?search=report`               |
| `file_type`      | string   | Exact or prefix match on MIME type               | `?file_type=image/`            |
| `uploaded_after`  | datetime | ISO 8601, inclusive lower bound                  | `?uploaded_after=2026-01-01T00:00:00Z` |
| `uploaded_before` | datetime | ISO 8601, inclusive upper bound                  | `?uploaded_before=2026-02-01T00:00:00Z` |
| `ordering`       | string   | Comma-separated sort fields (prefix `-` = desc)  | `?ordering=-size,original_filename` |
| `page_size`      | integer  | Results per page (1-100, default 20)             | `?page_size=50`                |

**Response envelope (paginated):**

```json
{
  "count": 142,
  "next": "http://localhost:8000/api/files/?cursor=cD0yMDI2LTAy...",
  "previous": null,
  "results": [
    {
      "id": "...",
      "file": "...",
      "original_filename": "report-q1.pdf",
      "file_type": "application/pdf",
      "size": 204800,
      "uploaded_at": "2026-02-21T10:00:00Z",
      "sha256_hash": "abc123..."
    }
  ]
}
```

Note: `count` represents the total number of results matching the current filters, not the total number of files in the system. With DRF's `CursorPagination`, `count` is not natively supported (cursor pagination is designed for infinite scroll and does not compute totals). See the implementation note below.

**Pagination implementation note:** DRF's built-in `CursorPagination` does not provide a `count` field. To include `count`, create a custom pagination class that extends `CursorPagination` and adds a `count` key by running a `.count()` query on the filtered queryset. This adds one extra query per paginated request but is necessary for the specified contract. If this proves too expensive on large datasets, we can make `count` opt-in via a `?include_count=true` parameter in a future iteration.

**Error response (400):**

```json
{
  "errors": {
    "uploaded_after": ["Enter a valid date/time in ISO 8601 format."],
    "ordering": ["Invalid ordering field: 'invalid_field'. Valid fields: original_filename, size, uploaded_at."]
  }
}
```

### Data Model Changes

None. All filtering is performed on existing fields.

### DRF Configuration

Add to `REST_FRAMEWORK` in `settings.py`:

```python
'DEFAULT_PAGINATION_CLASS': 'files.pagination.FileVaultCursorPagination',
'PAGE_SIZE': 20,
'DEFAULT_FILTER_BACKENDS': [
    'django_filters.rest_framework.DjangoFilterBackend',
    'rest_framework.filters.SearchFilter',
    'rest_framework.filters.OrderingFilter',
],
```

Add `django-filter` to `requirements.txt`. The `SearchFilter` handles the `search` parameter. The `OrderingFilter` handles `ordering`. Custom filter logic for `file_type` prefix matching, `uploaded_after`, and `uploaded_before` is implemented as a `django_filters.FilterSet` subclass. No database index on `size` is required or created.

### UX / Developer-Experience Considerations

- **Trailing-slash prefix matching:** The `file_type=image/` convention is simple and avoids introducing a separate `file_type_prefix` parameter. Document this clearly in the API reference. A trailing slash is unlikely to appear in a legitimate full MIME type, making it an unambiguous signal.
- **Empty results:** Filters that match no files return `200 OK` with `"count": 0, "results": []`, never `404`.
- **Page size bounds:** `page_size` values less than 1 or greater than 100 are clamped to the nearest valid value (1 or 100) rather than returning an error, to avoid unnecessary client failures. Document the clamping behavior.
- **Ordering stability:** Cursor pagination requires a deterministic ordering. If the user-provided `ordering` does not include `uploaded_at` or `id`, append `id` as a tiebreaker to ensure stable cursors.

### Edge Cases and Constraints

- **Search with special characters:** The `search` parameter is used in a Django `icontains` lookup. Characters like `%` and `_` have no special meaning in `icontains` (Django escapes them). No additional sanitization needed.
- **Empty search string:** `?search=` (empty value) is treated as "no search filter" and returns all results.
- **Timezone handling:** The project uses `USE_TZ = True` and `TIME_ZONE = "UTC"`. All datetime filter values should be parsed as UTC if no timezone offset is provided.

### Out of Scope

- Full-text search with relevance ranking (e.g., PostgreSQL `SearchVector`)
- Saved searches or search history
- Faceted search (returning count-by-type breakdowns)
- Size-based filtering (`min_size` / `max_size`) — no index on `size` will be created; clients retrieve size from individual records
- Filtering by `sha256_hash` (can be added later trivially)
- Offset-based pagination (cursor-based only for performance and consistency)

---

## Feature 3: API Rate Limiting & Per-User Storage Quota

### Motivation

File Vault currently has no authentication and no resource limits. Any client can upload unlimited files at unlimited speed. Before opening the API to multiple consumers, we need a lightweight identity layer (API keys, not full user accounts), request rate limiting, and per-key storage quotas to prevent abuse and ensure fair resource sharing.

### User Stories

> As an API operator, I want to issue API keys to consumers so that I can track and limit usage per consumer.

> As an API operator, I want rate limits so that no single consumer can overwhelm the service.

> As an API consumer, I want to see my storage usage and quota so that I can manage my uploads proactively.

### Functional Requirements

#### Identity: API Key Model

1. **New model `ApiKey`:**

   | Field                | Type              | Notes                                           |
   |----------------------|-------------------|-------------------------------------------------|
   | `id`                 | UUIDField (PK)    | Auto-generated                                  |
   | `key`                | CharField(64)     | Random 32-byte hex token, unique, db_indexed    |
   | `label`              | CharField(100)    | Human-readable name (e.g., "CI Pipeline Key")   |
   | `is_active`          | BooleanField      | Default `True`; inactive keys are rejected      |
   | `storage_quota_bytes`| BigIntegerField   | Default 1073741824 (1 GB)                       |
   | `created_at`         | DateTimeField     | `auto_now_add=True`                             |

2. **Key generation:** Keys are generated server-side using `secrets.token_hex(32)`. Clients never provide their own key values.
3. **Authentication header:** Clients pass `Authorization: ApiKey <token>`. The custom authentication class parses this header, looks up the key, verifies `is_active=True`, and attaches the `ApiKey` instance to `request.auth`. `request.user` remains `AnonymousUser` (we do not use Django's auth system).
4. **Anonymous access:** Requests without an `Authorization` header (or with an invalid/inactive key) are treated as anonymous. Anonymous requests are accepted but subject to stricter rate limits and a shared storage pool.
5. **Invalid key behavior:** A request with a correctly formatted `Authorization: ApiKey <token>` header where the token does not match any active key returns HTTP `401 Unauthorized` with `{"error": "invalid_api_key"}`. A malformed header (wrong scheme, missing token) is treated as anonymous, not as an error.
6. **Key management endpoint:**
   - `POST /api/keys/` -- Create a new API key. Requires the admin key: `Authorization: ApiKey <ADMIN_API_KEY>` where `ADMIN_API_KEY` is read from an environment variable. Request body: `{"label": "My Key", "storage_quota_bytes": 5368709120}`. The `storage_quota_bytes` field is optional (defaults to 1 GB). Response: `201 Created` with the full key object **including the key value** (this is the only time the full key is returned).
   - `GET /api/keys/me/` -- Returns the current key's information. Requires a valid API key. Returns `401` for anonymous requests.
   - `DELETE /api/keys/{id}/` -- Deactivate a key (sets `is_active=False`). Requires the admin key. Does not delete the record (preserves audit trail).

#### Rate Limiting

7. **Throttle classes:** Implement two custom DRF throttle classes: `ApiKeySecondRateThrottle` and `ApiKeyMinuteRateThrottle`, extending `SimpleRateThrottle`. The throttle key is the API key value for authenticated requests, or the client IP for anonymous requests.
8. **Rate limits:**

   | Identity      | Per-second | Per-minute |
   |---------------|------------|------------|
   | Authenticated | 10         | 300        |
   | Anonymous     | 2          | 30         |

9. **Cache backend:** Throttle state uses Django's default cache (`LocMemCache`). No Redis required. Add to `settings.py`:

   ```python
   CACHES = {
       'default': {
           'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
           'LOCATION': 'rate-limit-cache',
       }
   }
   ```

10. **429 response:** When rate limited, return HTTP `429 Too Many Requests` with a `Retry-After` header (integer seconds until the window resets) and body:

    ```json
    {
      "error": "rate_limit_exceeded",
      "retry_after": 12
    }
    ```

11. **Rate limit headers:** Include on every response (success or error):

    | Header                  | Value                                          |
    |-------------------------|-------------------------------------------------|
    | `X-RateLimit-Limit`     | The applicable rate limit for this window       |
    | `X-RateLimit-Remaining` | Requests remaining in the current window        |
    | `X-RateLimit-Reset`     | Unix timestamp when the current window resets   |

    Implementation: Add a custom middleware or override `finalize_response` on the viewset to inject these headers. DRF throttle classes expose `wait()` and internal state that can be used to compute these values.

#### Storage Quota

12. **Authenticated quota:** Each `ApiKey` has a `storage_quota_bytes` field. On upload, compute the sum of `size` for all `File` records associated with the key. If `used + new_file_size > quota`, reject with HTTP `413 Payload Too Large`:

    ```json
    {
      "error": "storage_quota_exceeded",
      "used_bytes": 1048576000,
      "quota_bytes": 1073741824
    }
    ```

13. **Anonymous quota:** Anonymous uploads draw from a global pool. The total size of all files uploaded without an API key is capped at `ANONYMOUS_STORAGE_QUOTA_MB` (environment variable, default 100). Computed as `File.objects.filter(api_key__isnull=True).aggregate(Sum('size'))`.
14. **File ownership:** Add a nullable `api_key` ForeignKey on the `File` model pointing to `ApiKey`. Files uploaded anonymously have `api_key=NULL`. Files uploaded with a key are associated with that key.
15. **Quota on `GET /api/keys/me/`:** Response includes computed usage:

    ```json
    {
      "id": "key-uuid-...",
      "label": "CI Pipeline Key",
      "is_active": true,
      "storage_quota_bytes": 1073741824,
      "storage_used_bytes": 524288000,
      "created_at": "2026-02-15T08:00:00Z"
    }
    ```

    The `key` field itself is **not** returned on `GET /api/keys/me/` (it was only shown once at creation time). This prevents key leakage in logs and monitoring tools.

16. **Quota reclamation on delete:** When a file is deleted, the freed space is immediately reflected in the key's quota. Since quota is computed dynamically via `SUM(size)`, no separate counter needs to be decremented -- deletion of the `File` row is sufficient.

17. **Deduplication interaction:** When a duplicate upload is detected (Feature 1), no new `File` record is created and no disk space is consumed. Therefore, the quota is **not** charged for a deduplicated upload. The response clearly indicates `deduplicated: true`.

### API Contract Changes

#### New Endpoints

| Method   | Path              | Auth Required | Description                            |
|----------|-------------------|---------------|----------------------------------------|
| `POST`   | `/api/keys/`      | Admin key     | Create a new API key                   |
| `GET`    | `/api/keys/me/`   | Any valid key | Get current key info + usage           |
| `DELETE` | `/api/keys/{id}/` | Admin key     | Deactivate a key                       |

#### Modified Endpoints

| Endpoint          | Change                                                        |
|-------------------|---------------------------------------------------------------|
| `POST /api/files/`| Quota check before write; associates file with `api_key`     |
| `GET /api/files/` | Authenticated users see only their own files + anonymous files; admin key sees all (see Open Questions) |
| All endpoints     | Rate limit headers added to every response                    |

#### New Error Codes

| HTTP Status | Error Key                | When                                         |
|-------------|--------------------------|----------------------------------------------|
| `401`       | `invalid_api_key`        | Valid header format but key not found/inactive|
| `413`       | `storage_quota_exceeded` | Upload would exceed key or anonymous quota   |
| `429`       | `rate_limit_exceeded`    | Request rate exceeds throttle limit          |

### Data Model Changes

**New model: `files.ApiKey`** (see table in Functional Requirements above)

**Modified model: `files.File`** -- Add:

```python
api_key = models.ForeignKey(
    'ApiKey',
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name='files'
)
```

`on_delete=models.SET_NULL` ensures that deactivating or eventually deleting a key does not cascade-delete files. Orphaned files remain accessible and can be cleaned up separately.

### Environment Variables

| Variable                    | Default  | Description                              |
|-----------------------------|----------|------------------------------------------|
| `ADMIN_API_KEY`             | (none)   | Required in production. Grants admin access to key management. |
| `ANONYMOUS_STORAGE_QUOTA_MB`| `100`    | Total storage allowed for anonymous uploads (MB). |

If `ADMIN_API_KEY` is not set, the `POST /api/keys/` and `DELETE /api/keys/{id}/` endpoints return `503 Service Unavailable` with `{"error": "admin_key_not_configured"}`. This prevents silent misconfigurations.

### UX / Developer-Experience Considerations

- **Key shown once:** The full API key is returned only in the `POST /api/keys/` response. Document this clearly: "Store this key securely. It will not be shown again."
- **Actionable 413 errors:** The `storage_quota_exceeded` error includes both `used_bytes` and `quota_bytes` so the client can display a meaningful message or calculate how much space to free.
- **Actionable 429 errors:** The `retry_after` field and `Retry-After` header are both integers (seconds), making them trivial to use in a `sleep()` call for retry logic.
- **Rate limit headers on every response:** Clients can proactively back off before hitting `429` by monitoring `X-RateLimit-Remaining`.
- **Graceful degradation for anonymous users:** Anonymous access is not blocked; it is simply more restricted. This lowers the barrier to initial API exploration.

### Edge Cases and Constraints

- **Admin key in Authorization header:** The admin key does not correspond to an `ApiKey` database record. It is compared directly against the `ADMIN_API_KEY` environment variable. Requests authenticated with the admin key are not subject to storage quotas or rate limits. The admin key has no `storage_used_bytes` because it does not own files.
- **LocMemCache and multi-process:** `LocMemCache` is per-process. Under Gunicorn with multiple workers, each worker maintains its own rate limit counters. This means the effective rate limit is multiplied by the number of workers. For the MVP on a single-worker dev server, this is acceptable. Document this limitation. For production, recommend switching to a shared cache backend (Redis or Memcached).
- **Quota race condition:** Two concurrent uploads for the same key could both pass the quota check and both succeed, temporarily exceeding the quota. This is acceptable for the MVP. The overshoot is bounded by the size of a single upload. A strict implementation would use `SELECT ... FOR UPDATE`, but SQLite does not support row-level locking.
- **Key rotation:** There is no key rotation mechanism in this iteration. A new key must be created and the old one deactivated manually.
- **File visibility:** After adding `api_key` to `File`, the question of visibility arises. See Open Questions.

### Out of Scope

- Full user accounts or OAuth
- Key rotation or expiration
- Per-endpoint rate limits (all endpoints share the same throttle)
- Bandwidth quotas (only storage is metered)
- Usage analytics or dashboards
- Billing integration
- Redis-backed rate limiting
- Transferring file ownership between keys

---

## Migration & Rollout

Implementation should proceed in this order to minimize risk and ensure each feature builds on a stable foundation.

### Phase 1: Data Model Migrations (No endpoint changes)

1. **Migration 1:** Add `sha256_hash` (nullable CharField) to `File`.
2. **Migration 2 (data migration):** Backfill `sha256_hash` for all existing files by reading each file from disk and computing its SHA-256 hash. Log warnings for files missing from disk.
3. **Migration 3:** Create the `ApiKey` model.
4. **Migration 4:** Add `api_key` (nullable ForeignKey to `ApiKey`) to `File`.

All four migrations can be combined into a single deployment. Existing API behavior is unchanged.

### Phase 2: Search & Filtering

5. Add `django-filter` to `requirements.txt`.
6. Implement the custom `FilterSet`, cursor pagination class, and ordering validation.
7. Update DRF settings to use the new pagination and filter backends.
8. Add `sha256_hash` to the serializer as a read-only field.

This phase is purely additive -- the list endpoint gains new optional query parameters and pagination. Existing clients that pass no parameters get paginated results (a breaking change in response shape), so coordinate with any existing API consumers.

**Breaking change note:** Wrapping the list response in a `{"count": ..., "next": ..., "previous": ..., "results": [...]}` envelope is a breaking change for clients that expect a bare array. If this is a concern, gate it behind a versioned URL or an `Accept` header. Given that the API is pre-production, this spec assumes the breaking change is acceptable.

### Phase 3: File Deduplication

9. Implement SHA-256 hash computation in the `create` and `update` paths.
10. Implement duplicate detection logic and the modified upload response.
11. Implement the `/duplicates/` detail route.
12. Implement reference-counted deletion.

This phase depends on the `sha256_hash` field from Phase 1 being populated.

### Phase 4: API Keys, Rate Limiting, and Quotas

13. Implement the `ApiKeyAuthentication` class.
14. Implement the `POST /api/keys/`, `GET /api/keys/me/`, `DELETE /api/keys/{id}/` endpoints.
15. Implement the two throttle classes and rate limit response headers.
16. Implement quota checking in the upload path.
17. Associate uploaded files with the requesting API key.

This phase is last because it introduces authentication, which affects all other endpoints. It should be tested end-to-end with Features 1 and 2 to ensure correct interaction (e.g., deduplication does not charge quota, filters work with file ownership).

---

## Resolved Decisions

1. **File visibility per API key — RESOLVED:** Key-scoped. Each API key sees only its own files via `GET /api/files/`. The admin key sees all files across all keys. Anonymous requests see only files uploaded without any key.

2. **Deduplication across keys — RESOLVED:** Deduplicate on disk, but always create a new `File` record per upload. When User A and User B upload identical content, the physical file is written to disk only once. User B's upload creates a new `File` record pointing to that same disk path, with `deduplicated: true` in the response. User B's record is independent — they see it in their own file list, can delete it, and it is charged to their own quota. Neither user ever sees the other's records.

## Open Questions

These items still require sign-off before implementation begins.

3. **Anonymous upload cleanup:** Should anonymous files be subject to automatic expiration (e.g., deleted after 7 days)? If the anonymous quota fills up, no new anonymous uploads are possible until an admin manually deletes files. Recommendation: Defer TTL to a future iteration; document the manual cleanup requirement for now.

4. **PUT/PATCH with file replacement:** Allowing `PUT/PATCH` to replace file content interacts poorly with deduplication (reference counts change, hash must be recomputed) and quota accounting. Recommendation: Disallow file content replacement after creation — make `file` and `sha256_hash` read-only on update. Only `original_filename` should be editable. Needs stakeholder confirmation before implementation of Feature 1.

5. **Cursor pagination and `count`:** DRF's cursor pagination does not compute `count` by default; adding it requires an extra `COUNT(*)` query per list request. Options: (a) always include `count`, (b) make it opt-in via `?include_count=true`, (c) omit `count` entirely. Recommendation: Option (b) — opt-in count. Needs confirmation.

6. **Admin key management:** The `ADMIN_API_KEY` env var is static; rotating it requires a server restart. Is this acceptable for MVP? Recommendation: Yes; document the limitation.

7. **Rate limit header accuracy under LocMemCache:** Each Gunicorn worker maintains its own counter, so `X-RateLimit-Remaining` is per-worker, not global. Recommendation: Accept the inaccuracy for MVP and document it clearly; recommend Redis for production.
