from __future__ import annotations

import os
import time
import json
import typing as tp
from dataclasses import dataclass
from urllib.parse import urlparse

# aiohttp & related imports
import asyncio
import aiohttp

# local imports
import tools
import router


__all__ = [
    "PoolProcessorConfig",
    "run_once",
    "run_forever",
    "main",
]


PRODUCER_PREFIX: tp.Final = "router:delayed:producer:"
CONSUMER_PREFIX: tp.Final = "router:delayed:consumer:"
PROCESSING_PREFIX: tp.Final = "router:delayed:processing:"
PROCESSING_INIT_LOCK: tp.Final = "router:delayed:processing:init_lock"


@dataclass(frozen=True)
class PoolProcessorConfig:
    redis_url: str | None = None

    poll_interval_seconds: float = 0.25

    scan_count: int = 500
    max_keys_per_tick: int = 2000
    max_jobs_per_tick: int = 2000

    default_timeout_seconds: int = 300

    # By default ALL are infinite (None), as requested.
    # Note: with startup lock dropping, deadlocks are less painful, but still possible mid-run.
    processing_lock_ttl_seconds: int | None = None
    consumer_ttl_seconds: int | None = None
    producer_ttl_seconds: int | None = None

    max_parallel_pools: int = 8

    # per-model batching (preferred)
    model_batch_sizes: dict[str, int] | None = None

    # fallback: per-host batching
    host_batch_sizes: dict[str, int] | None = None

    # "extended" | "simple"
    default_response_parser: str = "extended"

    # http session
    tls_dns_cache: int = 300
    session_timeout: float = 31 * 60
    simultaneous_connections_per_task: int = 1

    # queues / lifecycle
    max_queue_per_pool: int = 2000
    pool_idle_seconds: float = 10.0

    # logs
    verbose: bool = True
    traceback_verbose: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_batch_sizes", tools.default_for_none(self.model_batch_sizes, _default_model_batch_sizes()))
        object.__setattr__(self, "host_batch_sizes", tools.default_for_none(self.host_batch_sizes, _default_host_batch_sizes()))


@dataclass(frozen=True)
class _Job:
    producer_key: str
    consumer_key: str
    processing_key: str
    request_hash: str

    url: str
    headers: dict[str, tp.Any]
    payload: tp.Any
    extra_params: dict[str, tp.Any]


def _default_model_batch_sizes() -> dict[str, int]:
    return {
        # external
        "external:deepseek-reasoner": 100,
        "external:xiaomi-mimo": 100,

        # internal
        "internal:deepseek-reasoner": 100,
        "internal:deepseek_ai_r1": 100,
        "internal:openrouter-gpt-5": 100,
        "internal:openrouter-gpt-5.2": 100,
        "internal:deepseek-v3.1-terminus-batch": 100,
        "internal:deepseek-v3.1-terminus-batch-reasoner": 100,

        # internal zeliboba umbrella
        "__zeliboba__": 50,

        # if you put these into extra_params["model"]
        "http://ecom-assistant-gamma-3.sas.yp-c.yandex.net": 6,
        "http://hamster.yandex.ru/products/ecomassist": 6,
    }


def _default_host_batch_sizes() -> dict[str, int]:
    return {
        "ecom-assistant-gamma-3.sas.yp-c.yandex.net": 6,
        "hamster.yandex.ru": 6,
        "api.eliza.yandex.net": 100,
        "api.deepseek.com": 100,
        "zeliboba.yandex-team.ru": 50,
    }


def _extract_request_hash_from_producer_key(producer_key: str) -> str:
    return producer_key.removeprefix(PRODUCER_PREFIX) if producer_key.startswith(PRODUCER_PREFIX) else producer_key


def _make_consumer_key(request_hash: str) -> str:
    return f"{CONSUMER_PREFIX}{request_hash}"


def _make_processing_key(request_hash: str) -> str:
    return f"{PROCESSING_PREFIX}{request_hash}"


