from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('learning', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='term_to_definition_easy_seconds',
            field=models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(600)]),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='term_to_definition_good_seconds',
            field=models.PositiveSmallIntegerField(default=35, validators=[MinValueValidator(2), MaxValueValidator(900)]),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='definition_to_term_easy_seconds',
            field=models.PositiveSmallIntegerField(default=6, validators=[MinValueValidator(1), MaxValueValidator(600)]),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='definition_to_term_good_seconds',
            field=models.PositiveSmallIntegerField(default=18, validators=[MinValueValidator(2), MaxValueValidator(900)]),
        ),
    ]
