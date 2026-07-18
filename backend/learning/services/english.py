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

# Parenthetical labels recognized as part-of-speech metadata. Since v1.25 they
# are no longer discarded: a label selects the sense the flashcard should
# cover, so "bark (v)" and "bark (n)" become two distinct cards. Only
# metadata-looking annotations are touched, not arbitrary parenthetical
# content from phrases.
_POS_CANONICAL = {
    'n': 'noun', 'noun': 'noun', 'sing': 'noun', 'singular': 'noun',
    'pl': 'noun', 'plural': 'noun', 'c': 'noun', 'countable': 'noun',
    'u': 'noun', 'uncountable': 'noun',
    'v': 'verb', 'verb': 'verb', 'aux': 'verb', 'auxiliary': 'verb', 'modal': 'verb',
    'adj': 'adjective', 'adjective': 'adjective',
    'adv': 'adverb', 'adverb': 'adverb',
    'prep': 'preposition', 'preposition': 'preposition',
    'pron': 'pronoun', 'pronoun': 'pronoun',
    'conj': 'conjunction', 'conjunction': 'conjunction',
    'det': 'determiner', 'determiner': 'determiner',
    'interj': 'interjection', 'interjection': 'interjection',
    'phrase': 'phrase', 'phr': 'phrase', 'idiom': 'idiom',
}
_POS_LABELS = frozenset(_POS_CANONICAL)
_PAREN_RE = re.compile(r"\(([^()]*)\)")

# A free-form generation request (the single-add input) is capped to keep
# prompts small and deny prompt-stuffing.
MAX_GENERATION_REQUEST_CHARS = 1000


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


def canonical_pos_labels(content: str) -> list[str] | None:
    """Canonical POS names for a pure annotation like ``n / adj``, else None."""
    if not _is_pos_annotation(content):
        return None
    labels: list[str] = []
    for token in re.findall(r"[A-Za-z]+", content):
        canonical = _POS_CANONICAL.get(token.casefold())
        if canonical and canonical not in labels:
            labels.append(canonical)
    return labels


def canonical_pos_string(text: str) -> str:
    """Reduce free-form POS wording ("transitive verb", "n / adj") to canonical
    names joined with '/'; '' when nothing recognizable remains."""
    labels: list[str] = []
    for token in re.findall(r"[A-Za-z]+", str(text)):
        canonical = _POS_CANONICAL.get(token.casefold())
        if canonical and canonical not in labels:
            labels.append(canonical)
    return '/'.join(labels)


def normalized_identity(term: str, part_of_speech: str = '') -> str:
    """The duplicate-detection key stored in ``Flashcard.normalized_term``.

    A sense-restricted card carries its canonical POS so that "bark (verb)"
    and "bark (noun)" coexist while the term shown to the learner stays
    "bark". A general card keeps the historical bare casefold, so every
    pre-v1.25 card keeps its identity.
    """
    base = ' '.join(str(term).casefold().split())
    return f'{base} ({part_of_speech})' if part_of_speech else base


