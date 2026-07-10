from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache

from spellchecker import SpellChecker
from wordfreq import top_n_list, zipf_frequency

# LexiLoop intentionally teaches ordinary English vocabulary and collocations, not
# arbitrary identifiers, code, or words written in another alphabet.
_TERM_RE = re.compile(r"^[A-Za-z]+(?:['’-][A-Za-z]+)*(?:[ -][A-Za-z]+(?:['’-][A-Za-z]+)*)*$")
_TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
_COMMON_SHORT_WORDS = {
    'a', 'an', 'as', 'at', 'be', 'by', 'do', 'go', 'he', 'i', 'if', 'in', 'is',
    'it', 'me', 'my', 'no', 'of', 'on', 'or', 'so', 'to', 'up', 'us', 'we',
}
# A high corpus-frequency fallback admits established British spellings that the
# bundled spellchecker dictionary may omit, while still rejecting common typos.
_FALLBACK_ZIPF = 3.0

# Parenthetical labels accepted by the bulk importer. We deliberately remove only
# metadata-looking annotations, not arbitrary parenthetical content from phrases.
_POS_LABELS = {
    'n', 'noun', 'v', 'verb', 'adj', 'adjective', 'adv', 'adverb', 'prep',
    'preposition', 'pron', 'pronoun', 'conj', 'conjunction', 'det', 'determiner',
    'interj', 'interjection', 'phrase', 'phr', 'idiom', 'modal', 'aux', 'auxiliary',
    'sing', 'singular', 'pl', 'plural', 'countable', 'uncountable', 'c', 'u',
}
_PAREN_RE = re.compile(r"\(([^()]*)\)")


@dataclass(frozen=True)
class EnglishTermValidation:
    normalized: str
    words: tuple[str, ...]


@dataclass(frozen=True)
class BulkNormalization:
    normalized: tuple[str, ...]
    changes: tuple[dict[str, str], ...]
    errors: tuple[dict[str, str], ...]
    input_count: int


