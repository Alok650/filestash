# Abnormal File Vault

A Django-based file management application designed for efficient file handling and storage.

## 🚀 Technology Stack

### Backend
- Django 4.x (Python web framework)
- Django REST Framework (API development)
- SQLite (Development database)
- Gunicorn (WSGI HTTP Server)
- WhiteNoise (Static file serving)

### Infrastructure
- Docker and Docker Compose
- Local file storage with volume mounting

## 📋 Prerequisites

Before you begin, ensure you have installed:
- Docker (20.10.x or higher) and Docker Compose (2.x or higher)
- Python (3.9 or higher) - for local development

## 🛠️ Installation & Setup

### Quick start (Makefile)

Requires **Python 3.11+** and **make**.

```bash
make setup       # create venv, install deps, run migrations
make run         # start dev server at http://localhost:8000
make test        # run full test suite
```

Run `make help` to see all available targets.

### Using Docker

```bash
docker-compose up --build
```

### Manual setup

```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
mkdir -p data media staticfiles
python manage.py migrate
python manage.py runserver
```

## 🌐 Accessing the Application

- Backend API: http://localhost:8000/api

## 📝 API Documentation

### File Management Endpoints

#### List Files
- **GET** `/api/files/`
- Returns a list of all uploaded files
- Response includes file metadata (name, size, type, upload date)

#### Upload File
- **POST** `/api/files/`
- Upload a new file
- Request: Multipart form data with 'file' field
- Returns: File metadata including ID and upload status

#### Get File Details
- **GET** `/api/files/<file_id>/`
- Retrieve details of a specific file
- Returns: Complete file metadata

#### Delete File
- **DELETE** `/api/files/<file_id>/`
- Remove a file from the system
- Returns: 204 No Content on success

#### Download File
- Access file directly through the file URL provided in metadata

## 🧪 Running Tests

Tests use Python's standard `unittest` framework via Django's test runner. All test modules live under `backend/files/tests/`, one file per source module.

```bash
# Via Makefile (recommended)
make test                                                    # entire suite
make test-module MOD=test_repository                         # one module
make test-class  CLS=test_pagination.PaginationEnvelopeTests # one class
make test-method M=test_pagination.PaginationEnvelopeTests.test_default_page_size_is_20

# Directly (from backend/ with venv active)
python manage.py test files
python manage.py test files.tests.test_repository
python manage.py test files.tests.test_pagination.PaginationEnvelopeTests
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

## 🗄️ Project Structure

```
file-hub/
├── backend/                # Django backend
│   ├── files/             # Main application
│   │   ├── models.py      # Data models
│   │   ├── views.py       # API views
│   │   ├── urls.py        # URL routing
│   │   └── serializers.py # Data serialization
│   ├── core/              # Project settings
│   └── requirements.txt   # Python dependencies
└── docker-compose.yml    # Docker composition
```

## 🔧 Development Features

- Hot reloading for backend development
- Django Debug Toolbar for debugging
- SQLite for easy development

## 🐛 Troubleshooting

1. **Port Conflicts**
   ```bash
   # If port 8000 is in use, modify docker-compose.yml or use:
   python manage.py runserver 8001
   ```

2. **File Upload Issues**
   - Maximum file size: 10MB
   - Ensure proper permissions on media directory
   - Check network tab for detailed error messages

3. **Database Issues**
   ```bash
   # Reset database
   rm backend/data/db.sqlite3
   python manage.py migrate
   ```

# Project Submission Instructions

## Preparing Your Submission

1. Before creating your submission zip file, ensure:
   - All features are implemented and working as expected
   - All tests are passing
   - The application runs successfully locally
   - Remove any unnecessary files or dependencies
   - Clean up any debug/console logs

2. Create the submission zip file:
   ```bash
   # Activate your backend virtual environment first
   cd backend
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # Run the submission script from the project root
   cd ..
   python create_submission_zip.py
   ```

   The script will:
   - Create a zip file named `username_YYYYMMDD.zip` (e.g., `johndoe_20240224.zip`)
   - Respect .gitignore rules to exclude unnecessary files
   - Preserve file timestamps
   - Show you a list of included files and total size
   - Warn you if the zip is unusually large

3. Verify your submission zip file:
   - Extract the zip file to a new directory
   - Ensure all necessary files are included
   - Verify that no unnecessary files (like __pycache__, etc.) are included
   - Test the application from the extracted files to ensure everything works

## Video Documentation Requirement

**Video Guidance** - Record a screen share demonstrating:
- How you leveraged Gen AI to help build the features
- Your prompting techniques and strategies
- Any challenges you faced and how you overcame them
- Your thought process in using AI effectively

**IMPORTANT**: Please do not provide a demo of the application functionality. Focus only on your Gen AI usage and approach.

## Submission Process

1. Submit your project through this Google Form:
   [Project Submission Form](https://forms.gle/nr6DZAX3nv6r7bru9)

2. The form will require:
   - Your project zip file (named `username_YYYYMMDD.zip`)
   - Your video documentation
   - Any additional notes or comments about your implementation

Make sure to test the zip file and video before submitting to ensure they are complete and working as expected.

