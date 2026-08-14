"""Runtime for AI-authored provider connection modules.

The provider updater asks a capable model to write the Python that talks to a
provider's chat API, because provider request shapes drift (DeepSeek renaming
``deepseek-chat`` to ``deepseek-v4-flash``, OpenAI moving reasoning models to
``max_completion_tokens`` and ``/v1/responses``) faster than hand-written
adapters can be redeployed.

Executing model-written code on the production server is only defensible with
real controls around it, so every revision passes through all of these:

1. **Only staff** can trigger authoring; the author is one of the providers the
   account already trusts with its API keys.
2. **Static screening** (:func:`screen_source`) rejects imports outside a tiny
   allowlist, private/dunder attribute access, dangerous builtins, and
   module-level loops before the source is ever compiled.
3. **No ambient capability at runtime**: the module executes with a curated
   ``__builtins__`` and receives exactly one object, :class:`AdapterContext`,
   whose only method performs an HTTPS request to the provider's own registered
   domain with capped timeout and capped response size. The generated code
   cannot open files, spawn processes, import modules, or reach another host.
4. **Proof before activation**: a revision is stored as a draft and only becomes
   active after it has answered live provider calls (see provider_updates).
5. **Reversible**: every revision is retained and a previous one can be
   reactivated without a deploy.

This is a strong containment boundary, not a formally secure sandbox: a
determined adversary with a novel CPython escape could still get out. The
threat it is built for is a hallucinating or prompt-influenced model, and the
worst realistic outcome is a revision that fails its canary and never activates.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import json
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import aiohttp
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from router.llm import deepseek_chat, deepseek_reasoner, xiaomi_mimo
from router.llm import router as router_module

from learning.exceptions import LlmResponseError
from learning.models import RouterAdapter

# Hosts a generated adapter may call, per provider. Reviewed application code,
# never model output. Subdomains are allowed so a provider moving from
# api.example.com to eu.api.example.com keeps working; a different registrable
# domain requires an operator to extend PROVIDER_ADAPTER_EXTRA_DOMAINS.
PROVIDER_DOMAINS: dict[str, tuple[str, ...]] = {
    'deepseek': ('api.deepseek.com', 'deepseek.com'),
    'openai': ('api.openai.com', 'openai.com'),
    'anthropic': ('api.anthropic.com', 'anthropic.com'),
    'openrouter': ('openrouter.ai',),
    'xiaomi': ('api.xiaomimimo.com', 'xiaomimimo.com'),
}

ALLOWED_IMPORTS = frozenset({'json', 're', 'math', 'time', 'typing', 'dataclasses'})

# Screened out even though the curated builtins would already deny most of them:
# a clear pre-execution report beats a NameError from inside a live request.
FORBIDDEN_NAMES = frozenset({
    'eval', 'exec', 'compile', 'open', 'input', 'breakpoint', 'exit', 'quit', 'help',
    'globals', 'locals', 'vars', 'dir', 'getattr', 'setattr', 'delattr', 'hasattr',
    'memoryview', 'object', 'type', 'super', 'classmethod', 'staticmethod', 'property',
    'os', 'sys', 'subprocess', 'socket', 'shutil', 'pathlib', 'importlib', 'builtins',
    'aiohttp', 'requests', 'urllib', 'http', 'asyncio', 'threading', 'multiprocessing',
    'pickle', 'marshal', 'ctypes', 'gc', 'inspect', 'traceback', 'code', 'codeop',
})

SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(builtins, name)
    for name in (
        'abs', 'all', 'any', 'bool', 'bytes', 'dict', 'divmod', 'enumerate', 'filter',
        'float', 'format', 'frozenset', 'int', 'isinstance', 'issubclass', 'iter', 'len',
        'list', 'map', 'max', 'min', 'next', 'range', 'repr', 'reversed', 'round', 'set',
        'slice', 'sorted', 'str', 'sum', 'tuple', 'zip',
        'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError', 'RuntimeError',
        'ZeroDivisionError', 'ArithmeticError', 'AttributeError', 'StopIteration',
    )
}

MAX_SOURCE_CHARS = 24_000
MAX_SOURCE_LINES = 500
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

ADAPTER_CONTRACT = '''async def post(ctx, *, model, token, messages, options) -> dict'''


class AdapterError(LlmResponseError):
    """A generated adapter was rejected, or failed while running."""


@dataclass
class ScreeningReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    lines: int = 0
    characters: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            'ok': self.ok,
            'problems': self.problems[:40],
            'imports': self.imports,
            'lines': self.lines,
            'characters': self.characters,
        }


def _allowed_hosts(provider: str) -> tuple[str, ...]:
    extra = getattr(settings, 'PROVIDER_ADAPTER_EXTRA_DOMAINS', {}) or {}
    configured = extra.get(provider, ()) if isinstance(extra, dict) else ()
    return tuple(PROVIDER_DOMAINS.get(provider, ())) + tuple(configured)


def host_allowed(provider: str, url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != 'https' or not parsed.hostname:
        return False
    host = parsed.hostname.casefold().rstrip('.')
    return any(host == domain or host.endswith(f'.{domain}') for domain in _allowed_hosts(provider))


def screen_source(source: str, provider: str) -> ScreeningReport:
    """Reject model-written code that reaches outside the adapter contract."""
    problems: list[str] = []
    imports: list[str] = []
    lines = source.count('\n') + 1
    if len(source) > MAX_SOURCE_CHARS:
        problems.append(f'The module is {len(source)} characters; the limit is {MAX_SOURCE_CHARS}.')
    if lines > MAX_SOURCE_LINES:
        problems.append(f'The module is {lines} lines; the limit is {MAX_SOURCE_LINES}.')
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ScreeningReport(ok=False, problems=[f'Syntax error on line {exc.lineno}: {exc.msg}'],
                               lines=lines, characters=len(source))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or '']
            for name in names:
                root = name.split('.', 1)[0]
                imports.append(name)
                if root not in ALLOWED_IMPORTS:
                    problems.append(f'Line {node.lineno}: import of "{name}" is not allowed.')
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith('_'):
                problems.append(f'Line {node.lineno}: access to private attribute "{node.attr}" is not allowed.')
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                problems.append(f'Line {node.lineno}: use of "{node.id}" is not allowed.')
            elif node.id.startswith('__'):
                problems.append(f'Line {node.lineno}: use of dunder name "{node.id}" is not allowed.')

    # Module level should only define constants and functions; an unbounded loop
    # there would hang the worker during the very first compile.
    for node in tree.body:
        if isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            problems.append(f'Line {node.lineno}: loops at module level are not allowed.')

    entry = next(
        (node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'post'),
        None,
    )
    if entry is None:
        problems.append(f'The module must define the entry point: {ADAPTER_CONTRACT}')
    else:
        arguments = entry.args
        keyword_names = {argument.arg for argument in arguments.kwonlyargs}
        positional = [argument.arg for argument in arguments.args]
        if positional[:1] != ['ctx']:
            problems.append('post() must take the context object as its first positional argument, named "ctx".')
        missing = {'model', 'token', 'messages', 'options'} - keyword_names - set(positional)
        if missing:
            problems.append(f'post() is missing required parameters: {", ".join(sorted(missing))}.')

    # Any fully literal URL in the source must already point at the provider.
    # Interpolated URLs are skipped here and caught by fetch(), which is the
    # authoritative check; the prompt asks for literal endpoints anyway.
    for match in re.finditer(r'https?://[^\s\'"]+', source):
        url = match.group(0)
        if any(marker in url for marker in ('{', '}', '%s', '%(')):
            problems.append(f'The endpoint {url[:80]} must be a literal URL, not an interpolated one.')
        elif not host_allowed(provider, url):
            problems.append(f'The URL {url[:80]} is not on an allowed {provider} domain.')

    return ScreeningReport(ok=not problems, problems=problems, imports=sorted(set(imports)),
                           lines=lines, characters=len(source))


class AdapterContext:
    """The only capability handed to a generated module."""

    def __init__(self, session: aiohttp.ClientSession, provider: str, timeout: int):
        self._session = session
        self._provider = provider
        self._timeout = timeout
        self.calls: list[dict[str, Any]] = []

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        method: str = 'POST',
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """POST/GET JSON to the provider and return the decoded body."""
        if not isinstance(url, str) or not host_allowed(self._provider, url):
            raise AdapterError(f'The adapter tried to call a host outside {self._provider}: {str(url)[:120]}')
        if method.upper() not in {'POST', 'GET'}:
            raise AdapterError(f'The adapter tried to use the {method} method.')
        if len(self.calls) >= 4:
            raise AdapterError('The adapter made more than 4 provider requests for one completion.')
        safe_headers = {
            str(key): str(value) for key, value in (headers or {}).items()
            if isinstance(key, str) and len(str(value)) < 8192
        }
        effective = min(int(timeout or self._timeout), self._timeout)
        self.calls.append({'url': url, 'method': method.upper()})
        async with self._session.request(
            method.upper(), url, headers=safe_headers, json=json,
            timeout=aiohttp.ClientTimeout(total=effective),
        ) as response:
            raw = await response.content.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AdapterError('The provider response exceeded the 4 MB adapter limit.')
            text = raw.decode('utf-8', errors='replace')
            if response.status >= 400:
                raise AdapterError(f'{self._provider} returned HTTP {response.status}: {text[:400]}')
            try:
                body = _json_loads(text)
            except ValueError as exc:
                raise AdapterError(f'{self._provider} did not return JSON: {text[:200]}') from exc
        if not isinstance(body, dict):
            raise AdapterError(f'{self._provider} returned {type(body).__name__}, not a JSON object.')
        return body


def _json_loads(text: str) -> Any:
    return json.loads(text)


def compile_adapter(source: str, provider: str, *, revision: int = 0) -> dict[str, Any]:
    """Screen, compile and execute the module body; return its namespace."""
    report = screen_source(source, provider)
    if not report.ok:
        raise AdapterError('The generated adapter failed screening: ' + ' '.join(report.problems[:3]))
    namespace: dict[str, Any] = {
        '__builtins__': dict(SAFE_BUILTINS),
        '__name__': f'lexiloop_adapter_{provider}_r{revision}',
    }
    try:
        exec(compile(source, f'<{provider}-adapter-r{revision}>', 'exec'), namespace)  # noqa: S102
    except Exception as exc:
        raise AdapterError(f'The generated adapter failed to load: {type(exc).__name__}: {exc}') from exc
    entry = namespace.get('post')
    if not callable(entry):
        raise AdapterError('The generated adapter does not define post().')
    return namespace


def normalize_result(raw: Any) -> dict[str, Any]:
    """Coerce an adapter's return value into the router's result shape."""
    if not isinstance(raw, dict):
        raise AdapterError(f'The adapter returned {type(raw).__name__}, not a dict.')
    content = raw.get('content')
    if isinstance(content, list):
        content = ''.join(
            part.get('text', '') if isinstance(part, dict) else str(part) for part in content
        )
    if not isinstance(content, str) or not content.strip():
        raise AdapterError('The adapter returned no textual content.')
    stats = raw.get('stats')
    reasoning = raw.get('reasoning_content')
    return {
        'response': raw.get('response') if isinstance(raw.get('response'), dict) else {},
        'content': content,
        'reasoning_content': reasoning if isinstance(reasoning, str) else None,
        'stats': {
            key: value for key, value in (stats or {}).items()
            if isinstance(key, str) and isinstance(value, (int, float, str))
        } if isinstance(stats, dict) else {},
        'elapsed_time': float(raw.get('elapsed_time') or 0.0),
    }


def priced_stats(provider: str, model: str, result: dict[str, Any]) -> dict[str, Any]:
    """Add the cost of a call an AI-authored adapter could not know.

    Most providers do not return a price; the built-in adapters compute it from
    price tables in reviewed code. A generated module returns the provider's raw
    body, so the same tables still apply and the AI usage page keeps working.
    """
    stats = dict(result.get('stats') or {})
    if stats.get('total_price'):
        return stats
    raw = result.get('response')
    if not isinstance(raw, dict):
        return stats
    try:
        if provider == 'deepseek':
            module = deepseek_reasoner if 'pro' in model.lower() else deepseek_chat
            stats.setdefault('total_price', float(module.summarize_response_stats(raw, decimals=False)['total_price']))
        elif provider == 'xiaomi':
            stats.setdefault('total_price', float(xiaomi_mimo.summarize_response_stats(raw, decimals=False)['total_price']))
        elif provider == 'openrouter':
            usage = raw.get('usage')
            if isinstance(usage, dict) and isinstance(usage.get('cost'), (int, float, str)):
                stats.setdefault('total_price', float(usage['cost']))
        elif provider == 'anthropic':
            usage = raw.get('usage')
            if not isinstance(usage, dict):
                return stats
            input_price, output_price = router_module.ANTHROPIC_PRICES.get(model, (Decimal('0'), Decimal('0')))
            total = (
                int(usage.get('input_tokens') or 0) * input_price
                + int(usage.get('output_tokens') or 0) * output_price
                + int(usage.get('cache_read_input_tokens') or 0) * input_price / 10
                + int(usage.get('cache_creation_input_tokens') or 0) * input_price * Decimal('1.25')
            )
            stats.setdefault('total_price', float(total))
    except Exception:
        # Pricing is telemetry. A provider that changed its usage shape must
        # never turn a successful completion into a failure.
        return stats
    return stats


async def run_adapter(
    namespace: dict[str, Any],
    *,
    provider: str,
    model: str,
    token: str,
    messages: list[dict[str, str]],
    options: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute a compiled adapter for one completion, under a hard deadline."""
    started = timezone.now()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout + 15)) as session:
        ctx = AdapterContext(session, provider, timeout)
        try:
            raw = await asyncio.wait_for(
                namespace['post'](
                    ctx,
                    model=model,
                    token=token,
                    messages=[dict(message) for message in messages],
                    options=dict(options or {}),
                ),
                timeout=timeout + 5,
            )
        except AdapterError:
            raise
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise AdapterError(f'The {provider} adapter did not finish within {timeout + 5} seconds.') from exc
        except Exception as exc:
            raise AdapterError(f'The {provider} adapter raised {type(exc).__name__}: {str(exc)[:300]}') from exc
    result = normalize_result(raw)
    if not result['elapsed_time']:
        result['elapsed_time'] = (timezone.now() - started).total_seconds()
    return result


