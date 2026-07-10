from django.urls import include, path
from rest_framework.routers import DefaultRouter

from learning.views import (
    AnalyticsView, BulkGenerateView, BulkJobCancelView, BulkJobDetailView, FlashcardViewSet, GenerateView, JudgeView, LoginView,
    LogoutView, MeView, ModelsView, NextCardView, NormalizeTermsView, OverviewView, PoolViewSet, RegisterView,
    PronunciationView, ReviewView, SettingsView,
)

router = DefaultRouter()
router.register('pools', PoolViewSet, basename='pool')
router.register('flashcards', FlashcardViewSet, basename='flashcard')

urlpatterns = [
    path('auth/register/', RegisterView.as_view()),
    path('auth/login/', LoginView.as_view()),
    path('auth/logout/', LogoutView.as_view()),
    path('auth/me/', MeView.as_view()),
    path('settings/', SettingsView.as_view()),
    path('models/', ModelsView.as_view()),
    path('generate/', GenerateView.as_view()),
    path('generate/normalize/', NormalizeTermsView.as_view()),
    path('generate/bulk/', BulkGenerateView.as_view()),
    path('generate/bulk/jobs/<uuid:job_id>/', BulkJobDetailView.as_view()),
    path('generate/bulk/jobs/<uuid:job_id>/cancel/', BulkJobCancelView.as_view()),
    path('study/next/', NextCardView.as_view()),
    path('study/<int:card_id>/judge/', JudgeView.as_view()),
    path('study/<int:card_id>/review/', ReviewView.as_view()),
    path('pronunciation/', PronunciationView.as_view()),
    path('overview/', OverviewView.as_view()),
    path('analytics/', AnalyticsView.as_view()),
    path('', include(router.urls)),
]
