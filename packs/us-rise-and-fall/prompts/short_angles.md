You are planning YouTube Shorts that promote a long documentary. Each Short
tells ONE self-contained moment from the story in about 50 seconds and makes
the viewer want the full video.

<channel_brief>
{{channel_brief}}
</channel_brief>

<long_video_title>{{title}}</long_video_title>

<dossier>
{{dossier}}
</dossier>

Propose {{count}} different Shorts. Each must stand alone (a viewer who has
never heard of the subject understands it), be built on one striking fact,
moment or quote from the dossier, and have its own hook. Prefer: a shocking
number, a disaster, a reversal, a "the first/largest ever" record that later
vanished, a first-hand quote.

For each give:
- "title": under 60 characters
- "angle": the one moment this Short tells, in one sentence
- "hook": the first spoken sentence (a number or a name in it, under 18 words)

Return only JSON inside <json></json> tags: {"shorts": [{"title": "", "angle": "", "hook": ""}]}
