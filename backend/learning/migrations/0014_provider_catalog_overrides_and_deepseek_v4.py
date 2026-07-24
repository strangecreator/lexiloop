from django.db import migrations, models


LEGACY_REPLACEMENTS = {
    'external:deepseek-chat': 'deepseek:deepseek-v4-flash',
    'external:deepseek-reasoner': 'deepseek:deepseek-v4-pro',
    'external:xiaomi-mimo': 'xiaomi:mimo-v2-flash',
}


def migrate_model_ids(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    for profile in UserProfile.objects.all().iterator():
        changed = []
        for field in ('generation_model', 'judge_model', 'image_model', 'sentence_judge_model'):
            old = getattr(profile, field)
            replacement = LEGACY_REPLACEMENTS.get(old)
            if replacement:
                setattr(profile, field, replacement)
                changed.append(field)
        if changed:
            profile.save(update_fields=changed)


def restore_legacy_model_ids(apps, schema_editor):
    reverse = {value: key for key, value in LEGACY_REPLACEMENTS.items()}
    UserProfile = apps.get_model('learning', 'UserProfile')
    for profile in UserProfile.objects.all().iterator():
        changed = []
        for field in ('generation_model', 'judge_model', 'image_model', 'sentence_judge_model'):
            old = getattr(profile, field)
            replacement = reverse.get(old)
            if replacement:
                setattr(profile, field, replacement)
                changed.append(field)
        if changed:
            profile.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [('learning', '0013_remove_userprofile_reveal_threshold_and_more')]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='provider_catalog_overrides',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='generation_model',
            field=models.CharField(default='deepseek:deepseek-v4-flash', max_length=200),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='judge_model',
            field=models.CharField(default='deepseek:deepseek-v4-flash', max_length=200),
        ),
        migrations.AlterField(
            model_name='llmusage',
            name='operation',
            field=models.CharField(
                choices=[
                    ('generation', 'Generation'),
                    ('bulk_generation', 'Bulk generation'),
                    ('judging', 'Judging'),
                    ('sentence_judging', 'Sentence judging'),
                    ('image', 'Image lookup'),
                    ('provider_update', 'Provider update'),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(migrate_model_ids, restore_legacy_model_ids),
    ]
