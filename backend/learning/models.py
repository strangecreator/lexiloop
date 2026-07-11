from __future__ import annotations

import uuid

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def default_learning_steps():
    return [1, 10]


def default_relearning_steps():
    return [10]


# Names must match the CSS reveal animations in the frontend.
IMAGE_ANIMATIONS = ('droplets', 'mist', 'ripple', 'drift')


def default_image_animations():
    return list(IMAGE_ANIMATIONS)


class UserProfile(models.Model):
    class Theme(models.TextChoices):
        DARK = 'dark', 'Dark'
        LIGHT = 'light', 'Light'
        SYSTEM = 'system', 'System'

    class AccentColor(models.TextChoices):
        VIOLET = 'violet', 'Violet'
        INDIGO = 'indigo', 'Indigo'
        BLUE = 'blue', 'Blue'
        TEAL = 'teal', 'Teal'
        EMERALD = 'emerald', 'Emerald'
        ROSE = 'rose', 'Rose'
        ORANGE = 'orange', 'Orange'

    class Direction(models.TextChoices):
        MIXED = 'mixed', 'Mixed'
        TERM_TO_DEFINITION = 'term_to_definition', 'Word → definition'
        DEFINITION_TO_TERM = 'definition_to_term', 'Definition → word'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    theme = models.CharField(max_length=16, choices=Theme.choices, default=Theme.SYSTEM)
    accent_color = models.CharField(max_length=16, choices=AccentColor.choices, default=AccentColor.EMERALD)
    study_direction = models.CharField(max_length=32, choices=Direction.choices, default=Direction.MIXED)
    generation_model = models.CharField(max_length=200, default='external:deepseek-chat')
    judge_model = models.CharField(max_length=200, default='external:deepseek-chat')
    # Empty string means "use the generation model" for image-lookup assistance.
    image_model = models.CharField(max_length=200, blank=True, default='')
    show_card_images = models.BooleanField(default=True)
    show_images_term_to_definition = models.BooleanField(default=True)
    show_images_definition_to_term = models.BooleanField(default=True)
    image_animations = models.JSONField(default=default_image_animations, blank=True)
    # Encrypted API keys keyed by token provider ('deepseek', 'openai', …), so a
    # saved key survives switching between models of the same provider.
    provider_tokens_encrypted = models.JSONField(default=dict, blank=True)
    judge_acceptance_score = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(7)])
    reveal_threshold = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(7)])
    daily_new_limit = models.PositiveIntegerField(default=20, validators=[MinValueValidator(0), MaxValueValidator(500)])
    learning_steps_minutes = models.JSONField(default=default_learning_steps)
    relearning_steps_minutes = models.JSONField(default=default_relearning_steps)
    graduating_interval_days = models.FloatField(default=1.0, validators=[MinValueValidator(0.01)])
    easy_interval_days = models.FloatField(default=4.0, validators=[MinValueValidator(0.01)])
    easy_bonus = models.FloatField(default=1.3, validators=[MinValueValidator(1.0)])
    hard_multiplier = models.FloatField(default=1.2, validators=[MinValueValidator(1.0)])
    lapse_multiplier = models.FloatField(default=0.5, validators=[MinValueValidator(0.01), MaxValueValidator(1.0)])
    minimum_ease = models.FloatField(default=1.3, validators=[MinValueValidator(1.0)])
    term_to_definition_easy_seconds = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(600)])
    term_to_definition_good_seconds = models.PositiveSmallIntegerField(default=35, validators=[MinValueValidator(2), MaxValueValidator(900)])
    definition_to_term_easy_seconds = models.PositiveSmallIntegerField(default=6, validators=[MinValueValidator(1), MaxValueValidator(600)])
    definition_to_term_good_seconds = models.PositiveSmallIntegerField(default=18, validators=[MinValueValidator(2), MaxValueValidator(900)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.username} settings'


class Pool(models.Model):
    class Accent(models.TextChoices):
        EMERALD = 'emerald', 'Emerald'
        BLUE = 'blue', 'Blue'
        VIOLET = 'violet', 'Violet'
        ROSE = 'rose', 'Rose'
        ORANGE = 'orange', 'Orange'
        TEAL = 'teal', 'Teal'
        INDIGO = 'indigo', 'Indigo'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pools')
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    accent = models.CharField(max_length=24, choices=Accent.choices, default=Accent.EMERALD)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='unique_pool_name_per_user')]

    def __str__(self):
        return self.name


