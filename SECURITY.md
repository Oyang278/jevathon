# Security policy

## Reporting a vulnerability

Please don't open a public issue. Contact the maintainers listed in `LICENSE` (Olivia Yang, Stanley Zhu
and Daniel Kao) privately with a description, steps to reproduce and the affected version or commit. We
aim to acknowledge reports promptly and to coordinate a fix before any public disclosure. Only the
latest version on the main branch is supported.

## Security and privacy model

- **API key**: `TYPESAFE_API_KEY` is read from the gitignored `.env` (or the environment), sent only as a
  bearer token to the Jev endpoint and never printed or logged.
- **Photos**: thumbnails are downloaded at 512px through your browser session, held in memory for one
  batch and never written to disk. CLIP and the pixel statistics run locally.
- **What Jev sees**: only text signals: the Google Photos label (photo type and date), shape, sharpness,
  exposure, CLIP labels, junk and near-duplicate scores, plus your album names as answer options. No
  pixels or image URLs are sent.
- **Local files**: `results.jsonl` and `apply_log*.json` contain photo ids, dates, thumbnail URLs and
  album names. They are gitignored; treat them as private.
- **Browser access**: jevsort acts through your own logged-in Google session, so it has the same access
  to your Google account as you do. It never deletes photos; `restore --yes` only deletes albums jevsort
  created (their photos stay in the library) and removes photos it added to existing albums.
- **Debugging port**: Chrome's remote debugging port (9222) listens on localhost only, but while that
  Chrome is running any local user or process can drive it and your logged-in account. Use the separate
  profile only for jevsort and quit it when you are done.
