# jevsort

Google Photos organizer: local Chrome (CDP) scrapes the library, CLIP + pixel stats turn each photo into text state, Jev (TypeSafe AI) makes typed decisions (album choice + delete noul).

## Setup
- Python 3.12 via uv: `uv sync`
- `.env` must contain `TYPESAFE_API_KEY` (never print it)
- Chrome with debugging on a separate profile (Chrome 136+ refuses CDP on the default profile), then log into photos.google.com in that window:
  `open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.jevathon-chrome"`

## Commands
- `uv run jevsort ping` – one Jev call (checks key/endpoint)
- `uv run jevsort albums` – smoke test: lists existing albums via Chrome
- `uv run jevsort scan --limit 300 --batch 100 --threshold 0.6` – batched in-memory download + classify → `results.jsonl` (resumable)
- `uv run jevsort apply` – dry-run plan; `apply --yes [--tabs 12]` multi-selects each album's photos (one in-page JS call per scroll step) and adds them in one action, albums in parallel tabs (never deletes photos). Writes the undo journal `apply_log.json` (new album paths are recorded the moment Google creates them, before titling) and verifies album item counts afterwards
- `uv run jevsort restore` – dry run of the undo; `restore --yes` deletes albums jevsort created (photos stay in the library) and removes photos it added to pre-existing albums, then archives the journal as `apply_log.restored-<ts>.json`
- `uv run python scripts/demo_set.py [--set N] [--rebuild] [--upload]` – build demo set N (Openverse page N) in /tmp/jevsort-demo[-N] and upload it; Google Photos silently skips byte-identical files

## Performance notes
- Checkbox ticking uses dispatched mouse events in one `page.evaluate` per scroll step (Playwright clicks per tile were the main cost)
- The albums page wait must also accept the empty state ("The albums you create are shown here"), otherwise it burns a 15s timeout
- The scan tab uses a tall 2400x4000 viewport via CDP `Emulation.setDeviceMetricsOverride` (Playwright `set_viewport_size` resizes the real window in headful Chrome); worker tabs don't, because 12 tall tabs overload Chrome
- Blocking thumbnail requests breaks scraping: tiles only get their background-image URL after the image loads
- The albums page item counts lag a few seconds after changes; apply polls before reporting shortfalls
- Under 12-tab load, some clicks time out; restore retries leftovers with fewer tabs

## Layout
- `src/jevsort/models.py` – contract between pipeline and processor
- Pipeline: `photos.py` (Google Photos UI), `pipeline.py` (batching, results, feed), `__main__.py` (CLI)
- Processing: `signals.py` (CLIP, sharpness, exposure, shape, phash), `jev.py` (API client), `processor.py` (state, dupes, decisions)

## Verified Google Photos selectors (Sep 2026, English UI)
- Photo links `a[href*="/photo/"]`, aria-label "Photo - Landscape - <date>", thumbs on `photos.fife.usercontent.google.com` (size suffix `=w512-h512` works)
- Upload: button "Create and add photos" → menuitem "Import photos from your computer"; first upload shows a "Continue" backup-quality prompt
- Multi-select: each tile's `[role=checkbox]` is a sibling of its photo link (`a.parentElement`); clicks can be flaky while the grid re-renders, so verify `aria-checked` and retry
- Add selection: button "Create or add to album" → menuitem "Album" → dialog options; "New album" immediately creates an untitled album and navigates to it (textbox "Edit album name", button "Done"); existing album option names look like "<title> · N items"
- Album page: "More options" → "Delete album" → button "Delete"; with a selection, the last "More options" has "Remove from album"
- Photo ids inside an album grid differ from library ids, so apply snapshots album contents (album-context ids) before touching pre-existing albums, and restore diffs against that snapshot