def _safe_dict(value: tp.Any) -> dict[str, tp.Any]:
    return value if isinstance(value, dict) else {}


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").strip()
    except Exception:
        return ""


def _resolve_model_name(extra_params: dict[str, tp.Any]) -> str | None:
    model_candidate = extra_params.get("model")
    if isinstance(model_candidate, str) and model_candidate.strip():
        return model_candidate.strip()

    model_candidate = extra_params.get("model_name")
    if isinstance(model_candidate, str) and model_candidate.strip():
        return model_candidate.strip()

    return None


def _resolve_pool_id_from_parts(url: str, extra_params: dict[str, tp.Any]) -> str:
    model_name = _resolve_model_name(extra_params)

    if isinstance(model_name, str) and model_name.startswith("internal:zeliboba-"):
        return "__zeliboba__"
    if isinstance(model_name, str) and model_name.strip():
        return model_name.strip()

    host = _hostname(url)
    if host:
        return host

    return "__default__"


def _resolve_effective_batch_size_from_parts(url: str, extra_params: dict[str, tp.Any], config: PoolProcessorConfig) -> int:
    override = extra_params.get("batch_size")
    if isinstance(override, (int, float)) and int(override) > 0:
        return int(override)

    pool_id = _resolve_pool_id_from_parts(url, extra_params)

    model_size = _safe_dict(config.model_batch_sizes).get(pool_id)
    if isinstance(model_size, int) and model_size > 0:
        return model_size

    host = _hostname(url)
    host_size = _safe_dict(config.host_batch_sizes).get(host)
    if isinstance(host_size, int) and host_size > 0:
        return host_size

    return 20


def _resolve_effective_timeout_from_parts(extra_params: dict[str, tp.Any], config: PoolProcessorConfig) -> int:
    override = extra_params.get("timeout")
    if isinstance(override, (int, float)) and int(override) > 0:
        return int(override)
    return int(config.default_timeout_seconds)


def _resolve_response_parser_from_parts(extra_params: dict[str, tp.Any], config: PoolProcessorConfig) -> str:
    override = extra_params.get("response_parser")
    if isinstance(override, str) and override.strip():
        override = override.strip().lower()
        if override in ("extended", "simple"):
            return override
    return config.default_response_parser


async def drop_all_processing_flags(
    redis_list_client: router.redis_utils.RedisListStructure,
    *,
    scan_count: int = 5000,
    verbose: bool = True,
) -> int:
    cursor = 0
    deleted = 0

    while True:
        cursor, keys = await redis_list_client.r.scan(
            cursor=int(cursor),
            match=f"{PROCESSING_PREFIX}*",
            count=int(scan_count),
        )

        if keys:
            deleted += int(await redis_list_client.r.delete(*keys))

        if int(cursor) == 0:
            break

    if verbose:
        print(f"[pool_processor] Dropped {deleted} processing flags.")
    return deleted


def _make_error_payload(
    error: BaseException,
    *,
    request_hash: str,
    producer_key: str,
    consumer_key: str,
    processing_key: str,
    url: str,
    config: PoolProcessorConfig,
) -> dict[str, tp.Any]:
    return {
        "__router_delayed_error__": True,
        "error_type": type(error).__name__,
        "error": tools.exception_to_string(error, traceback_verbose=config.traceback_verbose),
        "request_hash": request_hash,
        "producer_key": producer_key,
        "consumer_key": consumer_key,
        "processing_key": processing_key,
        "url": url,
        "ts": time.time(),
    }


async def _store_result(
    redis_list_client: router.redis_utils.RedisListStructure,
    *,
    consumer_key: str,
    payload_obj: tp.Any,
    ttl_seconds: int | None,
) -> None:
    await redis_list_client.clear(consumer_key)

    try:
        payload_raw = json.dumps(payload_obj, ensure_ascii=False)
    except Exception as error:
        payload_raw = json.dumps({
            "__router_delayed_error__": True,
            "error_type": type(error).__name__,
            "error": f"Failed to json.dumps result: {error}",
            "ts": time.time(),
        }, ensure_ascii=False)

    await redis_list_client.add(consumer_key, payload_raw)

    if ttl_seconds is not None:
        await redis_list_client.set_ttl(consumer_key, int(ttl_seconds))


