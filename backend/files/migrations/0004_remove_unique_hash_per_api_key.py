from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0003_add_unique_hash_per_api_key'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='file',
            name='unique_hash_per_api_key',
        ),
    ]
