from django.db import migrations


DEFAULT_MODEL = 'external:deepseek-chat'
SUPPORTED_MODELS = (
    'external:deepseek-chat',
    'external:deepseek-reasoner',
    'external:xiaomi-mimo',
    'openrouter:openai/gpt-5.2',
    'openrouter:anthropic/claude-sonnet-4.6',
    'openrouter:google/gemini-3.1-pro-preview',
    'openrouter:google/gemini-3-flash-preview',
    'openrouter:moonshotai/kimi-k2.6',
    'openrouter:deepseek/deepseek-v3.2',
    'openrouter:xiaomi/mimo-v2-flash',
)


def replace_unsupported_models(apps, schema_editor):
    UserProfile = apps.get_model('learning', 'UserProfile')
    UserProfile.objects.exclude(generation_model__in=SUPPORTED_MODELS).update(
        generation_model=DEFAULT_MODEL, generation_token_encrypted=''
    )
    UserProfile.objects.exclude(judge_model__in=SUPPORTED_MODELS).update(
        judge_model=DEFAULT_MODEL, judge_token_encrypted=''
    )


class Migration(migrations.Migration):
    dependencies = [('learning', '0004_pool_tools_bulk_jobs_and_hints')]

    operations = [migrations.RunPython(replace_unsupported_models, migrations.RunPython.noop)]
