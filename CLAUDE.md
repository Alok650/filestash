# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All backend commands must be run from the `backend/` directory with the virtualenv active.

```bash
# Setup
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p media staticfiles data
python manage.py migrate

# Run dev server
python manage.py runserver

# Run all tests
python manage.py test

# Run tests for the files app only
python manage.py test files.tests

# Run via Docker
docker-compose up --build
```

## Architecture

This is a Django REST Framework API-only backend (no frontend). The single `files` Django app handles all functionality.

**Request flow:** `core/urls.py` → `api/` prefix → `files/urls.py` → DRF `DefaultRouter` → `FileViewSet`

**Key design decisions:**
- Files are stored on disk under `backend/media/uploads/` with UUID-renamed filenames (original name preserved in the DB)
- The `File` model uses UUID primary keys and stores `original_filename`, `file_type`, `size`, and `uploaded_at` separately from the actual `FileField`
- The `FileViewSet` overrides `create()` to extract metadata from the uploaded file object rather than accepting it as separate form fields
- SQLite database is stored at `backend/data/db.sqlite3` (not the default location)
- Static files are served by WhiteNoise; media files are served by Django's `static()` helper in dev

**Environment variables** (read in `core/settings.py`):
- `DJANGO_SECRET_KEY` — defaults to an insecure dev key
- `DJANGO_DEBUG` — defaults to `True`

**API base URL:** `http://localhost:8000/api/`
**File download:** via the `file` URL field returned in list/detail responses (resolves to `/media/uploads/<uuid>.<ext>`)
