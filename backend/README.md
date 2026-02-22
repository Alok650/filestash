# File Hub Backend

Django-based backend for the File Hub application, providing a robust API for file management.

## 🚀 Technology Stack

- Python 3.9+
- Django 4.x
- Django REST Framework
- SQLite (Development database)
- Docker
- WhiteNoise for static file serving

## 📋 Prerequisites

- Python 3.9 or higher
- pip
- Docker (if using containerized setup)
- virtualenv or venv (recommended)

## 🛠️ Installation & Setup

### Local Development

1. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Setup**
   Create a `.env` file in the backend directory:
   ```env
   DEBUG=True
   SECRET_KEY=your-secret-key
   ALLOWED_HOSTS=localhost,127.0.0.1
   ```

4. **Database Setup**
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   ```
   Note: SQLite database will be automatically created at `db.sqlite3`

5. **Run Development Server**
   ```bash
   python manage.py runserver
   ```
   Access the API at http://localhost:8000/api

### Docker Setup

```bash
# Build the image
docker build -t file-hub-backend .

# Run the container
docker run -p 8000:8000 file-hub-backend
```

## 📁 Project Structure

```
backend/
├── core/           # Project settings and main URLs
├── files/          # File management app
│   ├── models.py   # Data models
│   ├── views.py    # API views
│   ├── urls.py     # URL routing
│   └── tests.py    # Unit tests
├── db.sqlite3      # SQLite database
└── manage.py       # Django management script
```

## 🔌 API Endpoints

### Files API (`/api/files/`)

- `GET /api/files/`: List all files
  - Query Parameters:
    - `search`: Search files by name
    - `sort`: Sort by created_at, name, or size

- `POST /api/files/`: Upload new file
  - Request: Multipart form data
  - Fields:
    - `file`: File to upload
    - `description`: Optional file description

- `GET /api/files/<uuid>/`: Get file details
- `DELETE /api/files/<uuid>/`: Delete file

## 🔒 Security Features

- UUID-based file identification
- WhiteNoise for secure static file serving
- CORS configuration for frontend integration
- Django's built-in security features:
  - CSRF protection
  - XSS prevention
  - SQL injection protection

## 🧪 Testing

Tests use Python's standard `unittest` framework via Django's test runner. All test modules live under `files/tests/`, one file per source module.

```bash
# Run the entire test suite
python manage.py test

# Run all tests in the files app
python manage.py test files

# Run all tests in a single test module
python manage.py test files.tests.test_repository

# Run a single test class
python manage.py test files.tests.test_pagination.PaginationEnvelopeTests

# Run a single test method
python manage.py test files.tests.test_pagination.PaginationEnvelopeTests.test_default_page_size_is_20
```

### Test modules

| File | Source module | What's covered |
|------|--------------|----------------|
| `tests/test_crypto.py` | `crypto.py` | `hash_api_key()` — output format, determinism, collision resistance |
| `tests/test_repository.py` | `repository.py` | ApiKey + File CRUD, dedup helpers, quota aggregation, reference-counted deletion |
| `tests/test_pagination.py` | `pagination.py` | Cursor envelope shape, cursor navigation, page_size clamping, filtered count |
| `tests/test_filters.py` | `filters.py` | Filename search, file_type exact/prefix, date range, invalid datetime → 400 |
| `tests/test_views.py` | `views.py` | Ordering validation (valid fields, 400 on invalid, error format), composability |
| `tests/test_serializers.py` | `serializers.py` | `sha256_hash` in list/detail responses, null hash, read-only enforcement |

## 🐛 Troubleshooting

1. **Database Issues**
   ```bash
   # Reset database
   rm db.sqlite3
   python manage.py migrate
   ```

2. **Static Files**
   ```bash
   python manage.py collectstatic
   ```

3. **Permission Issues**
   - Check file permissions in media directory
   - Ensure write permissions for SQLite database directory

## 📚 Contributing

1. Fork the repository
2. Create your feature branch
3. Write and run tests
4. Commit your changes
5. Push to the branch
6. Create a Pull Request

## 📖 Documentation

- API documentation available at `/api/docs/`
- Admin interface at `/admin/`
- Detailed API schema at `/api/schema/` 