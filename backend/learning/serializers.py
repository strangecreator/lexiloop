from django.contrib.auth.models import User
from rest_framework import serializers

from learning.models import BulkGenerationItem, BulkGenerationJob, CardSchedule, Flashcard, Pool, UserProfile
from learning.services.english import InvalidEnglishTerm, validate_english_term
from learning.services.security import encrypt_secret
from learning.services.model_catalog import is_supported_model


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

    class Meta:
        model = Flashcard
        fields = [
            'id', 'pool', 'pool_name', 'term', 'normalized_term', 'part_of_speech', 'ipa',
            'short_definition', 'definition', 'examples', 'forms', 'synonyms', 'antonyms',
            'collocations', 'usage_notes', 'aliases', 'source_payload', 'suspended',
            'schedule', 'created_at', 'updated_at',
        ]
        read_only_fields = ['normalized_term', 'created_at', 'updated_at']

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
        attrs['normalized_term'] = validated_term.normalized.casefold()
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
    generation_token = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    judge_token = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    has_generation_token = serializers.SerializerMethodField()
    has_judge_token = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            'theme', 'accent_color', 'study_direction', 'generation_model', 'generation_token', 'has_generation_token',
            'judge_model', 'judge_token', 'has_judge_token', 'judge_acceptance_score', 'reveal_threshold',
            'daily_new_limit', 'learning_steps_minutes', 'relearning_steps_minutes',
            'graduating_interval_days', 'easy_interval_days', 'easy_bonus', 'hard_multiplier',
            'lapse_multiplier', 'minimum_ease',
            'term_to_definition_easy_seconds', 'term_to_definition_good_seconds',
            'definition_to_term_easy_seconds', 'definition_to_term_good_seconds',
        ]

    def get_has_generation_token(self, obj):
        return bool(obj.generation_token_encrypted)

    def get_has_judge_token(self, obj):
        return bool(obj.judge_token_encrypted)

    def validate_generation_model(self, value):
        if not is_supported_model(value):
            raise serializers.ValidationError('Choose one of the public models offered by LexiLoop.')
        return value

    def validate_judge_model(self, value):
        if not is_supported_model(value):
            raise serializers.ValidationError('Choose one of the public models offered by LexiLoop.')
        return value

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
        )
        for easy_field, good_field, label in pairs:
            easy = attrs.get(easy_field, getattr(self.instance, easy_field, None))
            good = attrs.get(good_field, getattr(self.instance, good_field, None))
            if easy is not None and good is not None and int(easy) >= int(good):
                raise serializers.ValidationError({good_field: f'{label}: the Good threshold must be greater than the Easy threshold.'})
        return attrs

    def update(self, instance, validated_data):
        if 'generation_token' in validated_data:
            instance.generation_token_encrypted = encrypt_secret(validated_data.pop('generation_token'))
        if 'judge_token' in validated_data:
            instance.judge_token_encrypted = encrypt_secret(validated_data.pop('judge_token'))
        return super().update(instance, validated_data)
