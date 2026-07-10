from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import router
from django.conf import settings
from django.db import IntegrityError, close_old_connections, models, transaction
from django.db.models import Count, Q
from django.utils import timezone

from learning.exceptions import LlmResponseError
from learning.models import BulkGenerationItem, BulkGenerationJob, Flashcard, LlmUsage
from learning.services.llm import (
    GENERATION_SYSTEM_PROMPT,
    _parse_object,
    _token,
    _validate_generation,
    log_usage,
)


def refresh_job_counts(job_id) -> BulkGenerationJob:
    counts = BulkGenerationItem.objects.filter(job_id=job_id).aggregate(
        created=Count('id', filter=Q(status=BulkGenerationItem.Status.SUCCEEDED)),
        failed=Count('id', filter=Q(status=BulkGenerationItem.Status.FAILED)),
        skipped=Count('id', filter=Q(status=BulkGenerationItem.Status.SKIPPED)),
    )
    BulkGenerationJob.objects.filter(pk=job_id).update(
        created_count=counts['created'], failed_count=counts['failed'],
        skipped_count=counts['skipped'], heartbeat_at=timezone.now(),
    )
    return BulkGenerationJob.objects.get(pk=job_id)


def _persist_result(*, job_id, item_id: int, result: dict[str, Any], round_number: int) -> None:
    close_old_connections()
    with transaction.atomic():
        item = BulkGenerationItem.objects.select_for_update().select_related('job__pool', 'job__user').get(pk=item_id)
        if item.status in {BulkGenerationItem.Status.SUCCEEDED, BulkGenerationItem.Status.SKIPPED}:
            return
        job = item.job
        if job.status == BulkGenerationJob.Status.CANCELLED:
            return
        if not job.pool_id:
            item.status = BulkGenerationItem.Status.FAILED
            item.error = 'The destination pool no longer exists.'
            item.save(update_fields=['status', 'error', 'updated_at'])
            return
        try:
            if result.get('__error__'):
                error_type = str(result.get('__error_type__') or 'ProviderError')
                detail = str(result.get('__error__') or result.get('__traceback__') or 'Unknown provider error')
                raise LlmResponseError(f'{error_type}: {detail[:900]}')
            content = result.get('content')
            if not isinstance(content, str):
                raise LlmResponseError('The model response has no textual content.')
            data = _validate_generation(_parse_object(content), item.term)
            try:
                card = Flashcard.objects.create(pool=job.pool, **data)
            except IntegrityError:
                card = Flashcard.objects.filter(pool=job.pool, normalized_term=data['normalized_term']).first()
                item.card = card
                item.status = BulkGenerationItem.Status.SKIPPED
                item.error = 'The term already exists in the destination pool.'
                item.save(update_fields=['card', 'status', 'error', 'updated_at'])
                return
            item.card = card
            item.status = BulkGenerationItem.Status.SUCCEEDED
            item.error = ''
            item.save(update_fields=['card', 'status', 'error', 'updated_at'])
            log_usage(
                user=job.user, pool=job.pool, card=card,
                operation=LlmUsage.Operation.BULK_GENERATION,
                model=job.user.profile.generation_model, result=result,
            )
        except Exception as exc:
            item.status = BulkGenerationItem.Status.FAILED
            item.error = f'Round {round_number}: {type(exc).__name__}: {str(exc)[:1000]}'
            item.save(update_fields=['status', 'error', 'updated_at'])
            log_usage(
                user=job.user, pool=job.pool, card=None,
                operation=LlmUsage.Operation.BULK_GENERATION,
                model=job.user.profile.generation_model,
                result=result, error=item.error,
            )
    refresh_job_counts(job_id)


def _mark_missing(*, job_id, item_ids: list[int], round_number: int, error: str) -> None:
    close_old_connections()
    job = BulkGenerationJob.objects.select_related('user__profile', 'pool').get(pk=job_id)
    message = f'Round {round_number}: {error[:1000]}'
    for item in BulkGenerationItem.objects.filter(pk__in=item_ids, status=BulkGenerationItem.Status.RUNNING):
        item.status = BulkGenerationItem.Status.FAILED
        item.error = message
        item.save(update_fields=['status', 'error', 'updated_at'])
        log_usage(
            user=job.user, pool=job.pool, card=None,
            operation=LlmUsage.Operation.BULK_GENERATION,
            model=job.user.profile.generation_model, error=f'{item.term}: {message}',
        )
    refresh_job_counts(job_id)


def _drain_jsonl(path: Path, *, offset: int, job_id, item_ids: list[int], round_number: int) -> int:
    if not path.exists():
        return offset
    with path.open('r', encoding='utf-8') as handle:
        handle.seek(offset)
        while True:
            line = handle.readline()
            if not line:
                break
            try:
                data = json.loads(line)
                index = data.pop('index')
                if isinstance(index, int) and 0 <= index < len(item_ids):
                    _persist_result(job_id=job_id, item_id=item_ids[index], result=data, round_number=round_number)
            except Exception:
                # A partially-written final line is read again after the next flush.
                if not line.endswith('\n'):
                    handle.seek(offset)
                    return offset
            offset = handle.tell()
    return offset


