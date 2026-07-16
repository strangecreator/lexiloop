# LexiLoop — AI-assisted English flashcards

LexiLoop is a Django + React platform for building and retaining English vocabulary. It combines one-field AI card creation, semantic answer judging, durable high-volume generation, server-side pagination, PostgreSQL storage, HTTPS deployment, and an Anki-inspired review scheduler with a polished responsive interface.

Version **1.24.0** fixes bulk generation on PostgreSQL (every item failed with "No valid response was returned for this item") and gives each study task type a quiet diagonal-tape texture on the card topline so tasks are distinguishable at a glance.

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

## v1.24.0 changes

### Bulk generation fixed on PostgreSQL

Since `BulkGenerationJob.pool` became nullable, the bulk worker's `select_for_update().select_related('job__pool', …)` produced a LEFT OUTER JOIN that PostgreSQL refuses to lock ("FOR UPDATE cannot be applied to the nullable side of an outer join"). The exception escaped the item's error handling, was swallowed by the results reader, and every item decayed into the generic "No valid response was returned for this item" — even though the model responses on disk were valid. SQLite ignores row locks, which is why the test suite never caught it. The worker now locks only the item row and fetches the job separately (the same split `views._record_review` already uses), and a persistence failure is recorded on the item instead of being silently swallowed.

### Task-type texture

`.card-topline` carries a per-task class: Word → sentence gets quiet 45° diagonal bands in the border tone, Definition → word the mirrored 135° variant, and Word → definition stays plain. Texture instead of color keeps it visible at a glance without shouting, and future task types can pick their own pattern.

## v1.23.0 changes

### Per-device task types

`GET /api/study/next/` accepts `?directions=` (comma-separated `term_to_definition`, `definition_to_term`, `term_to_sentence`). When present, the served task rotates through that set instead of the profile's `study_directions`; unknown names are dropped and a fully invalid value falls back to the profile. Reviews are recorded identically either way, so scheduling and progress stay in sync across devices. Added for the Android app, where typing a full definition is harder than on a keyboard.

## v1.22.0 changes

### Per-device review timing

`POST /api/study/{id}/judge/` and `POST /api/study/{id}/review/` accept optional `easy_seconds` and `good_seconds` fields. When both are present and sane (easy 1–600, good 2–900), the automatic Easy/Good/Hard rating uses them instead of the profile bands; anything else silently falls back to the profile. The web app keeps using the account bands — the fields exist for devices where typing speed differs (the Android client sends its device-local bands).

### Per-device image prefetch

`GET /api/study/next/` accepts `?prefetch=N` (0–10) to override `image_prefetch_count` for the `upcoming_images` list of that response. Without the parameter, the profile value applies as before.

## v1.21.0 changes

### Task types as checkboxes

Settings → Study experience now offers three independent checkboxes — Word → definition, Definition → word, Word → sentence — instead of a "one or mixed" select. Due cards rotate deterministically through the enabled set; at least one type always stays on. The sentence task is unchecked by default. The migration converts existing profiles (`mixed` becomes the two classic tasks, keeping sentences opt-in; a single selection stays itself); `study_direction` is replaced by the `study_directions` list in the API.

### Auto-reveal removed

The "Auto-reveal at" thresholds dated from the old two-step study flow. Since checking an answer already shows the full card, `should_reveal` controlled nothing — both sliders, both profile fields, and the response flag are gone.

## v1.20.0 changes

### Word → sentence task

The learner sees a word and writes one original sentence using it. A dedicated LLM judge grades usage on a fixed 1–7 rubric — meaning first, then whether the context actually demonstrates the meaning, then the word's grammar and collocations — and includes a corrected version of flawed sentences in its feedback. Settings gains a **Sentence judge** section (model — defaults to the definition judge — accept score, auto-reveal threshold), a third **Automatic review timing** band (Easy < 20s, Good < 60s by default), a per-task image switch, and the "Word → sentence" option in Card direction. Mixed direction rotates deterministically through all three tasks. Sentence-judge calls appear in AI usage as "Sentence judging".

