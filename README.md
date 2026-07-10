# LexiLoop — AI-assisted English flashcards

LexiLoop is a Django + React platform for building and retaining English vocabulary. It combines one-field AI card creation, semantic answer judging, durable high-volume generation, server-side pagination, PostgreSQL storage, HTTPS deployment, and an Anki-inspired review scheduler with a polished responsive interface.

Version **1.10.0** focuses on user-tested reliability and mobile polish: review results are saved immediately, direct OpenAI API models are available, the default accent is emerald, and narrow smartphone layouts are improved.

## Highlights

- Username/password accounts. Email is not required.
- Multiple vocabulary pools with persistent names, descriptions, and colors.
- Right-click or ellipsis pool actions: rename, recolor, copy, merge, or delete.
- Pool selection preserves the current page. If Study is open, the next task comes from the newly selected pool.
- One-field AI generation for definitions, IPA, examples, forms, synonyms, antonyms, collocations, aliases, and usage notes.
- Public model catalog with readable choices for DeepSeek, direct OpenAI, OpenRouter, Claude, Gemini, Kimi, and MiMo.
- Two-stage bulk normalization followed by a durable background worker for up to 1000 terms.
- Immediate per-card persistence, retry rounds, progress reporting, cancellation, and final failed-term reports.
- Free-form definition judging using a fixed 1–7 semantic rubric.
- Definition → word checks performed locally, including aliases and optional infinitive `to`.
- Hedged judge requests: a second request starts after a short delay and the first successful answer wins.
- Server-side Library pagination for large pools.
- Dynamic page titles, cached pronunciation audio, custom favicon, and responsive UI.
- Dedicated routes: `/overview`, `/study`, `/library`, `/analytics`, `/settings`, `/auth`, `/register`, and `/admin/`.
- Unknown URLs return a custom LexiLoop 404 page instead of the SPA shell.

## v1.10.0 changes

### Immediate review persistence

In v1.9.0 a review was saved only when the user moved to the next task. If the user checked an answer or revealed the card and then closed the tab, refreshed the page, or waited too long, the accepted/rejected result could be lost.

v1.10.0 saves the review immediately after:

- semantic judge result is received;
- binary definition → word result is received;
- the user presses **Show answer**.

The **Next task** button now only advances the queue if the review has already been saved. It still has a fallback save path for old browser state or transient network failures. The result area shows **Saved** after persistence succeeds.

### Direct OpenAI API models

Settings now includes direct OpenAI API choices, not only OpenRouter/DeepSeek/MiMo:

- GPT-5.4 mini
- GPT-5.4 nano
- GPT-5 mini
- GPT-5 nano

The router supports the new model prefix:

```text
openai:<model-name>
```

Example internal IDs:

```text
openai:gpt-5.4-mini
openai:gpt-5.4-nano
openai:gpt-5-mini
openai:gpt-5-nano
```

The UI still shows only readable model names and provider descriptions. Users paste an OpenAI API key in Settings, and the raw router ID remains hidden.

### Emerald default color

The default interface accent is now emerald instead of violet:

- unauthenticated first paint defaults to emerald;
- new user profiles default to emerald;
- the accent picker shows emerald first.

Existing users keep their chosen accent.

### Mobile and narrow-width layout

The layout was tuned for real smartphone widths:

- sidebar uses 100% viewport width below 500 px when opened;
- Overview → Your pools no longer overflows the screen;
- pool cards become compact two-column cards on small screens;
- Overview stat cards collapse further below 430 px;
- hero, buttons, Study progress, answer actions, and modal padding are adjusted for narrow mobile screens.

### Migration

v1.10.0 adds migration:

```text
learning.0006_default_emerald_and_openai_catalog
```

It changes the default accent for future `UserProfile` rows to emerald. It does not rewrite existing users.

## Production

Use `scripts/update-production.sh` from the release ZIP. It preserves:

```text
/opt/lexiloop/.env
/opt/lexiloop/.venv/
/opt/lexiloop/backend/media/
PostgreSQL database through pg_dump rollback backup
```

It rebuilds the frontend, runs Django migrations, collects static files, restarts `lexiloop` and `lexiloop-bulk`, validates Nginx, and rolls back automatically on failure.
