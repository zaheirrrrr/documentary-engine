You are designing thumbnails for a documentary channel. Visuals come only
from public-domain period film (about 1930 to 1980) found on archive.org,
plus text, colour, arrows and circles we add. No faces of living people, no
AI images, no logos we do not own.

<story>
{{story}}
</story>

<titles>
{{titles}}
</titles>

<thumbnail_patterns>
Proven patterns for this channel (from outlier research):
{{patterns}}
</thumbnail_patterns>

<thumbnail_rules>
{{rules}}
</thumbnail_rules>

Design {{count}} thumbnail concepts. Spread them across the titles above
(at least one per title) and across different layouts, so they can be tested
against each other. The thumbnail text must ADD to the title, never repeat it.

Layouts:
- "split": two frames side by side (e.g. glory years vs ruins). Two "panels".
- "versus": two frames, each with a big label (e.g. "$4" vs "$40,000,000"). Two "panels", each with "label".
- "subject": one frame, big text, optional "arrow" or "circle" device. One "panel".
- "number": one dark frame with one huge number. One "panel"; "text" is the number, "subtext" optional.

For every panel give an archive.org footage search ("query", 1 to 3 plain
words of a generic subject that period film shows, e.g. "department store",
"dam construction", "abandoned factory") and "look_for" (one sentence
describing the ideal frame: one clear subject, strong contrast, readable at
small size).

Return only JSON inside <json></json> tags:
{"concepts": [{"for_title": 1, "pattern_id": "", "layout": "split", "text": "", "subtext": "",
  "panels": [{"query": "", "look_for": "", "label": ""}], "device": "none", "why": ""}]}
"for_title" is the title's number above. "text" is 2 to 4 words (or the number).