def split_bulk_term(value: str) -> tuple[str, str]:
    """Split a vocabulary-list item into (bare term, canonical POS string).

    Examples:
      ``to abolish (v)`` -> ``('abolish', 'verb')``
      ``adolescent (n / adj)`` -> ``('adolescent', 'noun/adjective')``
      ``perch`` -> ``('perch', '')``
    """
    cleaned = _normalise(value)
    pos: list[str] = []

    def strip_annotation(match: re.Match) -> str:
        labels = canonical_pos_labels(match.group(1))
        if labels is None:
            return match.group(0)
        for label in labels:
            if label not in pos:
                pos.append(label)
        return ''

    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _normalise(_PAREN_RE.sub(strip_annotation, cleaned))
    cleaned = re.sub(r'^to\s+', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(' \t,;:/')
    return _normalise(cleaned), '/'.join(pos)


def normalize_bulk_term(value: str) -> str:
    """Clean one vocabulary-list item, keeping its POS label as ``term (pos)``."""
    cleaned, pos = split_bulk_term(value)
    if cleaned and pos:
        return f'{cleaned} ({pos})'
    return cleaned


@dataclass(frozen=True)
class GenerationRequest:
    """A parsed single-add / bulk-item generation request.

    ``interpret`` marks a free-form request the model itself must read to find
    the target term (the server re-validates whatever it extracts); otherwise
    ``term`` is already validated and ``part_of_speech`` optionally restricts
    the card to one sense.
    """
    term: str
    part_of_speech: str
    raw: str
    interpret: bool

    @property
    def identity(self) -> str:
        return normalized_identity(self.term, self.part_of_speech)


_TRAILING_ANNOTATIONS_RE = re.compile(r"^(?P<term>.*?)\s*(?P<annotations>(?:\([^()]*\)\s*)*)$")


def parse_generation_request(raw: str) -> GenerationRequest:
    """Understand what the learner asked to study.

    Deterministic shapes are resolved without a model: a plain validated term
    ("perch"), and the classic vocabulary-list shape with trailing POS labels
    ("bark (verb)", "alert (n / adj)"). Typos and gibberish in those shapes
    fail fast with the spellchecker's message, exactly like before. Anything
    structured beyond that ("bark verb", "bark — the sound a dog makes") is
    handed to the model to interpret, with server-side re-validation of the
    term it extracts.
    """
    normalized = _normalise(raw)
    if not normalized:
        raise InvalidEnglishTerm('Enter an English word or collocation.')
    if len(normalized) > MAX_GENERATION_REQUEST_CHARS:
        raise InvalidEnglishTerm(
            f'The request is too long (maximum {MAX_GENERATION_REQUEST_CHARS} characters).'
        )

    # "bark (verb)"-shaped: term followed only by POS annotations.
    match = _TRAILING_ANNOTATIONS_RE.fullmatch(normalized)
    if match and match.group('annotations'):
        contents = _PAREN_RE.findall(match.group('annotations'))
        labels: list[str] = []
        pure = True
        for content in contents:
            found = canonical_pos_labels(content)
            if found is None:
                pure = False
                break
            for label in found:
                if label not in labels:
                    labels.append(label)
        term_part = match.group('term').strip()
        if pure and labels and _TERM_RE.fullmatch(term_part):
            term = validate_english_term(term_part).normalized
            return GenerationRequest(term=term, part_of_speech='/'.join(labels), raw=normalized, interpret=False)

    if _TERM_RE.fullmatch(normalized):
        validated = validate_english_term(normalized)
        words = [word.casefold() for word in validated.words]
        if len(words) > 1 and any(word in _POS_LABELS for word in words):
            # "bark verb" (a POS instruction) and "phrasal verb" (an actual
            # term) look identical here — only the model can tell them apart.
            return GenerationRequest(term='', part_of_speech='', raw=normalized, interpret=True)
        return GenerationRequest(term=validated.normalized, part_of_speech='', raw=normalized, interpret=False)

    # Free-form context needs at least a term plus qualifiers; a single
    # code-like token ("bark7") is rejected the way it always was.
    if ' ' not in normalized:
        validate_english_term(normalized)  # raises with the standard message
    return GenerationRequest(term='', part_of_speech='', raw=normalized, interpret=True)


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
        bare, pos = split_bulk_term(source)
        if not bare:
            errors.append({'term': source, 'error': 'No English term remained after removing metadata.'})
            continue
        try:
            validated = validate_english_term(bare).normalized
        except InvalidEnglishTerm as exc:
            errors.append({'term': source, 'normalized': bare, 'error': str(exc)})
            continue
        # The POS label stays with the item: it now selects the sense the card
        # covers, so the same word with different labels yields distinct cards.
        item = f'{validated} ({pos})' if pos else validated
        if len(normalized_identity(validated, pos)) > 250:
            errors.append({'term': source, 'normalized': item, 'error': 'The term is too long (maximum 250 characters).'})
            continue
        key = item.casefold()
        if key in seen:
            changes.append({'source': source, 'normalized': item, 'status': 'duplicate'})
            continue
        seen.add(key)
        normalized.append(item)
        changes.append({
            'source': source,
            'normalized': item,
            'status': 'changed' if source != item else 'unchanged',
        })

    return BulkNormalization(
        normalized=tuple(normalized),
        changes=tuple(changes),
        errors=tuple(errors),
        input_count=len(source_items),
    )
