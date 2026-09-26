# Contributing to jevsort

Thanks for helping. By contributing you agree that your work is released under the MIT license (see
`LICENSE`) and that you will follow the [code of conduct](CODE_OF_CONDUCT.md). Report security issues
privately as described in [SECURITY.md](SECURITY.md), not in public issues.

## Development setup

Requirements: macOS, Google Chrome, [uv](https://docs.astral.sh/uv/) and a TypeSafe API key.

Run `uv sync`, then create `.env` in the repo root containing `TYPESAFE_API_KEY=<your key>` (it is
gitignored; never commit or print it). Start the debugging Chrome:

```sh
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.jevathon-chrome"
```

Log into [photos.google.com](https://photos.google.com) in that Chrome window once (English UI). Chrome
136+ refuses remote debugging on the default profile, hence the separate `--user-data-dir`.

## Testing safely

There is no automated test suite yet; changes are checked by hand against a real library.

- Use a spare Google account with a throwaway library, e.g. the one built by
  `uv run python scripts/demo_set.py --upload`, never your personal library.
- `uv run jevsort --help` needs no browser or key. `ping` makes one (paid, tiny) Jev call; `albums` only reads.
- `scan --limit 20` keeps runs short. `apply` and `restore` without `--yes` are dry runs; only `--yes`
  changes Google Photos. Run `restore --yes` after testing `apply --yes`.
- Never commit `.env`, `results.jsonl` or `apply_log*.json`: they hold your key, photo ids, dates,
  thumbnail URLs and album names. Only the default file names are gitignored, so take extra care with
  custom `--results` or `--log` paths.

## Code style

No formatter or linter is configured; match the surrounding code.

- Keep modules small and compact, with type hints on signatures and dataclasses.
- Browser work uses async Playwright (`playwright.async_api`) over CDP; bound concurrency with
  `asyncio.Semaphore` and move CPU-heavy work (CLIP) off the event loop with `asyncio.to_thread`.
- Locate Google Photos elements by role, accessible name and stable attributes (`get_by_role(...)`,
  `aria-label`, `aria-checked`, `[role=checkbox]`, `a[href*="/photo/"]`), never by Google's generated
  CSS class names.
- `src/jevsort/models.py` is the contract between the pipeline and the processor (`PhotoRef`,
  `FetchedPhoto`, `Decision`, `Processor`). Change it deliberately and keep both sides in sync.
- Keep photos in memory only: never write images to disk, and don't retain them after `process()`
  returns. Send Jev text signals only, never pixels or image URLs.
- Never delete photos. Any new change to Google Photos must be recorded in the undo journal and
  reversible by `restore`.

## Google Photos UI changes

jevsort automates the Google Photos web UI, which Google can change at any time and break the
selectors. The verified selectors and flows are listed under "Verified Google Photos selectors" in
`AGENTS.md`; update that list when you fix or add one.
