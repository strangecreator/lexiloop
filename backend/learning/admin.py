from django.contrib import admin

from learning.models import (
    BulkGenerationItem,
    BulkGenerationJob,
    CardSchedule,
    Flashcard,
    LlmUsage,
    Pool,
    ReviewLog,
    RouterAdapter,
    UserProfile,
)


@admin.register(Pool)
class PoolAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'accent', 'archived', 'updated_at')
    search_fields = ('name', 'user__username')
    list_filter = ('accent', 'archived')


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = ('term', 'pool', 'part_of_speech', 'suspended', 'updated_at')
    search_fields = ('term', 'definition')
    list_filter = ('pool', 'part_of_speech', 'suspended')


@admin.register(BulkGenerationJob)
class BulkGenerationJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'pool_name', 'status', 'created_count', 'failed_count', 'total_count', 'created_at')
    search_fields = ('id', 'user__username', 'pool_name')
    list_filter = ('status', 'created_at')
    readonly_fields = ('created_at', 'updated_at', 'started_at', 'finished_at', 'heartbeat_at')


@admin.register(BulkGenerationItem)
class BulkGenerationItemAdmin(admin.ModelAdmin):
    list_display = ('term', 'job', 'status', 'attempts', 'card', 'updated_at')
    search_fields = ('term', 'job__id', 'error')
    list_filter = ('status',)


@admin.register(RouterAdapter)
class RouterAdapterAdmin(admin.ModelAdmin):
    """Read-only history of the AI-authored provider connection modules.

    Activation goes through the API so a revision is always recompiled and
    screened first; editing source here would bypass that.
    """

    list_display = ('provider', 'revision', 'status', 'author_model', 'activated_at', 'created_at')
    list_filter = ('provider', 'status')
    search_fields = ('provider', 'author_model', 'notes')
    readonly_fields = tuple(field.name for field in RouterAdapter._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(UserProfile)
admin.site.register(CardSchedule)
admin.site.register(ReviewLog)
admin.site.register(LlmUsage)
