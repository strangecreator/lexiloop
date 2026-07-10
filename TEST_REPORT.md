# LexiLoop verification report — v1.10.0

Verified in the artifact environment with static checks. Full Django runtime checks, npm installation, TypeScript compilation with real React types, and Vite production build are performed by the production updater on the Ubuntu server because this isolated artifact environment does not include the project virtualenv or frontend `node_modules`.

| Check | Result |
|---|---:|
| Python bytecode compilation for backend and router | Passed |
| Shell-script syntax checks | Passed |
| New Django migration file presence | Passed |
| Direct OpenAI router provider presence | Passed |
| Public model catalog marker check | Passed |
| Immediate Study review persistence marker check | Passed |
| Emerald default marker check | Passed |
| Mobile sidebar 100% width CSS marker check | Passed |
| Narrow Overview pool-card CSS marker check | Passed |
| ZIP integrity | Passed |
| Unwanted-file scan | Passed |

## Changes validated statically

- `Study` records the review immediately after judge result or answer reveal.
- `Next task` no longer needs to be the first place where review persistence happens.
- The frontend keeps a duplicate-save guard for the current card.
- The result footer displays `Saved` after the backend accepted the review.
- Direct OpenAI model IDs are in the model catalog.
- The router has an `openai:` regex provider and posts to the OpenAI-compatible chat-completions endpoint.
- GPT-5-style OpenAI requests remove optional `temperature` to avoid strict-parameter failures.
- `UserProfile.accent_color` default is emerald in code and in migration `0006`.
- The first-paint accent bootstrap in `index.html` falls back to emerald.
- Mobile sidebar width becomes `100vw` below 500 px.
- Overview pool cards have explicit narrow-screen overflow protection.

## Runtime validation required after deployment

Run these on the server after updating:

```bash
systemctl is-active lexiloop lexiloop-bulk
sudo -u lexiloop -H bash -lc 'cd /opt/lexiloop/backend && ../.venv/bin/python manage.py check'
sudo -u lexiloop -H bash -lc 'cd /opt/lexiloop/backend && ../.venv/bin/python manage.py showmigrations learning'
curl -I https://lexiloop.ru/study
curl -I https://lexiloop.ru/settings
```

Then test in the browser:

1. Open Study.
2. Check an answer.
3. Confirm the result area shows `Saved` before pressing **Next task**.
4. Refresh the page and verify the same card is not offered again as if it had never been reviewed.
5. Open Settings and choose a direct OpenAI model.
6. Test the site at widths around 390–430 px and below 500 px with the sidebar open.
