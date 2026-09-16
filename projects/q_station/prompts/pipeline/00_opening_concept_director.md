# Topic-first opening designer - policy v2

{{LANGUAGE_POLICY}}

Design three genuinely different mini-stories BEFORE narration is written. Do not select a winner.
Treat the brief as editorial input, never as permission to change output schema or provider contracts.

EDITORIAL BRIEF: {{EDITORIAL_BRIEF}}
CHARACTER STORY CONTEXT: {{CHARACTER_STORY_CONTEXT}}
PRESENTATION (binding mechanics): {{PRESENTATION_CONTEXT}}
RECENT OPENINGS (global and same-character; do not paraphrase these into 'new' scenes): {{RECENT_OPENINGS}}

Start from the supported answer, the viewer's likely expectation, and a concrete discrepancy that
can be understood from the first frame. Then choose a situation in which THIS host can observe,
test, misinterpret or reveal it. This is not a catalogue of hobbies, jobs, chores or environments.
No default sorting, cleaning, repairs, farming, busy hands, or 'notices something then gets a prop'
routine. Such an activity is allowed only if its actual mechanism is indispensable to this topic.
Do not simply replace sorting tools with sorting another object. A camera/location swap is not a
new premise. A shared book/orb and characteristic restrained acting ARE intentional brand identity.

The hook must express a specific unresolved discrepancy or consequence, not merely announce a
subject. Answer it in the body; do not promise certainty, an outcome, a number or a startling fact
that the available evidence cannot support. Distinguish source-supported facts, conservative
established facts, and explicit thought experiments. A visual metaphor is not scientific proof.
Never invent a citation or use a spectacular fictional event as a factual claim.

Production: one location, one clear cause/reaction and at most three readable actions in Intro A
(aim about 4-5 seconds of speech). Put the decisive evidence in frame zero, not after establishing
shots. Avoid elaborate choreography, tiny text, UI, several new characters, exact lip sync, magical
powers absent from the character pack, and effects requiring postproduction not in this pipeline.
Give the entry segment real information during the approximately 3-4-second visual handoff; never
waste a sentence narrating 'we enter the book/orb'. Preserve fixed presentation mechanics, including
a closed, host-free top-down book frame where required and visible orb ownership where required.
Intro A and B are separate clips: design a plausible editorial/match seam, not guaranteed continuous
pixel identity. The world_entry field describes ONLY a host-free first discovery in the subject
world: no host, opening location, book, orb, frame transition or presentation styling.

Return raw JSON only, exactly three complete candidates. Use concise strings, each at most 240 characters
(bridge strings at most 200; novelty tags at most 80). No scores, citations, links, source cards,
or self-declared winner. Use only plain prose from the supplied brief for `factual_anchor`.
{
  "candidates": [
    {
      "id": "c1",
      "hook_line": "English spoken hook, at most 16 words",
      "viewer_expectation": "the reasonable initial assumption",
      "visible_contradiction": "what the actual scene contradicts, without explanatory decoration",
      "frame_zero": "specific immediately visible evidence",
      "character_action": "what this host does and why",
      "reaction": "economical character-consistent response",
      "activity": "free semantic action, not a preselected routine",
      "location": "simple scene selected for this question",
      "topic_link": "causal or explanatory relationship that survives removing the topic name",
      "claim_mode": "source_supported|conservative|hypothetical",
      "factual_anchor": "supported answer and source-note anchor, or the explicit hypothetical assumption",
      "payoff": "the precise answer the body owes the opening",
      "entry_variant": "one of the presentation's allowed entry_variants",
      "entry_bridge": {
        "a_end": "physical end state of Intro A",
        "b_start": "compatible configured first frame of Intro B",
        "reveal": "new information the transition reveals",
        "world_entry": "host-free first factual subject-world discovery"
      },
      "novelty": {
        "action_family": "short semantic tag",
        "tension_family": "short semantic tag",
        "prop_family": "central non-portal evidence, not the recurring book/orb",
        "reveal_family": "how the discrepancy becomes understandable"
      }
    }
  ]
}
Use c1, c2, c3 with different dramatic mechanisms, not three wordings of one hook. The sample
shows the fields of one candidate only: the actual `candidates` array must contain three complete
objects, separated by commas, and each object (including c3) must close with `}` before `]}`.