_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}
# Every generation and judge call asks which adapter is active. Re-reading the
# row a few times a minute is enough for an activation to take effect promptly
# while keeping bulk generation off the database for this.
_LOOKUP_TTL_SECONDS = 20.0
_LOOKUPS: dict[str, tuple[float, tuple[RouterAdapter, dict[str, Any]] | None]] = {}


def active_adapter(provider: str) -> tuple[RouterAdapter, dict[str, Any]] | None:
    """The active revision for a provider, compiled and memoized per process.

    Reads the database, so it must be called from synchronous code. Request
    handlers call :func:`refresh_active_adapters` before entering their event
    loop and the coroutine then reads :func:`cached_adapter`.
    """
    now = time.monotonic()
    cached_lookup = _LOOKUPS.get(provider)
    if cached_lookup and now - cached_lookup[0] < _LOOKUP_TTL_SECONDS:
        return cached_lookup[1]
    resolved = _resolve(RouterAdapter.objects.filter(
        provider=provider, status=RouterAdapter.Status.ACTIVE,
    ).first(), provider)
    _LOOKUPS[provider] = (now, resolved)
    return resolved


def refresh_active_adapters(force: bool = False) -> None:
    """Load every active revision into the process cache in one query.

    Activation happens in one process but must reach the other Gunicorn workers,
    so the cache carries a short TTL rather than living forever.
    """
    now = time.monotonic()
    if not force and _LOOKUPS and all(now - stamp < _LOOKUP_TTL_SECONDS for stamp, _ in _LOOKUPS.values()):
        return
    records = {
        record.provider: record
        for record in RouterAdapter.objects.filter(status=RouterAdapter.Status.ACTIVE)
    }
    for provider in PROVIDER_DOMAINS:
        _LOOKUPS[provider] = (now, _resolve(records.get(provider), provider))


