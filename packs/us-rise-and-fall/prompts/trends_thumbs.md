You are a YouTube thumbnail analyst. The image is a grid of {{count}}
thumbnails from videos that strongly outperformed their channel's normal
views. Each tile has a number in its top-left corner. The titles are:

{{titles}}

For EACH numbered thumbnail, describe what makes it clickable. Return:
- "n": the tile number
- "layout": one of "single_subject", "split_before_after", "versus",
  "big_number", "object_closeup", "scene_wide", "map_or_diagram", "collage"
- "text": the exact words on the thumbnail ("" if none)
- "text_words": number of words on it
- "face": true if a human face is a main element
- "emotion": the emotion the image sells (shock, awe, fear, curiosity,
  nostalgia, triumph, loss, none)
- "focal_points": how many things compete for attention (1, 2, 3+)
- "devices": any of "arrow", "circle", "red_x", "price_tag", "glow",
  "blur_background", "before_after", "scale_comparison", "danger_sign",
  "question_mark", "number"
- "contrast": "high", "medium" or "low" at small size
- "palette": up to 3 dominant colours as plain words
- "title_relation": "complements" if image and title say different things
  that add up, "repeats" if the image repeats the title, "independent"
- "why": one sentence on why it gets clicked

Return only JSON inside <json></json> tags: {"thumbnails": [ ... ]}
