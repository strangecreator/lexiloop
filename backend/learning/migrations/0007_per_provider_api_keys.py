from django.db import migrations, models

# Static copy of the catalog's model → token-provider mapping at migration time.
# Both legacy roles default to DeepSeek models, so unknown ids fall back there.
MODEL_PROVIDERS = {
    'external:deepseek-chat': 'deepseek',
    'external:deepseek-reasoner': 'deepseek',
    'external:xiaomi-mimo': 'xiaomi',
    'openai:gpt-5.4-mini': 'openai',
    'openai:gpt-5.4-nano': 'openai',
    'openai:gpt-5-mini': 'openai',
    'openai:gpt-5-nano': 'openai',
}


def provider_for(model_id):
    if model_id in MODEL_PROVIDERS:
        return MODEL_PROVIDERS[model_id]
    if model_id.startswith('openrouter:'):
        return 'openrouter'
    if model_id.startswith('openai:'):
        return 'openai'
    return 'deepseek'


def move_tokens_forward(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    for profile in UserProfile.objects.exclude(generation_token_encrypted='', judge_token_encrypted='').iterator():
        tokens = {}
        # The generation key wins when both roles used the same provider: it is
        # the one exercised by bulk jobs, the higher-volume path.
        if profile.judge_token_encrypted:
            tokens[provider_for(profile.judge_model)] = profile.judge_token_encrypted
        if profile.generation_token_encrypted:
            tokens[provider_for(profile.generation_model)] = profile.generation_token_encrypted
        profile.provider_tokens_encrypted = tokens
        profile.save(update_fields=['provider_tokens_encrypted'])


def move_tokens_backward(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    for profile in UserProfile.objects.exclude(provider_tokens_encrypted={}).iterator():
        tokens = profile.provider_tokens_encrypted or {}
        profile.generation_token_encrypted = tokens.get(provider_for(profile.generation_model), '')
        profile.judge_token_encrypted = tokens.get(provider_for(profile.judge_model), '')
        profile.save(update_fields=['generation_token_encrypted', 'judge_token_encrypted'])


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0006_default_emerald_and_openai_catalog'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='provider_tokens_encrypted',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(move_tokens_forward, move_tokens_backward),
        migrations.RemoveField(model_name='userprofile', name='generation_token_encrypted'),
        migrations.RemoveField(model_name='userprofile', name='judge_token_encrypted'),
    ]
