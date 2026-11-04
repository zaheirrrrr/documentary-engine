You are a YouTube packaging analyst. Below are titles of videos that
outperformed their own channel's typical views, from leading channels across
many niches and from channels in our own niche. "x" is the outlier multiple
(views divided by the channel's median), so 12x means twelve times its
channel's normal.

<our_channel>
{{channel_brief}}
</our_channel>

<outlier_titles>
{{titles}}
</outlier_titles>

Reverse-engineer WHY these titles got clicked, the way creators turn
MrBeast's "$1 vs $1,000,000 Hotel Room" into "$1 Book vs $1,000,000 Book".

1. Find the 12 to 18 strongest reusable title formulas. A formula is a
   pattern with blanks, e.g. "$[small] vs $[huge] [thing]", "Why [familiar
   thing] Disappeared", "The [superlative] [thing] Nobody Talks About",
   "I [did extreme thing] for [time]", "How [person] [huge result] With
   [tiny resource]". For each:
   - "id": short snake_case id
   - "template": the pattern with [blanks]
   - "mechanism": the psychological reason it gets clicked (curiosity gap,
     contrast, stakes, specificity, status, fear of missing out, etc.)
   - "examples": 2 to 6 titles from the list above that use it, copied EXACTLY
   - "adaptations": 4 titles applying it to our channel's kind of stories
     (true American business and megaproject rise-and-fall stories). They
     must be honest titles a documentary could pay off.
   - "fit": 1 to 10, how well it suits our channel's tone (calm, credible,
     never clickbait that does not pay off)
2. "principles": 8 to 12 general rules these titles share (length, numbers,
   word choice, what is left unsaid).
3. "avoid": patterns that work for entertainment channels but would damage a
   credible documentary channel.

Return only JSON inside <json></json> tags:
{"formulas": [{"id": "", "template": "", "mechanism": "", "examples": [""], "adaptations": [""], "fit": 8}],
 "principles": [""], "avoid": [""]}
