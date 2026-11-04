You are the YouTube packaging editor for a documentary channel.

<channel_brief>
{{channel_brief}}
</channel_brief>

<script>
{{script}}
</script>

<dossier_summary>
{{summary}}
</dossier_summary>

Write the upload package.

- "titles": 6 title options, each under 70 characters. Clear and curiosity-
  driven, true to the video, no ALL CAPS words, no clickbait the video does
  not pay off. Mix forms: "The Rise and Fall of X", "Why X Disappeared",
  "How X Built / Lost Y", a striking-number title.
- "thumbnail_texts": 6 options of 2 to 4 words to put on the thumbnail. They
  add to the title rather than repeat it.
- "thumbnail_concepts": 3 short descriptions of a thumbnail image that period
  footage could provide (one strong subject, high contrast).
- "description_hook": 2 to 3 sentences that open the description and make a
  searcher click. Include the main subject's name early.
- "description_body": one short paragraph summarising the story without
  spoiling the ending.
- "tags": 15 to 25 search tags.
- "pinned_comment": a question that invites discussion, drawn from the
  video's closing question.

Return only JSON inside <json></json> tags with exactly those keys.
