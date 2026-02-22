# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Makefile (preferred — run from project root)

```bash
make setup       # first-time: create venv (Python 3.11), install deps, migrate
make run         # start dev server
make test        # entire suite
make test-module MOD=test_repository
make test-class  CLS=test_pagination.PaginationEnvelopeTests
make test-method M=test_pagination.PaginationEnvelopeTests.test_default_page_size_is_20
make clean       # remove venv + compiled files
```

### Manual (from `backend/` with venv active)

```bash
# First-time setup — requires Python 3.11+
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p data media staticfiles
python manage.py migrate

# Dev server
python manage.py runserver

# Tests
python manage.py test files
python manage.py test files.tests.test_repository
python manage.py test files.tests.test_pagination.PaginationEnvelopeTests

# Docker
docker-compose up --build
```

## Architecture

This is a Django REST Framework API-only backend (no frontend). The single `files` Django app handles all functionality.

**Request flow:** `core/urls.py` → `api/` prefix → `files/urls.py` → DRF `DefaultRouter` → `FileViewSet`

**Key files in `backend/files/`:**
- `models.py` — `File` (UUID PK, sha256_hash, api_key FK) and `ApiKey` models
- `repository.py` — all DB access; views must not build raw ORM queries
- `crypto.py` — `hash_api_key()` for safe API key storage (SHA-256)
- `serializers.py` — `FileSerializer` (sha256_hash is read-only)
- `views.py` — `FileViewSet` with ordering validation and id tiebreaker
- `filters.py` — `FileFilter` (file_type exact/prefix, date range) + `FileVaultFilterBackend`
- `pagination.py` — `FileVaultCursorPagination` (count field, clamped page_size)
- `tests/` — one test module per source file (test_crypto, test_repository, test_pagination, test_filters, test_views, test_serializers)

**Key design decisions:**
- Files are stored on disk under `backend/media/uploads/` with UUID-renamed filenames (original name preserved in the DB)
- The `File` model uses UUID primary keys and stores `original_filename`, `file_type`, `size`, `uploaded_at`, and `sha256_hash`
- API keys are stored as SHA-256 hashes — plaintext is never persisted; raw token returned once at creation
- `FileViewSet.filter_queryset()` validates ordering fields explicitly (returns 400 for invalid) and appends `id` as a cursor-pagination tiebreaker
- Filter backends are on the viewset (not global settings) to avoid affecting future viewsets
- SQLite database is stored at `backend/data/db.sqlite3` (not the default location)
- Static files are served by WhiteNoise; media files are served by Django's `static()` helper in dev

**Environment variables** (read in `core/settings.py`):
- `DJANGO_SECRET_KEY` — defaults to an insecure dev key
- `DJANGO_DEBUG` — defaults to `True`

**API base URL:** `http://localhost:8000/api/`
**File list:** `GET /api/files/` — supports `search`, `file_type`, `uploaded_after`, `uploaded_before`, `ordering`, `page_size`
**File download:** via the `file` URL field returned in list/detail responses (resolves to `/media/uploads/<uuid>.<ext>`)
