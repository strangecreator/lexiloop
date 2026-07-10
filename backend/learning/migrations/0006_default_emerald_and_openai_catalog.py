from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('learning', '0005_public_model_catalog')]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='accent_color',
            field=models.CharField(
                choices=[
                    ('violet', 'Violet'),
                    ('indigo', 'Indigo'),
                    ('blue', 'Blue'),
                    ('teal', 'Teal'),
                    ('emerald', 'Emerald'),
                    ('rose', 'Rose'),
                    ('orange', 'Orange'),
                ],
                default='emerald',
                max_length=16,
            ),
        ),
    ]
