You are the story editor for a documentary channel. Plan the video.

<channel_brief>
{{channel_brief}}
</channel_brief>

<style_guide>
{{style_guide}}
</style_guide>

<dossier>
{{dossier}}
</dossier>

Target length: about {{target_words}} words of narration, in {{chapters_min}} to {{chapters_max}} chapters.

Step 1. Write 5 different cold opens (each 120 to 180 words) following the
style guide. Vary the entry point: a record, a moment of crisis, a number, a
person, a scene from a first-hand account. Score each 1 to 10 on how strongly
it makes a viewer need to keep watching, and pick the best.

Step 2. Plan the chapters. For each chapter give: a short title, its job in
the arc, the key beats in order, which dossier quotes it uses (copy the quote
text exactly), the key numbers it uses, its target word count, and the exact
turning line it ends on.

Every beat must be supported by the dossier. Do not add facts.

Return only JSON inside <json></json> tags:
{
  "hooks": [{"text": "", "entry_point": "", "score": 8, "why": ""}],
  "chosen_hook": 0,
  "chapters": [
    {"title": "", "job": "", "beats": [""], "quotes": [""], "numbers": [""], "target_words": 300, "ending_turn": ""}
  ],
  "closing": {"final_fact": "", "judgement": "", "viewer_question": ""}
}
