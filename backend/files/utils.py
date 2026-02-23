import hashlib

def compute_sha256(file_obj) -> str:
    """Compute SHA-256 hash of a Django UploadedFile using 8 KB chunks."""
    h = hashlib.sha256()
    for chunk in file_obj.chunks(chunk_size=8192):
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()

def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of *raw_key* for safe database storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