async def _acquire_processing_lock(
    redis_list_client: router.redis_utils.RedisListStructure,
    *,
    processing_key: str,
    ttl_seconds: int | None,
) -> bool:
    if ttl_seconds is None:
        result = await redis_list_client.r.set(processing_key, "1", nx=True)
        return bool(result)

    result = await redis_list_client.r.set(processing_key, "1", nx=True, ex=int(ttl_seconds))
    return bool(result)


async def _release_processing_lock(
    redis_list_client: router.redis_utils.RedisListStructure,
    *,
    processing_key: str,
) -> None:
    await redis_list_client.r.delete(processing_key)


async def _scan_producer_keys_with_cursor(
    redis_list_client: router.redis_utils.RedisListStructure,
    *,
    cursor: int,
    scan_count: int,
    limit: int,
) -> tuple[int, list[str]]:
    keys: list[str] = []
    cursor_int = int(cursor)

    while len(keys) < int(limit):
        cursor_int, batch = await redis_list_client.r.scan(
            cursor=cursor_int,
            match=f"{PRODUCER_PREFIX}*",
            count=int(scan_count),
        )

        if batch:
            for k in batch:
                keys.append(k if isinstance(k, str) else str(k))
                if len(keys) >= int(limit):
                    break

        if cursor_int == 0:
            break

    return cursor_int, keys


async def _run_single_http(
    *,
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, tp.Any],
    payload: tp.Any,
    timeout: int,
    response_parser: str,
    request_hash: str,
    producer_key: str,
    consumer_key: str,
    processing_key: str,
    config: PoolProcessorConfig,
) -> tp.Any:
    try:
        if response_parser == "simple":
            return await router.utils.post_strict_safe_fixed_utf_8(
                session=session,
                url=url,
                headers=headers,
                payload=tp.cast(dict[str, tp.Any], payload),
                timeout=int(timeout),
            )

        return await router.utils.post_strict_safe_fixed_utf_8_extended(
            session=session,
            url=url,
            headers=headers,
            payload=payload,
            timeout=int(timeout),
        )

    except BaseException as error:
        return _make_error_payload(
            error,
            request_hash=request_hash,
            producer_key=producer_key,
            consumer_key=consumer_key,
            processing_key=processing_key,
            url=url,
            config=config,
        )


async def _finalize_job(
    redis_list_client: router.redis_utils.RedisListStructure,
    job: _Job,
    payload_obj: tp.Any,
    config: PoolProcessorConfig,
) -> None:
    extra_params = _safe_dict(job.extra_params)

    is_error = isinstance(payload_obj, dict) and bool(payload_obj.get("__router_delayed_error__"))
    keep_producer_on_error = bool(extra_params.get("keep_producer_on_error", False))

    try:
        await _store_result(
            redis_list_client,
            consumer_key=job.consumer_key,
            payload_obj=payload_obj,
            ttl_seconds=config.consumer_ttl_seconds,
        )

        if is_error and keep_producer_on_error:
            if config.producer_ttl_seconds is not None:
                await redis_list_client.set_ttl(job.producer_key, int(config.producer_ttl_seconds))
        else:
            await redis_list_client.clear(job.producer_key)

    finally:
        await _release_processing_lock(redis_list_client, processing_key=job.processing_key)


