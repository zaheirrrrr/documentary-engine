You are designing the thumbnail system for a documentary channel.

<our_channel>
{{channel_brief}}
</our_channel>

Our visuals are limited to public-domain period film and photographs
(roughly 1930 to 1980), plus text, shapes and colour we add. We cannot use
faces of living people, AI-generated people, or footage we do not have.

Here is what top outlier thumbnails across YouTube have in common (counts
weighted by how far each video beat its channel's normal):

<feature_stats>
{{stats}}
</feature_stats>

<examples>
{{examples}}
</examples>

Turn this into 6 to 8 thumbnail patterns our channel can build. Each must
map to one of our layout templates:
- "split": two period frames side by side with a divider, e.g. the glory
  years against the ruins (rise and fall in one image)
- "versus": two panels with a price or number label on each, the
  "$1 vs $1,000,000" contrast format
- "subject": one strong period frame, 2 to 4 words of big text, optional
  arrow or circle on the key detail
- "number": one striking number over a dark period frame

For each pattern give: "id", "layout" (one of the four), "name",
"when_to_use", "why_it_works" (tie it to the stats), "text_rule" (how many
words and what kind), "frame_brief" (what the period footage must show),
"devices" (arrow, circle, red_x or none) and "example_text".

Also give "rules": 8 to 10 thumbnail rules for this channel, and "avoid".

Return only JSON inside <json></json> tags:
{"patterns": [{"id": "", "layout": "split", "name": "", "when_to_use": "", "why_it_works": "", "text_rule": "", "frame_brief": "", "devices": [""], "example_text": ""}],
 "rules": [""], "avoid": [""]}
