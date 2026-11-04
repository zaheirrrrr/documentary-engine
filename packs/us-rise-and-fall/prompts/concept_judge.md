You are judging YouTube titles for a documentary channel the way a
viewer scrolling their home feed would, while protecting the channel's
credibility.

<channel_brief>
{{channel_brief}}
</channel_brief>

<story>
{{story}}
</story>

<candidates>
{{candidates}}
</candidates>

Score every candidate 1 to 10 on:
- "clarity": a stranger knows what the video is about in one glance
- "curiosity": the gap is strong enough that not clicking feels like missing out
- "specificity": a concrete number, name, place or record makes it real
- "stakes": something big was won, lost, built or destroyed
- "truth": the story fully pays it off (10) or it oversells (1)
- "fit": calm, credible, never cheap (the channel's tone)

Then "overall" (1 to 10): how likely a curious adult would click it over the
other videos on their home page, given that truth below 7 disqualifies it.

Return only JSON inside <json></json> tags:
{"scores": [{"i": 1, "clarity": 8, "curiosity": 9, "specificity": 7, "stakes": 8, "truth": 9, "fit": 8, "overall": 8.5, "note": ""}]}
Use the candidate numbers given above for "i".
