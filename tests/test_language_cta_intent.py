"""Plain wording must not turn requested likes/subscriptions into comment questions."""
import copy
import json

import pytest

from test_narration_language import character, project, cta, passed
from test_opening_concept_pipeline import Spy, narration


@pytest.mark.parametrize('intent,line', [
    ('Invite a like.', 'Like this video for more curious questions.'),
    ('Invite a subscription.', 'Subscribe for more strange questions like this.'),
])
def test_plain_language_keeps_operator_engagement_intent(project, character, intent, line):
    path = project / 'launch/CREATIVE_BRIEF.json'
    path.write_text(json.dumps({'_qh': {'cta_hint': intent}}))
    core = narration(character.presentation.segment_key)
    before = copy.deepcopy(core)
    spy = Spy([{'cta': line}, passed()])
    result = cta(spy, project, character, core)
    assert result['cta'] == line and core == before
    assert len(spy.prompts) == 2
    assert intent in spy.prompts[0][1]
    assert 'preserve the requested engagement intent' in spy.prompts[0][1]
    assert 'engagement_intent' in spy.prompts[1][1] and intent in spy.prompts[1][1]