### A definition-judge rubric that uses the whole scale

The old anchors made 4 ("genuinely ambiguous or too vague to decide") describe judge-uncertainty rather than answer quality, and 7 ("exact and complete") read as verbatim-only — so judges practically never awarded either. The new scale is a quality continuum: 4 = half right (core idea recognizable, an important aspect missing or off), 7 = fully correct and precise **regardless of wording**, plus explicit calibration rules ("if deciding between 3 and 5, it's a 4"; "award 7 for complete meaning even when short or informal"). Verified with live DeepSeek probes: casual-but-exact answers now earn 7 and half-answers earn 4 on both judges. Verdicts gain `half_right` and `perfect`.

### Animation defaults

Morning mist, Ripple, and Slow drift all default to 2.5 seconds (watercolor droplets keeps its slow 8s).

## v1.19.0 changes

### Comfortable number fields

All numeric inputs (animation durations, prefetch depth, daily new cards, review timing thresholds, scheduler tuning, bulk concurrency) previously clamped every keystroke against the controlled value, so clearing the field or deleting the first digit instantly snapped the old number back. They now hold free text while focused — valid keystrokes update state immediately, and the display settles to the last valid value on blur.

### Un-clipped pool actions menu

Below 1050px the off-canvas sidebar always carries a CSS transform (which makes it the containing block for `position: fixed`) and scrolls its own overflow, so the pool context menu was mispositioned and truncated inside the panel. The menu now renders in a portal at the document body and floats freely at every width.

### Droplets is opt-in

Watercolor droplets moved to the end of the Reveal animations list, is unchecked by default (existing untouched defaults are migrated; customized selections are preserved), and defaults to 8 seconds when enabled.

## v1.18.0 changes

### Claude models via the direct Anthropic API

The router supports the `anthropic:` prefix (`https://api.anthropic.com/v1/messages`). Settings offers **Claude Haiku 4.5** (fast, cheap — a great judge), **Claude Sonnet 5** (balanced), and **Claude Opus 4.8** (most capable) under a new Anthropic API key provider. The provider handles Anthropic's payload shape (top-level `system`, required `max_tokens`) and strips sampling parameters on models that reject them.

### Animation and prefetch controls

- Each reveal animation in Settings → Card images now has a **duration** field (0.5–30s).
- **Prefetch upcoming images** controls how many of the next flashcards' images load in advance (0–10, default 2 — as before).

### Fixes and polish

- The reveal animation plays on **every** "Next task": prefetched cards resolved so fast that the visual layer never re-rendered, so roughly half the reveals skipped their animation. The layer is now remounted per card.
- Watercolor droplets are gentler: drops swell steadily out of a soft haze that sharpens over the run (default 5.2s) instead of appearing abruptly.
- Light mode: the recall-hints box is a frosted panel over the image, keeping collocation chips and example sentences dark and readable.
- Overview shows a loading spinner until data arrives instead of flashing zeros.
- Library card images were confirmed lazy — a card's image loads only when that card is expanded.

## v1.17.0 changes

### Organic reveal animations

The flashcard image now surfaces with one of four soft, curve-only animations — **watercolor droplets** (staggered feathered drops soak through the blurred placeholder and merge until the picture is wet through), **ripple**, **morning mist**, and **slow drift**. Each is built from feathered radial masks with no straight edge anywhere. Settings → Card images has a checkbox per animation; a card keeps one of the checked ones, and unchecking all leaves a plain fade. `prefers-reduced-motion` still gets a fade.

### Smarter presentation