class Flashcard(models.Model):
    pool = models.ForeignKey(Pool, on_delete=models.CASCADE, related_name='cards')
    term = models.CharField(max_length=250)
    normalized_term = models.CharField(max_length=250, blank=True)
    part_of_speech = models.CharField(max_length=80, blank=True)
    ipa = models.CharField(max_length=160, blank=True)
    short_definition = models.CharField(max_length=500)
    definition = models.TextField()
    examples = models.JSONField(default=list, blank=True)
    forms = models.JSONField(default=dict, blank=True)
    synonyms = models.JSONField(default=list, blank=True)
    antonyms = models.JSONField(default=list, blank=True)
    collocations = models.JSONField(default=list, blank=True)
    usage_notes = models.TextField(blank=True)
    aliases = models.JSONField(default=list, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    image = models.FileField(upload_to='cards/', blank=True, default='')
    image_thumb = models.FileField(upload_to='cards/thumbs/', blank=True, default='')
    suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['term']
        constraints = [models.UniqueConstraint(fields=['pool', 'normalized_term'], name='unique_term_per_pool')]

    def save(self, *args, **kwargs):
        if not self.normalized_term:
            self.normalized_term = ' '.join(self.term.lower().strip().split())
        super().save(*args, **kwargs)
        CardSchedule.objects.get_or_create(card=self)

    def __str__(self):
        return self.term


class CardSchedule(models.Model):
    class State(models.TextChoices):
        NEW = 'new', 'New'
        LEARNING = 'learning', 'Learning'
        REVIEW = 'review', 'Review'
        RELEARNING = 'relearning', 'Relearning'
        SUSPENDED = 'suspended', 'Suspended'

    card = models.OneToOneField(Flashcard, on_delete=models.CASCADE, related_name='schedule')
    state = models.CharField(max_length=16, choices=State.choices, default=State.NEW)
    due_at = models.DateTimeField(default=timezone.now)
    interval_days = models.FloatField(default=0.0)
    ease_factor = models.FloatField(default=2.5)
    step_index = models.PositiveSmallIntegerField(default=0)
    repetitions = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_at']


class ReviewLog(models.Model):
    class AccentColor(models.TextChoices):
        VIOLET = 'violet', 'Violet'
        INDIGO = 'indigo', 'Indigo'
        BLUE = 'blue', 'Blue'
        TEAL = 'teal', 'Teal'
        EMERALD = 'emerald', 'Emerald'
        ROSE = 'rose', 'Rose'
        ORANGE = 'orange', 'Orange'

    class Direction(models.TextChoices):
        TERM_TO_DEFINITION = 'term_to_definition', 'Word → definition'
        DEFINITION_TO_TERM = 'definition_to_term', 'Definition → word'

    class Rating(models.IntegerChoices):
        AGAIN = 1, 'Again'
        HARD = 2, 'Hard'
        GOOD = 3, 'Good'
        EASY = 4, 'Easy'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='review_logs')
    card = models.ForeignKey(Flashcard, on_delete=models.CASCADE, related_name='review_logs')
    direction = models.CharField(max_length=32, choices=Direction.choices)
    answer = models.TextField(blank=True)
    judge_score = models.PositiveSmallIntegerField(null=True, blank=True)
    judge_verdict = models.CharField(max_length=40, blank=True)
    feedback = models.TextField(blank=True)
    accepted = models.BooleanField(default=False)
    rating = models.PositiveSmallIntegerField(choices=Rating.choices)
    previous_state = models.CharField(max_length=16)
    new_state = models.CharField(max_length=16)
    previous_interval_days = models.FloatField(default=0.0)
    new_interval_days = models.FloatField(default=0.0)
    response_ms = models.PositiveIntegerField(default=0)
    hint_revealed_letters = models.PositiveSmallIntegerField(default=0)
    hint_total_letters = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class LlmUsage(models.Model):
    class Operation(models.TextChoices):
        GENERATION = 'generation', 'Generation'
        BULK_GENERATION = 'bulk_generation', 'Bulk generation'
        JUDGING = 'judging', 'Judging'
        IMAGE = 'image', 'Image lookup'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='llm_usage')
    pool = models.ForeignKey(Pool, on_delete=models.SET_NULL, null=True, blank=True, related_name='llm_usage')
    card = models.ForeignKey(Flashcard, on_delete=models.SET_NULL, null=True, blank=True, related_name='llm_usage')
    operation = models.CharField(max_length=32, choices=Operation.choices)
    model = models.CharField(max_length=250)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    total_price = models.DecimalField(max_digits=14, decimal_places=8, default=0)
    elapsed_time = models.FloatField(default=0.0)
    success = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    stats = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class BulkGenerationJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        COMPLETED_WITH_ERRORS = 'completed_with_errors', 'Completed with errors'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bulk_generation_jobs')
    pool = models.ForeignKey(Pool, on_delete=models.SET_NULL, null=True, blank=True, related_name='bulk_generation_jobs')
    pool_name = models.CharField(max_length=120)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED)
    batch_size = models.PositiveSmallIntegerField(default=20, validators=[MinValueValidator(1), MaxValueValidator(200)])
    max_rounds = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(10)])
    current_round = models.PositiveSmallIntegerField(default=0)
    total_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    active_item_ids = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class BulkGenerationItem(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    job = models.ForeignKey(BulkGenerationJob, on_delete=models.CASCADE, related_name='items')
    position = models.PositiveIntegerField()
    term = models.CharField(max_length=250)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    card = models.ForeignKey(Flashcard, on_delete=models.SET_NULL, null=True, blank=True, related_name='bulk_generation_items')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['job', 'position'], name='unique_bulk_item_position')]
