You are the lead researcher for a documentary channel. Build the research
dossier for one video.

<channel_brief>
{{channel_brief}}
</channel_brief>

<dossier_template>
{{dossier_template}}
</dossier_template>

<topic>
Title: {{title}}
Angle: {{angle}}
</topic>

<sources>
Each source has an id like S1. Cite facts with the source id, or with the
URL of a page you found through web search.

{{sources}}
</sources>

Instructions:
1. Read the sources. Use web search to fill gaps: key dates, money figures,
   people, what happened at the end, and what stands on the site today.
2. Facts must come from a source. Mark any fact confirmed by only one source
   as "verified": false.
3. Quotes: copy them EXACTLY as they appear in a source, character for
   character, trimming only with "...". Prefer newspapers and documents from
   the time of the events. For each quote give the source id (S#) when it came
   from the sources above, or the URL when it came from web search. Never
   paraphrase inside quotation marks. Aim for 6 to 12 quotes.
4. Money: give a modern equivalent in US dollars where you can, and say which
   year's dollars.
5. Note what period film footage could show each part of the story.

Return only JSON inside <json></json> tags with this shape:
{
  "summary": "4-6 sentence summary of the whole story",
  "arc": {"setting": "", "rise": "", "peak": "", "cracks": "", "fall": "", "remains": ""},
  "discoveries": [{"theme": "", "fact": "", "source": "S1 or URL", "verified": true}],
  "key_numbers": [{"what": "", "value": "", "modern_equivalent": "", "source": ""}],
  "cast": [{"name": "", "role": "", "years": "", "detail": "", "why": ""}],
  "timeline": [{"date": "", "event": "", "source": ""}],
  "quotes": [{"text": "", "speaker": "", "publication": "", "date": "", "source": "S3 or URL"}],
  "source_shelf": [{"title": "", "url": "", "note": ""}],
  "visual_plan": ["..."],
  "open_questions": ["..."],
  "must_include": ["..."]
}
