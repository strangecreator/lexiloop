from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('learning', '0002_userprofile_timing_thresholds'),
    ]

    operations = [
        migrations.AddField(
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
                default='violet',
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='theme',
            field=models.CharField(
                choices=[('dark', 'Dark'), ('light', 'Light'), ('system', 'System')],
                default='system',
                max_length=16,
            ),
        ),
    ]