- **Portrait images** are no longer force-cropped: on screens above 560px they float beside the prompt text as a soft-edged pane over the blurred ambience (phones keep full-bleed, where portrait fits naturally).
- **Bright images** get a deeper text veil: the tiny placeholder's average luminance is measured client-side, so white prompt text stays readable in light mode.
- Per-direction switches control where images appear (word → definition and definition → word tasks separately — a picture can hint at the answer during recall).

### Fixes

- Replacing a card's image no longer shows the previous picture's blurred placeholder: image requests carry a version parameter, so the browser's immutable HTTP cache can't serve stale bytes.
- "Study prompt" wording is now "flashcard" everywhere; queue chips use the default cursor; the answer textarea disables native styling and inner scrollbars (Safari squared its right corners); the answer block gets breathing room below an image.

## v1.16.0 changes

### Flashcard images

A card can carry an optional picture, managed from the expanded library card or straight from the study page (the image button in the card's top line). Three ways in:

- **Upload** any image file (up to 12 MB; re-encoded to JPEG, metadata stripped).
- **Paste a link.** Direct image URLs download as is; Yandex/Google/Bing image-search result links are unwrapped to the real file automatically.
- **AI-assisted lookup.** When the pasted link is a web page rather than a picture, the backend reads the page's meta and `<img>` candidates and asks the *image assistant* model to point at the right file. The model is chosen in Settings → Card images (defaults to the generation model, sharing its provider key); its calls appear in AI usage as "Image lookup".
- **Copied search links.** A Yandex selected-image link (`ya.ru`/`yandex.*` with `img_url=`) resolves to the exact chosen picture. A copied Google Images link identifies the selection only by an internal id inside a JavaScript-rendered page, so the exact image cannot be recovered; instead the assistant rewrites the search text using the card's sense (dropping meta words like "noun"), retrieves candidates from the keyless Openverse and Wikimedia Commons APIs, and picks the best illustration — or refuses when nothing fits.

Server-side downloads are SSRF-guarded (no private addresses), size-capped, and validated as real images.

### A cinematic study reveal

The study prompt becomes the card's picture: first a tiny blurred thumbnail surfaces, then the full image reveals with one of four cinematic animations — emerge, ken-burns, iris, or tide — chosen deterministically per card, under a gradient scrim that keeps the prompt text readable. Upcoming queue cards' images are prefetched (`upcoming_images` in `/api/study/next/`), so the reveal is instant, and `prefers-reduced-motion` falls back to a plain fade. A Settings toggle hides images during study without deleting them.

### Neutral queue chips

The new/learning/review chips in the Study header now use the same muted grey as the round label instead of competing colors.

## v1.15.0 changes

### A calmer scale on small phones

The survey-driven 120% interface zoom is desktop comfort; on ≤450px screens it inflated text and controls and consumed ~17% of an already narrow viewport. Those screens now render at 105%: body text lands at an effective 13–15px (within mobile typography guidelines), captions stay above 10px, and layouts gain roughly 12% more horizontal room. The zoom-compensated viewport-height rules (`min-height` chain, modal `max-height`) get matching 100/1.05 overrides in the same breakpoint, and screens 451px and wider are unchanged.

## v1.14.0 changes

### Absolute heatmap brightness

Cell tint previously scaled against the user's own busiest day of the year, so 2 reviews on a quiet account already rendered at full brightness. Levels now use fixed cutoffs — 1–9, 10–49, 50–119, and 120+ reviews per day — and hovering the legend squares shows each range.

### One scroll region in the sidebar

The pool list no longer scrolls inside the panel; the entire sidebar scrolls naturally on desktop (thin scrollbar) and mobile (no scrollbar).

### Smaller fixes

- AI usage → Recent failures no longer clips error bodies at 30px; messages wrap in full.
- The library search field stays full-width below 431px (the two-column action grid had trapped it in one column).
- Cmd/Ctrl+Enter submits both stages of the bulk popup — "Normalize list" and "Start job" — even when the form has no focus.
- Term chips in the bulk review step keep their natural height when they fit on one line.

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
