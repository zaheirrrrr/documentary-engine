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

<packaging>
{{packaging}}
</packaging>

Target length: about {{target_words}} words of narration, in {{chapters_min}} to {{chapters_max}} chapters.

Step 1. Write 5 different cold opens (each 120 to 180 words) following the
style guide. Vary the entry point: a record, a moment of crisis, a number, a
person, a scene from a first-hand account. Judge each against the hook
checklist in the style guide (6 checks) and the four hook killers. Score =
checks passed (0 to 6) plus up to 4 points for how badly a viewer would need
the next sentence. The highest score wins, not the one that sounds nicest.

Step 2. Plan the chapters. For each chapter give: a short title, its job in
the arc, the key beats in order, which dossier quotes it uses (copy the quote
text exactly), the key numbers it uses, its target word count, the re-hooks
inside it (one at least every 150 words), and the exact turning line it ends
on.

The plan must also:
- open one loop in the cold open or first chapter that the close pays off
- name the doubter, rival, rule or obstacle within the first two chapters
- put the strongest scene or quote at 40 to 60 percent of the running time
- end with a callback to the opening image or fact

Every beat must be supported by the dossier. Do not add facts.

Return only JSON inside <json></json> tags:
{
  "hooks": [{"text": "", "entry_point": "", "checks_passed": ["subject named", "..."], "score": 8, "why": ""}],
  "open_loop": {"opened_by": "", "closed_by": ""},
  "obstacle": "",
  "midpoint_scene": "",
  "chosen_hook": 0,
  "chapters": [
    {"title": "", "job": "", "beats": [""], "quotes": [""], "numbers": [""], "target_words": 300, "ending_turn": ""}
  ],
  "closing": {"final_fact": "", "judgement": "", "viewer_question": ""}
}
