from rest_framework import serializers
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
        read_only_fields = ['id', 'uploaded_at', 'sha256_hash']


class ApiKeyCreateSerializer(serializers.ModelSerializer):
    """Used in POST /api/keys/ response — includes the raw token field."""

    key = serializers.CharField()  # raw token supplied by the view

    class Meta:
        model = ApiKey
        fields = ['id', 'key', 'label', 'is_active', 'storage_quota_bytes', 'created_at']


class ApiKeyDetailSerializer(serializers.ModelSerializer):
    """Used in GET /api/keys/me/ response — no key field, adds storage_used_bytes."""

    storage_used_bytes = serializers.SerializerMethodField()

    def get_storage_used_bytes(self, obj):
        return self.context.get('storage_used_bytes', 0)

    class Meta:
        model = ApiKey
        fields = ['id', 'label', 'is_active', 'storage_quota_bytes', 'created_at', 'storage_used_bytes']