def cached_adapter(provider: str) -> dict[str, Any] | None:
    """The compiled namespace for a provider from the cache alone.

    Touches no database, so a coroutine may call it. An unprimed or empty cache
    simply means "no generated adapter", and the built-in router answers.
    """
    entry = _LOOKUPS.get(provider)
    return entry[1][1] if entry and entry[1] else None


def _resolve(record: RouterAdapter | None, provider: str) -> tuple[RouterAdapter, dict[str, Any]] | None:
    if record is None:
        _CACHE.pop(provider, None)
        return None
    cached = _CACHE.get(provider)
    if cached and cached[0] == record.revision:
        return record, cached[1]
    try:
        namespace = compile_adapter(record.source_code, provider, revision=record.revision)
    except AdapterError:
        # A stored revision that no longer compiles must not break study; the
        # caller falls back to the built-in router adapter.
        _CACHE.pop(provider, None)
        return None
    _CACHE[provider] = (record.revision, namespace)
    return record, namespace


def forget_cached_adapters(provider: str | None = None) -> None:
    if provider is None:
        _CACHE.clear()
        _LOOKUPS.clear()
    else:
        _CACHE.pop(provider, None)
        _LOOKUPS.pop(provider, None)


def adapter_revisions(provider: str) -> list[dict[str, Any]]:
    return [
        {
            'revision': record.revision,
            'status': record.status,
            'author_model': record.author_model,
            'lines': record.screening.get('lines') if isinstance(record.screening, dict) else None,
            'verified_models': record.canary.get('passed') if isinstance(record.canary, dict) else [],
            'failures': record.canary.get('failed') if isinstance(record.canary, dict) else {},
            'notes': record.notes,
            'created_at': record.created_at.isoformat(),
            'activated_at': record.activated_at.isoformat() if record.activated_at else None,
            'source_code': record.source_code,
        }
        for record in RouterAdapter.objects.filter(provider=provider).order_by('-revision')[:20]
    ]


def activate_revision(record: RouterAdapter) -> RouterAdapter:
    """Make one revision the active adapter, retiring the previous one."""
    with transaction.atomic():
        RouterAdapter.objects.filter(
            provider=record.provider, status=RouterAdapter.Status.ACTIVE,
        ).exclude(pk=record.pk).update(status=RouterAdapter.Status.SUPERSEDED, updated_at=timezone.now())
        record.status = RouterAdapter.Status.ACTIVE
        record.activated_at = timezone.now()
        record.save(update_fields=['status', 'activated_at', 'updated_at'])
    forget_cached_adapters(record.provider)
    return record


def rollback_adapter(*, provider: str, revision: int) -> dict[str, Any]:
    record = RouterAdapter.objects.filter(provider=provider, revision=revision).first()
    if record is None:
        raise LookupError(revision)
    if record.status == RouterAdapter.Status.ACTIVE:
        raise ValueError(f'Revision {revision} is already active.')
    try:
        compile_adapter(record.source_code, provider, revision=revision)
    except AdapterError as exc:
        raise ValueError(str(exc)) from exc
    activate_revision(record)
    return {'revision': record.revision, 'status': record.status, 'author_model': record.author_model}
