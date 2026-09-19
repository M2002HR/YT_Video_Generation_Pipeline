# Independent opening selection review

{{LANGUAGE_POLICY}}

Evaluate the proposed scenes as a critical director, not as their author. Do not rewrite or select
by prettiness. Scores are editorial assessments, NOT probabilities of audience retention.
BRIEF: {{EDITORIAL_BRIEF}}
CHARACTER: {{CHARACTER_STORY_CONTEXT}}
PRESENTATION: {{PRESENTATION_CONTEXT}}
RECENT OPENINGS: {{RECENT_OPENINGS}}
CANDIDATES: {{CANDIDATES}}

For every candidate assess topic_fit, visible_hook, character_fit, honesty, payoff, entry_fit,
feasibility, novelty and spoken_clarity from 0 (unusable) to 4 (excellent). A weak generic routine with a plausible
written rationale is NOT a strong topic link. Ask whether the visible event, without its rationale,
actually raises the intended question. Test the promise against the factual_anchor and source notes.
Do not upgrade a hypothesis to a fact. Test that at most three actions can communicate the story
before its entry. Check first-frame evidence, profile-specific first frame, A/B seam, and useful
information during entry. Unfamiliar props alone are not an understandable discrepancy.
Compare meaning, not strings, with history AND the other candidates. Sorting paraphrases, a new
workshop, or a changed camera do not establish novelty. Shared host traits/book/orb are not defects.
A single shared action family is allowed when the discrepancy and payoff materially differ.
When a candidate revisits a broad question already present in history, reject it unless its causal
sub-question, first test, evidence/prop family, factual mechanism, and payoff are all materially
different. Do not score a renamed version of the previous demonstration as novel.
Do not require a returning-host ending: the configured subject world can pay off the hook.

Return raw JSON: {"reviews":[{"id":"c1","scores":{"topic_fit":0,"visible_hook":0,
"character_fit":0,"honesty":0,"payoff":0,"entry_fit":0,"feasibility":0,"novelty":0,"spoken_clarity":0},
"blocking_issues":["specific fundamental issue, or empty array when usable"],"reason":"brief evidence-based justification"}]}
Review each supplied id exactly once. All scores must be integers. Never rubber-stamp a proposal.
Minor polish is not a blocking issue. Unsupported promises, unfilmable sequences and broken entry
contracts are blocking. When all proposals fail, report that honestly; the caller can redesign them.

For spoken_clarity judge hook_line and the wording intended for entry narration, not internal
production vocabulary. A 3 allows minor wording polish; a 0-2 means material jargon/abstractness
blocks first-listen understanding. Necessary familiar terms and proper names are not penalized.