class _PoolRunner:
    def __init__(
        self,
        *,
        redis_list_client: router.redis_utils.RedisListStructure,
        pool_id: str,
        batch_size: int,
        config: PoolProcessorConfig,
    ) -> None:
        self.redis_list_client = redis_list_client
        self.pool_id = pool_id
        self.batch_size = int(batch_size)
        self.config = config

        queue_maxsize = max(int(config.max_queue_per_pool), self.batch_size * 4)
        self.queue: asyncio.Queue[_Job] = asyncio.Queue(maxsize=queue_maxsize)

        self._in_flight = 0
        self._errors = 0
        self._closed = False
        self._workers: list[asyncio.Task] = []

        self._last_activity = time.perf_counter()

        concurrency = max(1, self.batch_size)
        connector = aiohttp.TCPConnector(
            limit=concurrency * int(config.simultaneous_connections_per_task),
            limit_per_host=concurrency * int(config.simultaneous_connections_per_task),
            ttl_dns_cache=int(config.tls_dns_cache),
            enable_cleanup_closed=True,
        )
        session_timeout = aiohttp.ClientTimeout(total=float(config.session_timeout))
        self._session = aiohttp.ClientSession(connector=connector, timeout=session_timeout)

    def stats(self) -> dict[str, tp.Any]:
        return {
            "pool_id": self.pool_id,
            "batch_size": self.batch_size,
            "queue_size": int(self.queue.qsize()),
            "in_flight": int(self._in_flight),
            "errors": int(self._errors),
            "last_activity_seconds_ago": round(time.perf_counter() - self._last_activity, 3),
        }

    def is_idle(self, idle_seconds: float) -> bool:
        if self._closed:
            return True
        if self.queue.qsize() > 0:
            return False
        if self._in_flight > 0:
            return False
        return (time.perf_counter() - self._last_activity) >= float(idle_seconds)

    def can_accept(self) -> bool:
        return not self._closed and not self.queue.full()

    async def start(self) -> None:
        if self._workers:
            return

        workers_count = max(1, self.batch_size)

        for worker_index in range(workers_count):
            self._workers.append(asyncio.create_task(self._worker_loop(worker_index)))

        if self.config.verbose:
            print(f"[pool_processor] Started pool={self.pool_id} batch_size={self.batch_size} workers={workers_count}")

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        for _ in self._workers:
            try:
                self.queue.put_nowait(_Job(
                    producer_key="",
                    consumer_key="",
                    processing_key="",
                    request_hash="",
                    url="",
                    headers={},
                    payload={},
                    extra_params={"__shutdown__": True},
                ))
            except asyncio.QueueFull:
                break

        for task in self._workers:
            task.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        await self._session.close()

        if self.config.verbose:
            print(f"[pool_processor] Closed pool={self.pool_id} batch_size={self.batch_size}")

    async def put_nowait(self, job: _Job) -> bool:
        if not self.can_accept():
            return False

        try:
            self.queue.put_nowait(job)
            self._last_activity = time.perf_counter()
            return True
        except asyncio.QueueFull:
            return False

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            job = await self.queue.get()

            # shutdown marker (best-effort)
            if _safe_dict(job.extra_params).get("__shutdown__") is True:
                self.queue.task_done()
                return

            self._in_flight += 1
            self._last_activity = time.perf_counter()

            try:
                extra_params = _safe_dict(job.extra_params)

                payload_obj = await _run_single_http(
                    session=self._session,
                    url=job.url,
                    headers=job.headers,
                    payload=job.payload,
                    timeout=_resolve_effective_timeout_from_parts(extra_params, self.config),
                    response_parser=_resolve_response_parser_from_parts(extra_params, self.config),
                    request_hash=job.request_hash,
                    producer_key=job.producer_key,
                    consumer_key=job.consumer_key,
                    processing_key=job.processing_key,
                    config=self.config,
                )

                if isinstance(payload_obj, dict) and payload_obj.get("__router_delayed_error__"):
                    self._errors += 1

                await _finalize_job(self.redis_list_client, job, payload_obj, self.config)

                if self.config.verbose:
                    print(f"[pool_processor:{self.pool_id}/bs={self.batch_size}] worker={worker_index} done", sep='')

            except BaseException as error:
                payload_obj = _make_error_payload(
                    error,
                    request_hash=job.request_hash,
                    producer_key=job.producer_key,
                    consumer_key=job.consumer_key,
                    processing_key=job.processing_key,
                    url=job.url,
                    config=self.config,
                )

                self._errors += 1

                await _finalize_job(self.redis_list_client, job, payload_obj, self.config)

            finally:
                self._in_flight -= 1
                self._last_activity = time.perf_counter()
                self.queue.task_done()