async def _run_round(
    *, job_id, items: list[tuple[int, str]], round_number: int,
    model: str, token: str | None, batch_size: int,
) -> None:
    """Run one provider round without carrying lazy Django objects into asyncio."""
    item_ids = [item_id for item_id, _term in items]
    args_list = []
    for _item_id, term in items:
        messages = [
            {'role': 'system', 'content': GENERATION_SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps({'term': term}, ensure_ascii=False)},
        ]
        args_list.append({
            'model': model, 'token': token,
            'payload': {'messages': messages, 'temperature': 0.1},
            'attempts': settings.BULK_ITEM_ATTEMPTS,
            'backoff_seconds': settings.LLM_RETRY_BACKOFF_SECONDS,
            'errors_to_ignore_func': lambda exc: True,
            'verbose': True,
            'traceback_verbose': True,
        })

    job_dir = Path(settings.MEDIA_ROOT) / 'bulk_jobs' / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    result_file = job_dir / f'round-{round_number}.jsonl'
    offset = await asyncio.to_thread(
        _drain_jsonl, result_file, offset=0, job_id=job_id,
        item_ids=item_ids, round_number=round_number,
    )
    batch_task = asyncio.create_task(router.llm.post_batch(
        args_list=args_list,
        batch_size=batch_size,
        timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        save_to_file=str(result_file),
        override=True,
        only_new=True,
        verbose=True,
        traceback_verbose=True,
        skip_on_error=True,
        save_errors_to_file=True,
        session_timeout=settings.BULK_SESSION_TIMEOUT_SECONDS,
    ))
    batch_error = ''
    while not batch_task.done():
        await asyncio.sleep(0.35)
        offset = await asyncio.to_thread(
            _drain_jsonl, result_file, offset=offset, job_id=job_id,
            item_ids=item_ids, round_number=round_number,
        )
        await asyncio.to_thread(
            BulkGenerationJob.objects.filter(pk=job_id).update,
            heartbeat_at=timezone.now(),
        )
        status = await asyncio.to_thread(
            lambda: BulkGenerationJob.objects.values_list('status', flat=True).get(pk=job_id)
        )
        if status == BulkGenerationJob.Status.CANCELLED:
            batch_task.cancel()
            await asyncio.gather(batch_task, return_exceptions=True)
            return
    try:
        await batch_task
    except Exception as exc:
        batch_error = f'{type(exc).__name__}: {exc}'
    await asyncio.to_thread(
        _drain_jsonl, result_file, offset=offset, job_id=job_id,
        item_ids=item_ids, round_number=round_number,
    )
    await asyncio.to_thread(
        _mark_missing,
        job_id=job_id, item_ids=item_ids, round_number=round_number,
        error=batch_error or 'No valid response was returned for this item.',
    )


def process_bulk_job(job_id) -> None:
    close_old_connections()
    job = BulkGenerationJob.objects.select_related('user__profile', 'pool').get(pk=job_id)
    if not job.pool_id:
        BulkGenerationJob.objects.filter(pk=job.id).update(
            status=BulkGenerationJob.Status.FAILED,
            error='The destination pool no longer exists.',
            finished_at=timezone.now(), heartbeat_at=timezone.now(),
        )
        return

    # A stale worker may leave items marked RUNNING. Retry them in a fresh round;
    # using a new JSONL file avoids index mismatches with the interrupted round.
    job.items.filter(status=BulkGenerationItem.Status.RUNNING).update(
        status=BulkGenerationItem.Status.FAILED,
        error='The previous worker stopped before this result was committed.',
    )
    no_progress_rounds = 0
    start_round = max(1, job.current_round + 1 if job.current_round else 1)
    try:
        for round_number in range(start_round, job.max_rounds + 1):
            job.refresh_from_db()
            if job.status == BulkGenerationJob.Status.CANCELLED:
                return
            items = list(job.items.filter(
                status__in=[BulkGenerationItem.Status.PENDING, BulkGenerationItem.Status.FAILED]
            ).order_by('position'))
            if not items:
                break
            previous_created = job.created_count
            item_ids = [item.id for item in items]
            BulkGenerationItem.objects.filter(pk__in=item_ids).update(
                status=BulkGenerationItem.Status.RUNNING, error='', attempts=models.F('attempts') + 1,
            )
            BulkGenerationJob.objects.filter(pk=job.id).update(
                current_round=round_number, active_item_ids=item_ids,
                heartbeat_at=timezone.now(), error='',
            )
            job.current_round = round_number
            job.active_item_ids = item_ids
            profile = job.user.profile
            asyncio.run(_run_round(
                job_id=job.id,
                items=[(item.id, item.term) for item in items],
                round_number=round_number,
                model=profile.generation_model,
                token=_token(profile, LlmUsage.Operation.GENERATION),
                batch_size=job.batch_size,
            ))
            job = refresh_job_counts(job.id)
            resolved = job.created_count + job.skipped_count
            success_ratio = resolved / max(1, job.total_count)
            if success_ratio >= settings.BULK_TARGET_SUCCESS_RATIO:
                break
            if job.created_count == previous_created:
                no_progress_rounds += 1
            else:
                no_progress_rounds = 0
            if no_progress_rounds >= 2:
                break

        job = refresh_job_counts(job.id)
        if job.status == BulkGenerationJob.Status.CANCELLED:
            return
        remaining = job.items.exclude(status__in=[
            BulkGenerationItem.Status.SUCCEEDED, BulkGenerationItem.Status.SKIPPED,
        ]).count()
        status = BulkGenerationJob.Status.COMPLETED if remaining == 0 else BulkGenerationJob.Status.COMPLETED_WITH_ERRORS
        BulkGenerationJob.objects.filter(pk=job.id).update(
            status=status, finished_at=timezone.now(), heartbeat_at=timezone.now(),
            active_item_ids=[],
        )
    except Exception as exc:
        job = refresh_job_counts(job.id)
        message = f'{type(exc).__name__}: {str(exc)[:2000]}'
        BulkGenerationJob.objects.filter(pk=job.id).update(
            status=BulkGenerationJob.Status.FAILED, error=message,
            finished_at=timezone.now(), heartbeat_at=timezone.now(),
        )
        log_usage(
            user=job.user, pool=job.pool, card=None,
            operation=LlmUsage.Operation.BULK_GENERATION,
            model=job.user.profile.generation_model, error=message,
        )
