from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

import edge_tts
import requests
from django.conf import settings

from learning.services.english import validate_english_term


class PronunciationError(RuntimeError):
    pass


def pronunciation_path(text: str) -> Path:
    validated = validate_english_term(text)
    digest = hashlib.sha256(
        f'{settings.TTS_VOICE}\0{settings.TTS_RATE}\0{validated.normalized.casefold()}'.encode('utf-8')
    ).hexdigest()
    directory = Path(settings.MEDIA_ROOT) / 'pronunciations'
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f'{digest}.mp3'


def _dictionary_audio(text: str, destination: Path) -> bool:
    """Prefer dictionary recordings for single words; return False when absent."""
    if ' ' in text or '-' in text:
        return False
    try:
        response = requests.get(
            f'https://api.dictionaryapi.dev/api/v2/entries/en/{quote(text)}',
            timeout=min(10, settings.TTS_TIMEOUT_SECONDS),
            headers={'User-Agent': 'LexiLoop/1.1'},
        )
        if response.status_code != 200:
            return False
        payload = response.json()
        entries = payload if isinstance(payload, list) else []
        audio_url = ''
        for entry in entries:
            for phonetic in entry.get('phonetics', []) if isinstance(entry, dict) else []:
                candidate = phonetic.get('audio') if isinstance(phonetic, dict) else ''
                if candidate:
                    audio_url = str(candidate)
                    break
            if audio_url:
                break
        if not audio_url:
            return False
        if audio_url.startswith('//'):
            audio_url = f'https:{audio_url}'
        audio = requests.get(audio_url, timeout=min(15, settings.TTS_TIMEOUT_SECONDS), headers={'User-Agent': 'LexiLoop/1.1'})
        if audio.status_code != 200 or len(audio.content) <= 512 or len(audio.content) > 5_000_000:
            return False
        destination.write_bytes(audio.content)
        return True
    except (requests.RequestException, ValueError, TypeError):
        return False


async def _generate_neural(text: str, destination: Path) -> None:
    communicate = edge_tts.Communicate(
        text=text,
        voice=settings.TTS_VOICE,
        rate=settings.TTS_RATE,
    )
    await communicate.save(str(destination))


def generate_pronunciation(text: str) -> Path:
    validated = validate_english_term(text)
    destination = pronunciation_path(validated.normalized)
    if destination.exists() and destination.stat().st_size > 512:
        return destination

    fd, temporary_name = tempfile.mkstemp(prefix='lexiloop-tts-', suffix='.mp3', dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    errors: list[str] = []
    try:
        if _dictionary_audio(validated.normalized, temporary):
            os.replace(temporary, destination)
            return destination
        try:
            asyncio.run(asyncio.wait_for(
                _generate_neural(validated.normalized, temporary),
                timeout=settings.TTS_TIMEOUT_SECONDS,
            ))
        except Exception as exc:
            errors.append(str(exc))
        if not temporary.exists() or temporary.stat().st_size <= 512:
            detail = errors[-1] if errors else 'no audio source returned data'
            raise PronunciationError(f'Neural pronunciation is temporarily unavailable: {detail}')
        os.replace(temporary, destination)
        return destination
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, PronunciationError):
            raise
        raise PronunciationError(f'Neural pronunciation is temporarily unavailable: {exc}') from exc
