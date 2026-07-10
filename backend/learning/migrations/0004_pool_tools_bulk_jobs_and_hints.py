import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


PALETTE = ['emerald', 'blue', 'violet', 'rose', 'orange', 'teal', 'indigo']
OLD_FIXED_COLORS = ['rose', 'teal', 'orange', 'blue', 'violet']


def stabilize_pool_accents(apps, schema_editor):
    """Freeze the colors displayed by v1.5.6 instead of recoloring by index later.

    The old React UI used the current ``-updated_at`` position: c0 was the user's
    interface accent and c1..c5 were fixed colors. Creating a pool reordered the
    list and therefore changed every visible color. This migration captures that
    last pre-upgrade appearance once and stores it on each pool.
    """
    Pool = apps.get_model('learning', 'Pool')
    UserProfile = apps.get_model('learning', 'UserProfile')
    user_ids = Pool.objects.values_list('user_id', flat=True).distinct()
    for user_id in user_ids:
        profile_accent = (
            UserProfile.objects.filter(user_id=user_id)
            .values_list('accent_color', flat=True)
            .first()
        )
        first_color = profile_accent if profile_accent in PALETTE else 'violet'
        old_display_palette = [first_color, *OLD_FIXED_COLORS]
        pools = list(Pool.objects.filter(user_id=user_id).order_by('-updated_at', '-id'))
        for index, pool in enumerate(pools):
            color = old_display_palette[index % len(old_display_palette)]
            if pool.accent != color:
                Pool.objects.filter(pk=pool.pk).update(accent=color)


class Migration(migrations.Migration):
    dependencies = [
        ('learning', '0003_userprofile_accent_color_and_system_theme'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='pool',
            name='accent',
            field=models.CharField(
                choices=[
                    ('emerald', 'Emerald'), ('blue', 'Blue'), ('violet', 'Violet'),
                    ('rose', 'Rose'), ('orange', 'Orange'), ('teal', 'Teal'),
                    ('indigo', 'Indigo'),
                ],
                default='emerald', max_length=24,
            ),
        ),
        migrations.RunPython(stabilize_pool_accents, migrations.RunPython.noop),
        migrations.AddField(
            model_name='reviewlog',
            name='hint_revealed_letters',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='reviewlog',
            name='hint_total_letters',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='BulkGenerationJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('pool_name', models.CharField(max_length=120)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Running'), ('completed', 'Completed'), ('completed_with_errors', 'Completed with errors'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], default='queued', max_length=32)),
                ('batch_size', models.PositiveSmallIntegerField(default=20, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(200)])),
                ('max_rounds', models.PositiveSmallIntegerField(default=5, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10)])),
                ('current_round', models.PositiveSmallIntegerField(default=0)),
                ('total_count', models.PositiveIntegerField(default=0)),
                ('created_count', models.PositiveIntegerField(default=0)),
                ('failed_count', models.PositiveIntegerField(default=0)),
                ('skipped_count', models.PositiveIntegerField(default=0)),
                ('active_item_ids', models.JSONField(blank=True, default=list)),
                ('error', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('pool', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bulk_generation_jobs', to='learning.pool')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bulk_generation_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='BulkGenerationItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField()),
                ('term', models.CharField(max_length=250)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('succeeded', 'Succeeded'), ('failed', 'Failed'), ('skipped', 'Skipped')], default='pending', max_length=16)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('card', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bulk_generation_items', to='learning.flashcard')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='learning.bulkgenerationjob')),
            ],
            options={'ordering': ['position']},
        ),
        migrations.AddConstraint(
            model_name='bulkgenerationitem',
            constraint=models.UniqueConstraint(fields=('job', 'position'), name='unique_bulk_item_position'),
        ),
    ]
