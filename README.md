# Documentary Engine

Turns a topic into a review-ready long-form documentary video: research
dossier, fact-checked script, narration, public-domain archival footage,
rendered MP4, captions, thumbnails and an upload pack. A person approves the
script and the final video, then uploads by hand.

The engine is niche-agnostic. Everything specific to a channel lives in a
**niche pack** (`packs/<name>/`). The first pack is `us-rise-and-fall`: the
rise and fall of America's great builds and businesses.

## How a video is made

| # | Stage | What happens | Output |
|---|---|---|---|
| 1 | research | Wikipedia + Library of Congress newspapers + Claude web search. Every quote is checked word for word against the fetched source. | `dossier.json`, `dossier.md`, `sources.json` |
| 2 | outline | 5 cold-open hooks, scored; best one chosen. Chapter plan with turning lines. | `outline.json`, `outline.md` |
| 3 | script | Full narration in the pack's style, inside the word budget. | `script.md` |
| 4 | factcheck | Every claim checked against the dossier; exact fixes applied; leftovers listed. | `factcheck.md` |
| 5 | **review_script** | **You** read and edit `script.md`, then `de approve`. | |
| 6 | shotlist | Script split into 6–10 s beats in code (no words lost); Claude picks a visual per beat. | `shotlist.json` |
| 7 | narration | ElevenLabs, one chapter per call, with character timestamps. | `narration.wav`, `timing.json`, `captions.srt` |
| 8 | footage | archive.org search (licence-filtered), 3-frame contact sheets, Claude vision picks the fitting clip, clip cut with no audio. | `footage/clips/`, `footage.json`, `credits.json` |
| 9 | render | Clips framed over blurred fill, vintage grade, grain, quote and number cards, chapter titles, music ducking, −14 LUFS. | `final.mp4` |
| 10 | package | Titles, thumbnail text, description with chapters + sources + footage credits, tags, pinned comment. | `upload_pack.md`, `description.txt` |
| 11 | thumbnail | Three drafts from the sharpest, highest-contrast frames. | `thumbnails/` |
| 12 | qa | Length, streams, black frames, loudness, fallbacks, open fact-check items. | `qa.md`, `review.html` |
| 13 | **review_final** | **You** watch `review.html`, then upload by hand. | |

Every stage is checkpointed in SQLite. A crash or a closed laptop costs at most
the stage that was running: `de run <id>` resumes there. Network calls retry
with backoff; a beat with no usable footage falls back to a card instead of
stopping the render.

## Setup

Requirements: Python 3.10+, FFmpeg.

```bash
git clone <this repo> && cd documentary-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env        # then fill in the keys
de doctor                   # checks keys, FFmpeg, and every source
```

Keys:
- **Claude**: `ANTHROPIC_API_KEY` from console.anthropic.com (`LLM_PROVIDER=api`),
  or `LLM_PROVIDER=claude-code` to run through the `claude` CLI on a Claude
  Code plan.
- **ElevenLabs**: `ELEVENLABS_API_KEY` and the `ELEVENLABS_VOICE_ID` of the
  narrator voice.

Optional: put royalty-free music in `packs/<pack>/music/` with a
`credits.txt` (one credit line per track). Videos render without music too.

## Daily use

```bash
de discover --count 10                 # propose + score topics
de topics --detail                     # read them
de pick 4 --run                        # research → script, stops for your review
# edit workspace/projects/0001-.../script.md if you want
de approve 1 --run                     # narration → footage → render → QA
de review 1 --open                     # watch the video, read the upload pack
de approve 1                           # final sign-off
# upload final.mp4 by hand using upload_pack.md
de published 1 https://youtu.be/...
de notes 1 "Retention dipped at 4:10, chapter 3 too slow"
```

Other commands: `de status [id]`, `de redo <id> --from footage --run`,
`de new "My own topic" --wikipedia "Exact article" --era 1890-1930 --run`,
`de usage`, `de new-pack <name>`.

## Topic scoring

`de discover` combines Claude's judgement with two signals it cannot invent:
- **Familiarity**: last 12 months of Wikipedia page views for the subject.
- **Footage**: how many licence-approved films match the topic's footage keywords.

Score = 30% story arc + 15% novelty + 15% source depth + 20% familiarity + 20% footage.

## Footage and copyright

- Sources: archive.org collections listed in `pack.yaml` (Prelinger Archives,
  FedFlix US government films, the same material destockd.com indexes).
- Accepted: public domain, CC0, CC-BY, CC-BY-SA, and items in collections
  marked `trusted` (US federal works, 17 U.S.C. § 105). NC and ND licences are
  always rejected.
- Source audio is always stripped (avoids audio Content ID matches), and every
  clip is reframed and graded.
- Every film used is credited in the description with its archive.org link.
- Upload as **Private** first and wait for YouTube's copyright check before
  publishing. Public-domain footage does get false claims; dispute them with
  the archive.org link from the credits.

## A new niche

```bash
de new-pack ww-shipping-history
```
Edit the new folder: `pack.yaml` (topics, sources, footage collections,
length, voice), `channel_brief.md`, `style_guide.md`, `dossier_template.md`,
and the prompts. Then set `DE_PACK=ww-shipping-history`. The engine does not
change.

## Layout

```
engine/            the engine (no niche knowledge)
  stages/          one file per stage
  sources/         wikipedia, chronicling america, archive.org
packs/<name>/      a niche pack: brief, style, dossier template, prompts
workspace/         projects, cache and database (git-ignored)
tests/             unit tests + a full end-to-end render with simulated services
```

Run tests: `pip install -e .[dev] && pytest`.
