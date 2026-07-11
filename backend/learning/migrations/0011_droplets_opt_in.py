from django.db import migrations

# The watercolor droplets animation became opt-in (and moved to the end of the
# canonical order). Profiles still carrying the old untouched default get the
# new default; customized selections are left alone.
OLD_DEFAULT = ['droplets', 'mist', 'ripple', 'drift']
NEW_DEFAULT = ['mist', 'ripple', 'drift']


def forwards(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    for profile in UserProfile.objects.all().iterator():
        if profile.image_animations == OLD_DEFAULT:
            profile.image_animations = NEW_DEFAULT
            profile.save(update_fields=['image_animations'])


def backwards(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    for profile in UserProfile.objects.all().iterator():
        if profile.image_animations == NEW_DEFAULT:
            profile.image_animations = OLD_DEFAULT
            profile.save(update_fields=['image_animations'])


class Migration(migrations.Migration):
    dependencies = [
        ('learning', '0010_userprofile_image_animation_durations_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
