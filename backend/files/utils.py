import hashlib


def compute_sha256(file_obj) -> str:
    """Compute SHA-256 hash of a Django UploadedFile using 8 KB chunks.

    Returns the hex digest string (64 lowercase hex chars).
    Resets the file pointer to 0 after reading so the file can still be
    saved to disk by the caller.
    """
    h = hashlib.sha256()
    for chunk in file_obj.chunks(chunk_size=8192):
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()
