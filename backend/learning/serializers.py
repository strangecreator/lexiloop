import re

from django.contrib.auth.models import User
from rest_framework import serializers

from learning.models import IMAGE_ANIMATIONS, BulkGenerationItem, BulkGenerationJob, CardSchedule, Flashcard, Pool, UserProfile
from learning.services.english import InvalidEnglishTerm, validate_english_term
from learning.services.security import encrypt_secret
from learning.services.model_catalog import TOKEN_PROVIDERS, is_supported_model, token_provider_for


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def create(self, validated_data):
        user = User.objects.create_user(username=validated_data['username'], password=validated_data['password'])
        UserProfile.objects.create(user=user)
        return user


class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CardSchedule
        fields = ['state', 'due_at', 'interval_days', 'ease_factor', 'step_index', 'repetitions', 'lapses', 'last_reviewed_at']


class FlashcardSerializer(serializers.ModelSerializer):
    schedule = ScheduleSerializer(read_only=True)
    pool_name = serializers.CharField(source='pool.name', read_only=True)
    has_image = serializers.SerializerMethodField()
    # Opaque cache key: changes whenever a new image file is stored.
    image_key = serializers.SerializerMethodField()

    class Meta:
        model = Flashcard
        fields = [
            'id', 'pool', 'pool_name', 'term', 'normalized_term', 'part_of_speech', 'ipa',
            'short_definition', 'definition', 'examples', 'forms', 'synonyms', 'antonyms',
            'collocations', 'usage_notes', 'aliases', 'source_payload', 'suspended',
            'has_image', 'image_key', 'schedule', 'created_at', 'updated_at',
        ]
        read_only_fields = ['normalized_term', 'created_at', 'updated_at']

    def get_has_image(self, obj):
        return bool(obj.image)

    def get_image_key(self, obj):
        return obj.image.name if obj.image else ''

    def validate_pool(self, value):
        request = self.context['request']
        if value.user_id != request.user.id:
            raise serializers.ValidationError('Pool does not belong to this user.')
        return value

    def validate(self, attrs):
        term = attrs.get('term', getattr(self.instance, 'term', '')).strip()
        if not term:
            raise serializers.ValidationError({'term': 'Term is required.'})
        try:
            validated_term = validate_english_term(term)
        except InvalidEnglishTerm as exc:
            raise serializers.ValidationError({'term': str(exc)}) from exc
        definition = attrs.get('definition', getattr(self.instance, 'definition', '')).strip()
        short = attrs.get('short_definition', getattr(self.instance, 'short_definition', '')).strip()
        if not definition:
            raise serializers.ValidationError({'definition': 'Definition is required.'})
        attrs['term'] = validated_term.normalized
        attrs['definition'] = definition
        attrs['short_definition'] = short or definition[:180]
        identity = validated_term.normalized.casefold()
        existing = getattr(self.instance, 'normalized_term', '')
        # A sense-restricted card (normalized_term like "bark (verb)") keeps
        # its POS identity suffix when its fields are edited in the Library.
        match = re.fullmatch(r'.*? \((?P<pos>[a-z/]+)\)', existing or '')
        if match:
            identity = f"{identity} ({match.group('pos')})"
        attrs['normalized_term'] = identity
        return attrs


