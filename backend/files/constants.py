# Storage
ONE_GIB = 1_073_741_824
DEFAULT_STORAGE_QUOTA_BYTES = ONE_GIB

# MIME types that browsers can execute as active content.
BLOCKED_CONTENT_TYPES = frozenset({
    'text/html',
    'application/xhtml+xml',
    'image/svg+xml',
    'application/javascript',
    'text/javascript',
})

# Rate limiting
AUTHENTICATED_RATE_PER_SECOND = '10/second'
ANONYMOUS_RATE_PER_SECOND = '2/second'
AUTHENTICATED_RATE_PER_MINUTE = '300/minute'
ANONYMOUS_RATE_PER_MINUTE = '30/minute'

# Ordering
VALID_ORDERING_FIELDS = ['original_filename', 'size', 'uploaded_at']
