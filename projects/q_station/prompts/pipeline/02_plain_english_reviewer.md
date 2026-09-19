# Independent spoken-language review

{{LANGUAGE_POLICY}}

SCOPE: {{LANGUAGE_SCOPE}}
EDITORIAL BRIEF AND CONSTRAINTS: {{VIDEO_BRIEF}}
REFERENCE MEANING (not a wording/complexity target): {{REFERENCE_SCRIPT}}
ACTUAL SPOKEN SEGMENTS TO REVIEW: {{SPOKEN_SEGMENTS}}

Assess the actual segments, not the writer's intention. Use the reference and source notes to
check that simpler language preserves meaning and does not introduce new claims. This is not
new research or a readability-grade calculator. Proper names and necessary explained terms are
not defects. Longer but clearer wording is allowed. Do not demand more detail than the brief or
invent facts. Only material barriers to first-listen understanding require correction, not taste.
Do not reject a concrete everyday word merely because it also appears in science (for example
body, heat, model, mass, skin, surface, or size) when the sentence makes its role clear. Do not
ask for a vaguer replacement such as "inside size"; request a concrete cause-and-effect rewrite
only when a listener genuinely cannot tell what is being compared or what happens as a result.

For core scope, assess every hook, entry, body and closing segment; ignore provisional CTA.
For cta scope, assess ONLY the CTA, using the core as context; do not rewrite or reject the core.
A changed hook wording is allowed when its concrete premise and promised answer stay the same.

Return raw JSON only:
{"checks":{"everyday_words":true,"clear_sentence_meaning":true,"terms_explained":true,
"easy_to_follow_once":true,"meaning_preserved":true},"issues":[],"notes":[]}
All checks must be explicit booleans. For each false check include at least one issue:
{"check":"clear_sentence_meaning","segment":"body_03","quote":"exact text from that segment",
"problem":"specific comprehension or meaning error","suggestion":"smallest plain-English fix"}
Use the supplied segment keys and exact quotes, never made-up lines. A false meaning_preserved
may point to the current sentence that lost a qualifier/distinction. Limit issues to 12 priority
items. All true requires no issues. Optional notes are non-blocking observations. Do not return
rewritten narration: the editor owns changes and must keep its validated segment structure.
