from rest_framework import serializers

from .constants import DEFAULT_STORAGE_QUOTA_BYTES
from .models import ApiKey, File


class FileSerializer(serializers.ModelSerializer):
    deduplicated = serializers.SerializerMethodField()

    def get_deduplicated(self, obj):
        return self.context.get('deduplicated', False)

    class Meta:
        model = File
        fields = [
            'id', 'file', 'original_filename', 'file_type',
            'size', 'uploaded_at', 'sha256_hash', 'deduplicated',
        ]
        read_only_fields = ['id', 'file', 'file_type', 'size', 'uploaded_at', 'sha256_hash']


class ApiKeyCreateInputSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=100)
    storage_quota_bytes = serializers.IntegerField(
        min_value=1,
        default=DEFAULT_STORAGE_QUOTA_BYTES,
    )


class ApiKeyCreateSerializer(serializers.ModelSerializer):
    """Response serializer for POST /api/keys/ — includes the raw token field."""

    key = serializers.CharField()

    class Meta:
        model = ApiKey
        fields = ['id', 'key', 'label', 'is_active', 'storage_quota_bytes', 'created_at']


class ApiKeyDetailSerializer(serializers.ModelSerializer):
    """Response serializer for GET /api/keys/me/ — no key field, adds storage_used_bytes."""

    storage_used_bytes = serializers.SerializerMethodField()

    def get_storage_used_bytes(self, obj):
        return self.context.get('storage_used_bytes', 0)

    class Meta:
        model = ApiKey
        fields = ['id', 'label', 'is_active', 'storage_quota_bytes', 'created_at', 'storage_used_bytes']