class PoolSerializer(serializers.ModelSerializer):
    card_count = serializers.IntegerField(read_only=True, default=0)
    due_count = serializers.SerializerMethodField()

    class Meta:
        model = Pool
        fields = ['id', 'name', 'description', 'accent', 'archived', 'card_count', 'due_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_due_count(self, obj):
        # Annotated by PoolViewSet with one query. The remaining-new allowance is
        # per user and represents the queue available when this pool is selected.
        non_new = int(getattr(obj, 'due_non_new_count', 0) or 0)
        new = int(getattr(obj, 'due_new_count', 0) or 0)
        remaining = int(self.context.get('remaining_new_slots', 0) or 0)
        return non_new + min(new, remaining)

    def validate_name(self, value):
        request = self.context['request']
        qs = Pool.objects.filter(user=request.user, name__iexact=value.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A pool with this name already exists.')
        return value.strip()


class BulkGenerationJobSerializer(serializers.ModelSerializer):
    processed_count = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    failed_terms = serializers.SerializerMethodField()

    class Meta:
        model = BulkGenerationJob
        fields = [
            'id', 'pool', 'pool_name', 'status', 'batch_size', 'max_rounds',
            'current_round', 'total_count', 'created_count', 'failed_count',
            'skipped_count', 'processed_count', 'progress', 'failed_terms',
            'error', 'started_at', 'finished_at', 'heartbeat_at', 'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    @staticmethod
    def get_processed_count(obj):
        resolved = obj.created_count + obj.skipped_count
        if obj.status in {
            BulkGenerationJob.Status.COMPLETED,
            BulkGenerationJob.Status.COMPLETED_WITH_ERRORS,
            BulkGenerationJob.Status.FAILED,
            BulkGenerationJob.Status.CANCELLED,
        }:
            resolved += obj.failed_count
        return min(obj.total_count, resolved)

    @classmethod
    def get_progress(cls, obj):
        if not obj.total_count:
            return 100.0 if obj.status in {
                BulkGenerationJob.Status.COMPLETED,
                BulkGenerationJob.Status.COMPLETED_WITH_ERRORS,
            } else 0.0
        return round(100 * cls.get_processed_count(obj) / obj.total_count, 1)

    @staticmethod
    def get_failed_terms(obj):
        if obj.status not in {
            BulkGenerationJob.Status.COMPLETED_WITH_ERRORS,
            BulkGenerationJob.Status.FAILED,
            BulkGenerationJob.Status.CANCELLED,
        }:
            return []
        return list(obj.items.filter(status=BulkGenerationItem.Status.FAILED).values('term', 'error', 'attempts'))


class ProfileSerializer(serializers.ModelSerializer):
    # {'openai': 'sk-…'} saves or replaces one key per provider; an empty string
    # removes the stored key. Providers not mentioned are left untouched.
    provider_tokens = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        write_only=True, required=False,
    )
    token_status = serializers.SerializerMethodField()
    has_generation_token = serializers.SerializerMethodField()
    has_judge_token = serializers.SerializerMethodField()
    has_image_token = serializers.SerializerMethodField()
    has_sentence_token = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            'theme', 'accent_color', 'study_directions', 'generation_model', 'has_generation_token',
            'judge_model', 'has_judge_token', 'image_model', 'has_image_token', 'show_card_images',
            'show_images_term_to_definition', 'show_images_definition_to_term', 'image_animations',
            'image_animation_durations', 'image_prefetch_count',
            'provider_tokens', 'token_status',
            'judge_acceptance_score',
            'sentence_judge_model', 'has_sentence_token', 'sentence_acceptance_score',
            'daily_new_limit', 'learning_steps_minutes', 'relearning_steps_minutes',
            'graduating_interval_days', 'easy_interval_days', 'easy_bonus', 'hard_multiplier',
            'lapse_multiplier', 'minimum_ease',
            'term_to_definition_easy_seconds', 'term_to_definition_good_seconds',
            'definition_to_term_easy_seconds', 'definition_to_term_good_seconds',
            'term_to_sentence_easy_seconds', 'term_to_sentence_good_seconds',
        ]

    @staticmethod
    def _has_provider_token(obj, model_id):
        provider = token_provider_for(model_id)
        return bool((obj.provider_tokens_encrypted or {}).get(provider))

    def get_token_status(self, obj):
        saved = obj.provider_tokens_encrypted or {}
        return {provider: bool(saved.get(provider)) for provider in TOKEN_PROVIDERS}

    def get_has_generation_token(self, obj):
        return self._has_provider_token(obj, obj.generation_model)

    def get_has_judge_token(self, obj):
        return self._has_provider_token(obj, obj.judge_model)

    def get_has_image_token(self, obj):
        return self._has_provider_token(obj, obj.image_model or obj.generation_model)

    def get_has_sentence_token(self, obj):
        return self._has_provider_token(obj, obj.sentence_judge_model or obj.judge_model)

    def validate_provider_tokens(self, value):
        unknown = sorted(set(value) - set(TOKEN_PROVIDERS))
        if unknown:
            raise serializers.ValidationError(f"Unknown provider: {', '.join(unknown)}.")
        return value

    def validate_generation_model(self, value):
        if not is_supported_model(value):
            raise serializers.ValidationError('Choose one of the public models offered by LexiLoop.')
        return value

    def validate_judge_model(self, value):
        if not is_supported_model(value):
            raise serializers.ValidationError('Choose one of the public models offered by LexiLoop.')
        return value

    def validate_image_model(self, value):
        # Empty string means "use the generation model".
        if value and not is_supported_model(value):
            raise serializers.ValidationError('Choose one of the public models offered by LexiLoop.')
        return value

    def validate_study_directions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Provide a list of task types.')
        allowed = ('definition_to_term', 'term_to_definition', 'term_to_sentence')
        unknown = sorted(set(value) - set(allowed))
        if unknown:
            raise serializers.ValidationError(f"Unknown task type: {', '.join(unknown)}.")
        ordered = [direction for direction in allowed if direction in value]
        if not ordered:
            raise serializers.ValidationError('Enable at least one task type.')
        return ordered

    def validate_sentence_judge_model(self, value):
        # Empty string means "use the definition judge model".
        if value and not is_supported_model(value):
            raise serializers.ValidationError('Choose one of the public models offered by LexiLoop.')
        return value

    def validate_image_animations(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Provide a list of animation names.')
        unknown = sorted(set(value) - set(IMAGE_ANIMATIONS))
        if unknown:
            raise serializers.ValidationError(f"Unknown animation: {', '.join(unknown)}.")
        # Preserve the canonical order and drop duplicates.
        return [name for name in IMAGE_ANIMATIONS if name in value]

    def validate_image_animation_durations(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Provide a mapping of animation name to seconds.')
        unknown = sorted(set(value) - set(IMAGE_ANIMATIONS))
        if unknown:
            raise serializers.ValidationError(f"Unknown animation: {', '.join(unknown)}.")
        cleaned = {}
        for name, seconds in value.items():
            try:
                seconds = round(float(seconds), 1)
            except (TypeError, ValueError):
                raise serializers.ValidationError(f'{name}: the duration must be a number of seconds.')
            if not 0.5 <= seconds <= 30:
                raise serializers.ValidationError(f'{name}: the duration must be between 0.5 and 30 seconds.')
            cleaned[name] = seconds
        return cleaned

    def validate_learning_steps_minutes(self, value):
        return self._validate_steps(value)

    def validate_relearning_steps_minutes(self, value):
        return self._validate_steps(value)

    @staticmethod
    def _validate_steps(value):
        if not isinstance(value, list) or not value or len(value) > 10:
            raise serializers.ValidationError('Provide 1–10 positive minute values.')
        try:
            values = [int(x) for x in value]
        except (TypeError, ValueError):
            raise serializers.ValidationError('All steps must be integers.')
        if any(x < 1 or x > 525600 for x in values):
            raise serializers.ValidationError('Steps must be between 1 and 525600 minutes.')
        return values

    def validate(self, attrs):
        attrs = super().validate(attrs)
        pairs = (
            ('term_to_definition_easy_seconds', 'term_to_definition_good_seconds', 'Word → definition'),
            ('definition_to_term_easy_seconds', 'definition_to_term_good_seconds', 'Definition → word'),
            ('term_to_sentence_easy_seconds', 'term_to_sentence_good_seconds', 'Word → sentence'),
        )
        for easy_field, good_field, label in pairs:
            easy = attrs.get(easy_field, getattr(self.instance, easy_field, None))
            good = attrs.get(good_field, getattr(self.instance, good_field, None))
            if easy is not None and good is not None and int(easy) >= int(good):
                raise serializers.ValidationError({good_field: f'{label}: the Good threshold must be greater than the Easy threshold.'})
        return attrs

    def update(self, instance, validated_data):
        updates = validated_data.pop('provider_tokens', None)
        if updates:
            saved = dict(instance.provider_tokens_encrypted or {})
            for provider, token in updates.items():
                encrypted = encrypt_secret(token)
                if encrypted:
                    saved[provider] = encrypted
                else:
                    saved.pop(provider, None)
            instance.provider_tokens_encrypted = saved
        return super().update(instance, validated_data)
