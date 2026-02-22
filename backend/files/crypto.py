"""
Cryptographic utilities for the files app.

Kept separate from models.py so that authentication, repository, and any
future middleware can all import these helpers without creating circular
dependencies through the model layer.
"""

import hashlib


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of *raw_key* for safe database storage.

    The raw key is never persisted.  The digest is 64 lowercase hex characters,
    fitting the existing ApiKey.key CharField(max_length=64).  Callers must
    return the original *raw_key* to the API consumer exactly once (at creation
    time); it cannot be recovered from the stored hash.
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()
