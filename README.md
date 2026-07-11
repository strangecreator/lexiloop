# LexiLoop — AI-assisted English flashcards

LexiLoop is a Django + React platform for building and retaining English vocabulary. It combines one-field AI card creation, semantic answer judging, durable high-volume generation, server-side pagination, PostgreSQL storage, HTTPS deployment, and an Anki-inspired review scheduler with a polished responsive interface.

Version **1.13.0** polishes the mobile experience: the Study counter no longer promises a card that was already answered, the vertical activity heatmap fills the width of narrow screens, and the mobile navigation drawer is full-width, scrollable, and locks the page behind it.

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

## v1.13.0 changes

### An honest "done · left" counter

`queue_count` (and the queue chips) are computed with the card currently on screen still in the queue. After an answer was judged and saved, "X done · Y left" still counted that card as left, so finishing the last card read "1 left" and the Next button landed on the caught-up screen. The header and chips now subtract the current card the moment its review is recorded, so the counter always describes what actually remains.

### The vertical heatmap fills narrow screens

The mobile activity grid used fixed 17px cells pinned to the left edge. Cells now scale as squares across the available width (capped at 345px and centered, so tablets keep reasonable proportions).

### A usable mobile navigation drawer

- Phones up to 600px get a full-width drawer (previously only below 500px), and 601–820px screens get a 340px drawer instead of the desktop's 264px.
- The pool list scrolls inside the drawer — without visible scrollbars on mobile — so navigation, theme, Settings, and the account row stay reachable no matter how many pools exist.
- While the drawer is open the page behind it no longer scrolls; before, wheel and touch gestures scrolled the page under the scrim, which was confusing.

## v1.12.0 changes

### The judge saves the review in the same request

When the backend judges an answer (semantic or binary), it now records the review and reschedules the card inside that same request — there is no second round-trip from the browser, and a closed tab right after "Check answer" loses nothing. The response includes `review_recorded` and the new schedule. The separate `/review/` endpoint remains for the reveal path ("Show answer") and as a fallback if the in-request save loses a lock race.

The result footer now always shows the response time after a checked answer; "Saved" appears only on the reveal path, where a client-initiated save still happens.

### An honest, explained progress header

The Study header now reads "X done · Y left" (the old "X of Y completed" total silently grew when a failed card re-entered a learning step). Colored chips show what the remaining queue consists of — new / learning / review — with tooltips explaining each state, so a growing round is visible and understandable. `/api/study/next/` returns the new `queue_breakdown`.

### Vertical activity heatmap on narrow screens

Below 820 px the Overview heatmap renders vertically: weekday columns, weeks as rows with the most recent on top, month labels in the gutter, and a "Show the full year" toggle (recent quarter by default). No more horizontal scrolling on tablets and phones.

### Wide-monitor centering

Overview, Library, and AI usage content is capped at 1100 px and centered — a 1728 px display renders exactly as before; anything larger centers the content instead of stretching it.

### Library page on phones

- The expanded card no longer overflows the screen: the non-wrapping actions row forced the shared grid column of `card-details` ~20% past the viewport; actions now wrap and all children may shrink.
- Toolbar buttons show their labels again instead of icon-only pills.
- The generator input stacks above its button (a later wide-screen rule had squeezed them into one row).

## v1.11.0 changes

### No more multi-minute hangs on Check answer

Judge requests now use a dedicated short timeout (`JUDGE_REQUEST_TIMEOUT_SECONDS`, 30 s) and a hard end-to-end deadline (`JUDGE_TOTAL_DEADLINE_SECONDS`, 40 s). Single-card generation is capped at `GENERATION_TOTAL_DEADLINE_SECONDS` (170 s), below the gunicorn worker timeout. The browser also aborts stalled requests itself (judge 50 s, review save 20 s, generation 180 s) and shows a clear retry message. Timeouts and provider errors are logged to AI usage → Recent failures with their real cause instead of an opaque `AttemptsExceededError`, so provider slowness (for example DeepSeek at peak hours) is now visible and diagnosable.

### One API key per provider

API keys are stored per provider (DeepSeek, OpenAI, OpenRouter, Xiaomi) instead of per role. Switching the generation or judge model to another model of the same provider keeps the saved key. Settings shows a new **Saved API keys** panel with each provider's key state and remove/undo actions. Migration `learning.0007_per_provider_api_keys` moves existing encrypted tokens into the new storage; nothing needs to be re-entered.

### Study-activity heatmap

The Overview page shows a GitHub-style contributions grid of the last year of reviews. Cell tint follows the interface accent color and scales with how many cards were reviewed that day. The grid scrolls horizontally on narrow screens and starts at the most recent week. `/api/overview/` now returns the `activity` series.

### Layout corrections

- The Settings page content is centered between the sidebar and the right edge on large monitors.
- Below 500 px the sidebar previously rendered ~20% wider than the screen (viewport units are multiplied by the global interface zoom), pushing the new-pool and pool-action buttons off-screen. It now spans exactly the screen width.
- The bulk-generation review step no longer collapses the normalized-terms list inside a height-capped modal.
- Keyboard-shortcut hints are hidden on touch devices, and AI-usage headings stack on narrow screens.

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
