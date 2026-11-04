# Notes for Claude Code

This repo is a documentary video pipeline. Read README.md first.

## Rules
- The engine (`engine/`) must stay niche-agnostic. Anything about a channel's
  topics, tone, sources or prompts belongs in `packs/<name>/`.
- Stages are `engine/stages/<name>.py` with a single `run(ctx)` function. They
  read inputs from the project folder and write outputs there. The order and
  the human gates live in `engine/pipeline.py` (`STAGES`).
- Content files on disk are the source of truth; SQLite only tracks status
  and usage. Never make a stage depend on in-memory state from another stage.
- Write files atomically (`util.write_json`, `util.write_text`).
- Network calls go through `util.retry`; raise `util.PermanentError` for
  failures a retry cannot fix (bad key, 4xx).
- The footage stage must never stop the render: missing footage falls back to
  a card.
- Never weaken the licence filter in `engine/sources/archive_org.py`.
- Never let the model rewrite script text after the human script approval;
  `shotlist` splits the approved script in code.

## Testing
`pytest` runs unit tests and `tests/test_end_to_end.py`, which renders a real
video with FFmpeg using simulated Claude, ElevenLabs and archive.org. Run it
after any change to scriptdoc, narration, footage, render, package or qa.
