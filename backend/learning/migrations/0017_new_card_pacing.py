import django.core.validators
from django.db import migrations, models

# The three-way choice was a special case of a continuous control, so it becomes
# one: pacing is the mean position of a new card in the day's queue.
ORDER_TO_PACING = {
    'after_reviews': 0.0,
    'mixed': 0.5,
    'before_reviews': 1.0,
}
PACING_TO_ORDER = {value: key for key, value in ORDER_TO_PACING.items()}


def carry_order_forward(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    for order, pacing in ORDER_TO_PACING.items():
        UserProfile.objects.filter(new_card_order=order).update(new_card_pacing=pacing)


def carry_order_back(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    for pacing, order in PACING_TO_ORDER.items():
        UserProfile.objects.filter(new_card_pacing=pacing).update(new_card_order=order)
    # Anything set between the three old stops is closest to an even mix.
    UserProfile.objects.exclude(new_card_pacing__in=list(PACING_TO_ORDER)).update(new_card_order='mixed')


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0016_provider_check_jobs'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='new_card_pacing',
            field=models.FloatField(
                default=0.5,
                validators=[
                    django.core.validators.MinValueValidator(0.0),
                    django.core.validators.MaxValueValidator(1.0),
                ],
            ),
        ),
        migrations.RunPython(carry_order_forward, carry_order_back),
        migrations.RemoveField(
            model_name='userprofile',
            name='new_card_order',
        ),
    ]