class _PoolManager:
    def __init__(
        self,
        *,
        redis_list_client: router.redis_utils.RedisListStructure,
        config: PoolProcessorConfig,
    ) -> None:
        self.redis_list_client = redis_list_client
        self.config = config

        self._pools: dict[tuple[str, int], _PoolRunner] = {}
        self._cursor = 0

        self._scanner_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None

        self._stop_event = asyncio.Event()

        self._stats = {
            "seen_producer_keys": 0,
            "skipped_consumer_exists": 0,
            "skipped_locked": 0,
            "skipped_empty_producer": 0,
            "skipped_no_pool_slot": 0,
            "skipped_pool_queue_full": 0,
            "enqueued_jobs": 0,
        }

    def stats(self) -> dict[str, tp.Any]:
        pools_stats = {f"{pid}::bs={bs}": pool.stats() for (pid, bs), pool in self._pools.items()}
        return {
            "cursor": int(self._cursor),
            "pools_count": len(self._pools),
            "stats": dict(self._stats),
            "pools": pools_stats,
        }

    async def start(self) -> None:
        if self._scanner_task is not None:
            return

        self._scanner_task = asyncio.create_task(self._scanner_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        self._stop_event.set()

        if self._scanner_task is not None:
            self._scanner_task.cancel()
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()

        await asyncio.gather(
            *[t for t in [self._scanner_task, self._cleanup_task] if t is not None],
            return_exceptions=True,
        )

        self._scanner_task = None
        self._cleanup_task = None

        for pool in list(self._pools.values()):
            await pool.close()
        self._pools.clear()

    async def run_one_scan_iteration(self) -> None:
        new_cursor, producer_keys = await _scan_producer_keys_with_cursor(
            self.redis_list_client,
            cursor=int(self._cursor),
            scan_count=int(self.config.scan_count),
            limit=int(self.config.max_keys_per_tick),
        )
        self._cursor = int(new_cursor)

        self._stats["seen_producer_keys"] += int(len(producer_keys))

        jobs_added = 0

        for producer_key in producer_keys:
            if jobs_added >= int(self.config.max_jobs_per_tick):
                break

            request_hash = _extract_request_hash_from_producer_key(producer_key)
            consumer_key = _make_consumer_key(request_hash)
            processing_key = _make_processing_key(request_hash)

            if await self.redis_list_client.count(consumer_key) > 0:
                self._stats["skipped_consumer_exists"] += 1
                continue

            raw = await self.redis_list_client.peek(producer_key)
            if raw is None:
                self._stats["skipped_empty_producer"] += 1
                continue

            try:
                data = json.loads(raw)
            except BaseException as error:
                # We can lock and finalize immediately since it's a hard error.
                locked = await _acquire_processing_lock(
                    self.redis_list_client,
                    processing_key=processing_key,
                    ttl_seconds=self.config.processing_lock_ttl_seconds,
                )
                if not locked:
                    self._stats["skipped_locked"] += 1
                    continue

                payload_obj = _make_error_payload(
                    error,
                    request_hash=request_hash,
                    producer_key=producer_key,
                    consumer_key=consumer_key,
                    processing_key=processing_key,
                    url="",
                    config=self.config,
                )
                await _finalize_job(
                    self.redis_list_client,
                    _Job(
                        producer_key=producer_key,
                        consumer_key=consumer_key,
                        processing_key=processing_key,
                        request_hash=request_hash,
                        url="",
                        headers={},
                        payload={},
                        extra_params={},
                    ),
                    payload_obj,
                    self.config,
                )
                continue

            url = data.get("url")
            headers = data.get("headers")
            payload = data.get("payload")
            extra_params = _safe_dict(data.get("extra_params"))

            if not isinstance(url, str):
                url = ""
            if not isinstance(headers, dict):
                headers = {}

            pool_id = _resolve_pool_id_from_parts(url, extra_params)
            batch_size = _resolve_effective_batch_size_from_parts(url, extra_params, self.config)
            pool_key = (pool_id, int(batch_size))

            pool = self._pools.get(pool_key)

            # Create pool only if we have a slot.
            if pool is None:
                if len(self._pools) >= int(self.config.max_parallel_pools):
                    self._stats["skipped_no_pool_slot"] += 1
                    continue

                pool = _PoolRunner(
                    redis_list_client=self.redis_list_client,
                    pool_id=pool_id,
                    batch_size=int(batch_size),
                    config=self.config,
                )
                self._pools[pool_key] = pool
                await pool.start()

            if not pool.can_accept():
                self._stats["skipped_pool_queue_full"] += 1
                continue

            # Acquire lock only when we can enqueue.
            locked = await _acquire_processing_lock(
                self.redis_list_client,
                processing_key=processing_key,
                ttl_seconds=self.config.processing_lock_ttl_seconds,
            )
            if not locked:
                self._stats["skipped_locked"] += 1
                continue

            # Re-check producer (could be deleted between peek and lock).
            raw2 = await self.redis_list_client.peek(producer_key)
            if raw2 is None:
                self._stats["skipped_empty_producer"] += 1
                await _release_processing_lock(self.redis_list_client, processing_key=processing_key)
                continue

            # Use the latest payload (raw2), parse again.
            try:
                data2 = json.loads(raw2)
            except BaseException as error:
                payload_obj = _make_error_payload(
                    error,
                    request_hash=request_hash,
                    producer_key=producer_key,
                    consumer_key=consumer_key,
                    processing_key=processing_key,
                    url=url,
                    config=self.config,
                )
                await _finalize_job(
                    self.redis_list_client,
                    _Job(
                        producer_key=producer_key,
                        consumer_key=consumer_key,
                        processing_key=processing_key,
                        request_hash=request_hash,
                        url=url,
                        headers=tp.cast(dict[str, tp.Any], headers),
                        payload=payload,
                        extra_params=extra_params,
                    ),
                    payload_obj,
                    self.config,
                )
                continue

            url2 = data2.get("url")
            headers2 = data2.get("headers")
            payload2 = data2.get("payload")
            extra_params2 = _safe_dict(data2.get("extra_params"))

            if not isinstance(url2, str):
                url2 = url
            if not isinstance(headers2, dict):
                headers2 = headers

            job = _Job(
                producer_key=producer_key,
                consumer_key=consumer_key,
                processing_key=processing_key,
                request_hash=request_hash,
                url=url2,
                headers=tp.cast(dict[str, tp.Any], headers2),
                payload=payload2,
                extra_params=extra_params2,
            )

            ok = await pool.put_nowait(job)
            if not ok:
                self._stats["skipped_pool_queue_full"] += 1
                await _release_processing_lock(self.redis_list_client, processing_key=processing_key)
                continue

            jobs_added += 1
            self._stats["enqueued_jobs"] += 1

    async def _scanner_loop(self) -> None:
        while not self._stop_event.is_set():
            await self.run_one_scan_iteration()
            await asyncio.sleep(float(self.config.poll_interval_seconds))

    async def _cleanup_loop(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(max(0.25, float(self.config.pool_idle_seconds) / 2.0))

            to_delete: list[tuple[str, int]] = []

            for pool_key, pool in list(self._pools.items()):
                if pool.is_idle(self.config.pool_idle_seconds):
                    to_delete.append(pool_key)

            for pool_key in to_delete:
                pool = self._pools.pop(pool_key, None)
                if pool is not None:
                    await pool.close()


async def run_once(
    *,
    redis_list_client: router.redis_utils.RedisListStructure | None = None,
    config: PoolProcessorConfig | None = None,
) -> dict[str, tp.Any]:
    config = tools.default_for_none(config, PoolProcessorConfig())

    if redis_list_client is None:
        redis_list_client = router.redis_utils.RedisListStructure(
            url=tools.default_for_none(config.redis_url, router.redis_utils.REDIS_URL)
        )

    manager = _PoolManager(redis_list_client=redis_list_client, config=config)

    await manager.start()
    await manager.run_one_scan_iteration()

    # give queued jobs a tiny moment (optional)
    await asyncio.sleep(0.0)

    result = manager.stats()
    await manager.stop()

    return result


async def run_forever(
    *,
    redis_list_client: router.redis_utils.RedisListStructure | None = None,
    config: PoolProcessorConfig | None = None,
) -> None:
    config = tools.default_for_none(config, PoolProcessorConfig())

    if redis_list_client is None:
        redis_list_client = router.redis_utils.RedisListStructure(
            url=tools.default_for_none(config.redis_url, router.redis_utils.REDIS_URL)
        )

    await drop_all_processing_flags(
        redis_list_client,
        scan_count=int(config.scan_count),
        verbose=config.verbose,
    )

    manager = _PoolManager(redis_list_client=redis_list_client, config=config)
    await manager.start()

    try:
        while True:
            await asyncio.sleep(1.0)

            # if config.verbose:
            #     print("[pool_processor] state:", json.dumps(manager.stats(), ensure_ascii=False))

    finally:
        await manager.stop()
        await redis_list_client.close()


def main() -> None:
    processing_ttl_raw = os.getenv("ROUTER_POOL_PROCESSING_LOCK_TTL", "")
    consumer_ttl_raw = os.getenv("ROUTER_POOL_CONSUMER_TTL", "")
    producer_ttl_raw = os.getenv("ROUTER_POOL_PRODUCER_TTL", "")

    def parse_optional_int(value: str) -> int | None:
        value = (value or "").strip()
        if not value:
            return None
        return int(value)

    config = PoolProcessorConfig(
        poll_interval_seconds=float(os.getenv("ROUTER_POOL_POLL_INTERVAL", "0.25")),
        scan_count=int(os.getenv("ROUTER_POOL_SCAN_COUNT", "500")),
        max_keys_per_tick=int(os.getenv("ROUTER_POOL_MAX_KEYS_PER_TICK", "2000")),
        max_jobs_per_tick=int(os.getenv("ROUTER_POOL_MAX_JOBS_PER_TICK", "2000")),
        default_timeout_seconds=int(os.getenv("ROUTER_POOL_DEFAULT_TIMEOUT", "300")),
        processing_lock_ttl_seconds=parse_optional_int(processing_ttl_raw),
        consumer_ttl_seconds=parse_optional_int(consumer_ttl_raw),
        producer_ttl_seconds=parse_optional_int(producer_ttl_raw),
        max_parallel_pools=int(os.getenv("ROUTER_POOL_MAX_PARALLEL_POOLS", "8")),
        tls_dns_cache=int(os.getenv("ROUTER_POOL_TLS_DNS_CACHE", "300")),
        session_timeout=float(os.getenv("ROUTER_POOL_SESSION_TIMEOUT", str(31 * 60))),
        simultaneous_connections_per_task=int(os.getenv("ROUTER_POOL_SIMULTANEOUS_CONNECTIONS_PER_TASK", "1")),
        max_queue_per_pool=int(os.getenv("ROUTER_POOL_MAX_QUEUE_PER_POOL", "2000")),
        pool_idle_seconds=float(os.getenv("ROUTER_POOL_IDLE_SECONDS", "10")),
        verbose=True,
        traceback_verbose=True,
    )

    asyncio.run(run_forever(config=config))


if __name__ == "__main__":
    main()