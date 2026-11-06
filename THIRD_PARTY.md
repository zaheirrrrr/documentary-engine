# Third-party material

## Claude skills in `.claude/skills/`
Installed for use with Claude Code inside this repo. They are not part of the
engine and are not owned by this project.

- `viral-video-writing/`: script-writing rules and a checker. Its rules are
  adapted into `engine/scriptcheck.py` and the pack's `style_guide.md`.
- `famous-reel-editor/`: talking-head reel editor, built by Riccardo
  (Martes AI). Its caption style is adapted into `engine/karaoke.py`. The
  placeholder background track was left out; supply your own licensed music.

**Before selling or redistributing this repo**, remove `.claude/skills/` or get
permission from the skills' authors. The engine runs without them.

## Fonts
- `packs/us-rise-and-fall/fonts/Montserrat-VariableFont_wght.ttf`: Montserrat,
  SIL Open Font License 1.1 (free to bundle and redistribute).

## VoiceStudio (optional narration provider)

[debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio) is licensed
AGPL-3.0. The engine does not include or modify any of its code: it talks to a
separately installed VoiceStudio app over its local HTTP API, the same way it
talks to ElevenLabs. Buyers install VoiceStudio themselves. Do not bundle
VoiceStudio's code or binaries inside a sold copy of this engine without
meeting the AGPL's terms. VoiceStudio adds an invisible "synthetic speech"
watermark to generated audio.
