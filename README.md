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
| 2 | concept | **Title and thumbnail first.** ~24 titles adapted from proven outlier formulas, filtered by the title checker, judged like a viewer scrolling the feed, ranked; thumbnail concepts designed for the top titles. | `packaging.json`, `packaging.md` |
| 3 | outline | 5 cold-open hooks, scored against the hook checklist; chapter plan that pays off the chosen title's promise. | `outline.json`, `outline.md` |
| 4 | script | Full narration in the pack's style. Scored by the script checker (hooks, re-hooks, anti-AI writing rules, banned patterns) and rewritten until it scores 90+ with no hard fails. | `script.md`, `script_check.md` |
| 5 | factcheck | Every claim checked against the dossier; exact fixes applied; leftovers listed. | `factcheck.md` |
| 6 | **review_script** | **You** read and edit `script.md`, then `de approve`. | |
| 7 | shotlist | Script split into 6–10 s beats in code (no words lost); Claude picks a visual per beat. | `shotlist.json` |
| 8 | narration | VoiceStudio (local) or ElevenLabs, one chapter per call, with character timestamps. | `narration.wav`, `timing.json`, `captions.srt` |
| 9 | footage | archive.org search (licence-filtered), 3-frame contact sheets, Claude vision picks the fitting clip, clip cut with no audio. | `footage/clips/`, `footage.json`, `credits.json` |
| 10 | render | Clips framed over blurred fill, vintage grade, grain, quote and number cards, chapter titles, music ducking, −14 LUFS. | `final.mp4` |
| 11 | package | Titles, thumbnail text, description with chapters + sources + footage credits, tags, pinned comment. | `upload_pack.md`, `description.txt` |
| 12 | thumbnail | Each concept gets frames found on archive.org for its brief, is drawn in its layout (split, versus, subject, number), checked at phone size, and judged by Claude; the best 3 different ones are ready for Test & Compare. | `thumbnails/thumb1-3.jpg`, `thumbnails.md` |
| 13 | qa | Length, streams, black frames, loudness, fallbacks, open fact-check items. | `qa.md`, `review.html` |
| 14 | **review_final** | **You** watch `review.html`, then upload by hand. | |

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
- **Narration**, one of:
  - **VoiceStudio** (`TTS_PROVIDER=voicestudio`, the default): free and local.
    Install the [VoiceStudio](https://github.com/debpalash/VoiceStudio) app,
    keep it open, and set `VOICESTUDIO_VOICE` to a voice profile made in it.
    Word timings come from VoiceStudio's own transcription of each chapter.
  - **ElevenLabs** (`TTS_PROVIDER=elevenlabs`): `ELEVENLABS_API_KEY` and the
    `ELEVENLABS_VOICE_ID` of the narrator voice.

Optional: put royalty-free music in `packs/<pack>/music/` with a
`credits.txt` (one credit line per track). Videos render without music too.

## Daily use

```bash
de trends                              # refresh the packaging library (every ~2 weeks)
de discover --count 10                 # propose + score topics
de topics --detail                     # read them
de pick 4 --run                        # research → title → script, stops for your review
# read packaging.md (title ranking) and script.md; edit either if you want
de approve 1 --run                     # narration → footage → render → QA
de review 1 --open                     # watch the video, read the upload pack
de approve 1                           # final sign-off
# upload final.mp4 by hand using upload_pack.md
de published 1 https://youtu.be/...
de notes 1 "Retention dipped at 4:10, chapter 3 too slow"
```

Other commands: `de shorts <id> --run`, `de status [id]`, `de redo <id> --from footage --run`,
`de new "My own topic" --wikipedia "Exact article" --era 1890-1930 --run`,
`de usage`, `de new-pack <name>`.

## Shorts

Each long video can feed 2 to 3 vertical Shorts that pull viewers to it:

```bash
de shorts 1 --run        # plans 3 Shorts from video 1's research, writes and renders each
```

Each Short is its own project: about 50 seconds, one moment from the story,
a hook in the first 3 seconds (also shown as on-screen text so it works on
mute), a new shot every ~3 seconds, one-word captions burned in, ending on
the last word. It stops at the script review and the final review like a
long video. Settings live under `shorts:` in `pack.yaml`.

## Script checker

`engine/scriptcheck.py` scores narration out of 100 (hard fails cost 15,
soft flags 5; pass = 90+ with no hard fails). Hard fails: em dashes,
semicolons, "it's not X, it's Y", "not just X but Y", filler and stage
directions, fake suspense, AI vocabulary, more than one one-word sentence,
parallel repetition stacks. Soft flags: length, a weak first sentence, long
sentences, rhetorical questions in the body, gaps with no re-hook, no ask at
the end. Quote blocks are excluded (historic text keeps its punctuation).

## Packaging research: what makes people click

```bash
de trends        # every ~2 weeks
```

1. Pulls ~60 recent videos from each channel in `packaging.reference_channels`
   (leaders across niches: MrBeast, Veritasium, Johnny Harris...) and
   `packaging.niche_channels` (business, engineering, history channels).
2. Keeps the **outliers**: videos that beat their own channel's median views
   by 2x or more. That isolates packaging that worked, not channel size.
3. **Titles:** Claude reverse-engineers reusable formulas ("$[small] vs
   $[huge] [thing]", "Why [familiar thing] Disappeared") and adapts each to our
   stories. Each formula's strength is then measured in code from the real
   outlier multiples of the titles it cites, so nothing is taken on faith.
4. **Thumbnails:** the top outlier thumbnails are tiled into numbered grids
   and tagged by Claude vision (layout, words, devices, emotion, contrast).
   Tags are counted, weighted by outlier multiple, and turned into thumbnail
   patterns we can build from period footage.
5. **Topics:** niche outliers are grouped into themes that are over-performing
   now, with topic ideas; `de discover` leans on them.

Output: `workspace/research/library.md` (read it, it's a playbook) and
`library.json`, which the concept and thumbnail stages use on every video.

Data: a free `YOUTUBE_API_KEY` (read-only public data) or, with no key,
`yt-dlp`. Edit the channel lists in `pack.yaml`; any handle that can't be
found is listed at the top of library.md.

Check your own title ideas any time: `de titles "Title one" "Title two"`.

## Topic scoring

`de discover` combines Claude's judgement with two signals it cannot invent:
- **Familiarity**: last 12 months of Wikipedia page views for the subject.
- **Footage**: how many licence-approved films match the topic's footage keywords.

- **Trend**: the best of three: fit with a theme over-performing right now
  (from `de trends`), a Wikipedia interest spike in the last two months, or a
  round anniversary (25th, 50th, 100th...) in the next six months.

Score = 25% story arc + 10% novelty + 15% source depth + 15% familiarity + 20% footage + 15% trend.

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

## Claude skills

`.claude/skills/` holds two skills that Claude Code loads when opened in this
repo: `viral-video-writing` (writing and breaking down video scripts) and
`famous-reel-editor` (editing talking-head reels). See THIRD_PARTY.md.
