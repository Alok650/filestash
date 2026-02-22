from rest_framework import serializers
from .models import File


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