class InvalidEnglishTerm(ValueError):
    def __init__(self, message: str, *, suggestions: dict[str, str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or {}


def _normalise(term: str) -> str:
    return ' '.join(str(term).strip().replace('’', "'").split())


@lru_cache(maxsize=1)
def _suggestion_words() -> tuple[str, ...]:
    # The list is loaded only after an invalid token is encountered.
    return tuple(word for word in top_n_list('en', 60000, ascii_only=True) if word.isalpha() and len(word) > 1)


@lru_cache(maxsize=1)
def _spellchecker() -> SpellChecker:
    return SpellChecker(language='en', distance=2)


def _known_word(token: str) -> bool:
    token = token.casefold().replace('’', "'")
    if token in _COMMON_SHORT_WORDS:
        return True
    if token in _spellchecker():
        return True
    if zipf_frequency(token, 'en', wordlist='best') >= _FALLBACK_ZIPF:
        return True
    # A hyphenated compound or contraction can be valid even when the complete
    # surface form is sparse. Every lexical component must still be English.
    pieces = [piece for piece in re.split(r"[-']", token) if piece]
    return len(pieces) > 1 and all(
        piece in _COMMON_SHORT_WORDS
        or piece in _spellchecker()
        or zipf_frequency(piece, 'en', wordlist='best') >= _FALLBACK_ZIPF
        for piece in pieces
    )


def _suggest(token: str) -> str | None:
    token = token.casefold()
    correction = _spellchecker().correction(token)
    if correction and correction != token:
        return correction
    # Similar lengths avoid absurd suggestions for random long strings.
    candidates = [word for word in _suggestion_words() if abs(len(word) - len(token)) <= 2]
    match = get_close_matches(token, candidates, n=1, cutoff=0.79)
    return match[0] if match else None


def validate_english_term(term: str) -> EnglishTermValidation:
    normalized = _normalise(term)
    if not normalized:
        raise InvalidEnglishTerm('Enter an English word or collocation.')
    if len(normalized) > 250:
        raise InvalidEnglishTerm('The term is too long (maximum 250 characters).')
    if not _TERM_RE.fullmatch(normalized):
        raise InvalidEnglishTerm(
            'Use an English word or collocation written with Latin letters. '
            'Numbers, code-like strings, and other alphabets are not accepted.'
        )

    words = tuple(match.group(0) for match in _TOKEN_RE.finditer(normalized))
    unknown = [word for word in words if not _known_word(word)]
    if unknown:
        suggestions = {word: suggestion for word in unknown if (suggestion := _suggest(word))}
        details = []
        for word in unknown:
            details.append(f'“{word}” → perhaps “{suggestions[word]}”' if word in suggestions else f'“{word}”')
        raise InvalidEnglishTerm(
            'Unrecognized or probably misspelled English word: ' + ', '.join(details) + '.',
            suggestions=suggestions,
        )
    return EnglishTermValidation(normalized=normalized, words=words)


def _split_outside_parentheses(value: str, separators: set[str]) -> list[str]:
    """Split on separators only at parenthesis depth zero."""
    chunks: list[str] = []
    current: list[str] = []
    depth = 0
    for char in value:
        if char == '(':
            depth += 1
        elif char == ')' and depth:
            depth -= 1
        if char in separators and depth == 0:
            chunk = ''.join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
        else:
            current.append(char)
    chunk = ''.join(current).strip()
    if chunk:
        chunks.append(chunk)
    return chunks


def _is_pos_annotation(content: str) -> bool:
    tokens = [token.casefold() for token in re.findall(r"[A-Za-z]+", content)]
    return bool(tokens) and all(token in _POS_LABELS for token in tokens)


def normalize_bulk_term(value: str) -> str:
    """Remove vocabulary-list metadata while preserving the lexical item itself.

    Examples:
      ``to abolish (v)`` -> ``abolish``
      ``adolescent (n / adj)`` -> ``adolescent``
    """
    cleaned = _normalise(value)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _PAREN_RE.sub(lambda match: '' if _is_pos_annotation(match.group(1)) else match.group(0), cleaned)
        cleaned = _normalise(cleaned)
    cleaned = re.sub(r'^to\s+', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(' \t,;:/')
    return _normalise(cleaned)


def normalize_bulk_terms(raw_terms: str | list[object]) -> BulkNormalization:
    """Parse, clean, validate, and deduplicate a pasted vocabulary list.

    Slashes separating multiple grammatical forms are handled only outside
    parentheses, so ``alert (n / adj)`` remains one source item while
    ``to alert (v) / alert (n / adj)`` is split and then deduplicated.
    """
    if isinstance(raw_terms, str):
        top_level: list[str] = []
        for line in raw_terms.splitlines():
            top_level.extend(_split_outside_parentheses(line, {';', ','}))
    elif isinstance(raw_terms, list):
        top_level = [str(value) for value in raw_terms]
    else:
        top_level = []

    source_items: list[str] = []
    for item in top_level:
        source_items.extend(_split_outside_parentheses(item, {'/'}))

    normalized: list[str] = []
    changes: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()

    for source in source_items:
        source = _normalise(source)
        if not source:
            continue
        cleaned = normalize_bulk_term(source)
        if not cleaned:
            errors.append({'term': source, 'error': 'No English term remained after removing metadata.'})
            continue
        try:
            validated = validate_english_term(cleaned).normalized
        except InvalidEnglishTerm as exc:
            errors.append({'term': source, 'normalized': cleaned, 'error': str(exc)})
            continue
        key = validated.casefold()
        if key in seen:
            changes.append({'source': source, 'normalized': validated, 'status': 'duplicate'})
            continue
        seen.add(key)
        normalized.append(validated)
        changes.append({
            'source': source,
            'normalized': validated,
            'status': 'changed' if source != validated else 'unchanged',
        })

    return BulkNormalization(
        normalized=tuple(normalized),
        changes=tuple(changes),
        errors=tuple(errors),
        input_count=len(source_items),
    )
