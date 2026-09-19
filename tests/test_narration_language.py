"""Exercise real language-stage wiring with provider spies, never paid generations.

These tests verify contracts and corrective routing, not an automatic CEFR classifier.
Human listening checks remain necessary to evaluate actual model wording.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import narration_language as language
import opening_runtime as opening
import run_q_station_pipeline as qstation
from character_runtime import load_character_registry
from content_projects import load_content_project
from run_graph import graph_for, affected_nodes
from test_opening_concept_pipeline import Spy, narration, candidates, reviews


def passed():
    return {'checks': {key: True for key in language.REVIEW_CHECKS}, 'issues': [], 'notes': []}


def issue(segment, quote, *, check='clear_sentence_meaning', suggestion='Use a concrete everyday phrase.'):
    result = passed()
    result['checks'][check] = False
    result['issues'] = [{'check': check, 'segment': segment, 'quote': quote,
                         'problem': 'The wording is too abstract to understand on first hearing.',
                         'suggestion': suggestion}]
    return result


def replace_body(plan, text):
    result = copy.deepcopy(plan)
    result['body'][0] = text
    key = 'entry_transition' if 'entry_transition' in result else 'book_transition'
    result['full_narration'] = ' '.join(filter(None, [result['opening_question_spark'], result[key],
                                                     *result['body'], result['optional_closing'], result['cta']]))
    return result


@pytest.fixture
def project(tmp_path):
    for folder in ('creative', 'launch'):
        (tmp_path / folder).mkdir()
    (tmp_path / 'launch/CREATIVE_BRIEF.json').write_text(json.dumps({'audience': '', '_q_station': {}}))
    (tmp_path / 'launch/LAUNCH_REQUEST.json').write_text(json.dumps({'content_project': 'q_station'}))
    return tmp_path


@pytest.fixture(params=['red_horned_everyman', 'moss_cloaked_crone'])
def character(request):
    return load_character_registry(ROOT / 'projects/q_station/characters/registry.json').get(request.param)


def retain(spy, project, character, draft):
    return qstation.stage_retention(spy, project, load_content_project('q_station'), 'Source: some causes remain uncertain.',
                             draft, qstation.DurationTarget(30, 40), character.presentation, character=character)


@pytest.mark.parametrize('name', [
    '00_opening_concept_director.md', '00_opening_candidate_reviewer.md', '01_script_writer.md',
    '02_retention_editor.md', '03_call_to_action_writer.md', '02_plain_english_reviewer.md',
])
def test_all_spoken_producers_and_reviewers_receive_actual_shared_policy(name):
    content = load_content_project('q_station')
    template = qstation.resolve_prompt(content, name)
    policy = language.policy_text(content.root / 'prompts/pipeline')
    assert template.count(policy) == 1
    assert '{{LANGUAGE_POLICY}}' not in template
    assert 'Clarity comes before compression' in template
    assert 'uncertainty (may/can/often/some)' in template


@pytest.mark.parametrize('name', ['08_opening_video_prompt_writer.md', '09_entry_transition_video_prompt_writer.md',
                                  '06_world_keyframe_prompt_writer.md', '07_single_beat_image_prompt_writer.md'])
def test_visual_technical_vocabulary_is_not_subject_to_spoken_policy(name):
    assert 'International spoken English' not in qstation.resolve_prompt(load_content_project('q_station'), name)


def test_policy_loader_rejects_empty_missing_or_recursive_include(tmp_path):
    with pytest.raises(FileNotFoundError):
        language.expand_policy('{{LANGUAGE_POLICY}}', tmp_path)
    path = tmp_path / language.POLICY_FILE
    for text in ('', '{{LANGUAGE_POLICY}}'):
        path.write_text(text)
        with pytest.raises(language.LanguageContractError):
            language.policy_text(tmp_path)
    assert language.expand_policy('Unrelated project prompt', tmp_path) == 'Unrelated project prompt'


def test_blank_audience_does_not_remove_policy_from_actual_writer(project, character):
    plan = narration(character.presentation.segment_key)
    spy = Spy([plan])
    qstation.stage_script(spy, project, load_content_project('q_station'), '{"audience":""}',
                    qstation.DurationTarget(30, 40), character.presentation, character=character)
    assert 'Apply the policy even when' in spy.prompts[0][1]
    assert character.id in spy.prompts[0][1]


@pytest.mark.parametrize('bad', [1, 'true', None])
def test_review_requires_real_booleans(bad):
    payload = passed(); payload['checks']['everyday_words'] = bad
    with pytest.raises(language.LanguageContractError, match='booleans'):
        language.validate_review(payload, {'body_01': 'A clear idea.'})


def test_omitted_check_cannot_silently_pass():
    payload = passed(); payload['checks'].pop('terms_explained')
    with pytest.raises(language.LanguageContractError):
        language.validate_review(payload, {'body_01': 'A clear idea.'})


@pytest.mark.parametrize('segment,quote', [('not_a_segment', 'Chosen privacy'), ('body_01', 'Text that was never said')])
def test_review_must_quote_actual_spoken_evidence(segment, quote):
    with pytest.raises(language.LanguageContractError, match='actual text'):
        language.validate_review(issue(segment, quote), {'body_01': 'Chosen privacy differs from unexpected exposure.'})


def test_unexplained_rejection_or_contradictory_review_is_not_accepted():
    payload = passed(); payload['checks']['meaning_preserved'] = False
    with pytest.raises(language.LanguageContractError, match='actionable'):
        language.validate_review(payload, {'body_01': 'A clear idea.'})
    payload = issue('body_01', 'A clear idea.'); payload['checks']['clear_sentence_meaning'] = True
    with pytest.raises(language.LanguageContractError, match='failed'):
        language.validate_review(payload, {'body_01': 'A clear idea.'})


def test_necessary_names_and_terms_have_no_word_blacklist():
    text = 'The Antikythera mechanism was a machine that used gears to track the sky.'
    assert language.validate_review(passed(), {'body_01': text})['passed'] is True


def test_spoken_scope_never_contains_metadata_or_provisional_cta(character):
    plan = narration(character.presentation.segment_key)
    plan['visual_direction'] = 'A chromatic chiaroscuro macro composition.'
    core = language.spoken_segments(plan, character.presentation.segment_key, 'core')
    assert 'visual_direction' not in core and 'cta' not in core and 'full_narration' not in core
    assert len(core) == len(plan['body']) + 3
    assert language.spoken_segments(plan, character.presentation.segment_key, 'cta') == {'cta': plan['cta']}


def test_low_spoken_clarity_cannot_win_despite_other_high_scores():
    proposed = opening.validate_candidates(candidates(), ('desk_reach',))
    assessed = reviews()
    assessed['reviews'][0]['scores']['spoken_clarity'] = 1
    selected, decisions = opening.select_candidate(assessed, proposed, [])
    assert selected['id'] != 'c1'
    assert decisions[0]['blocking_issues']


def test_retention_rewrites_dense_sentence_in_editor_not_director(project, character):
    dense = replace_body(narration(character.presentation.segment_key), 'Chosen privacy differs from unexpected exposure.')
    simple = replace_body(dense, 'Being seen when you want privacy can feel embarrassing.')
    spy = Spy([dense, issue('body_01', dense['body'][0], suggestion=simple['body'][0]), simple, passed()])
    final = retain(spy, project, character, dense)
    assert final['body'][0] == simple['body'][0]
    assert len(spy.prompts) == 4
    assert all(label.startswith('retention_edit') for label, _ in spy.prompts)
    assert 'Required fixes:' in spy.prompts[2][1]
    report = json.loads((project / language.REPORT_PATHS['core']).read_text())
    assert [item['passed'] for item in report['attempts']] == [False, True]
    assert report['passed'] and report['policy_sha256'] and report['reviewer_prompt_sha256']
    assert report['attempts'][0]['issues'][0]['quote'] == dense['body'][0]
    assert qstation.validate_script_plan('test', final, qstation.DurationTarget(30, 40), character.presentation)
    assert not (project / 'SCRIPT_FINAL.md').exists()
    assert not (project / 'assets').exists()


def test_simplification_cannot_remove_uncertainty_without_correction(project, character):
    source = replace_body(narration(character.presentation.segment_key), 'Seeing a yawn may make you more likely to yawn too.')
    overclaim = replace_body(source, 'Seeing a yawn always makes you yawn too.')
    rejected = issue('body_01', overclaim['body'][0], check='meaning_preserved', suggestion=source['body'][0])
    spy = Spy([overclaim, rejected, source, passed()])
    result = retain(spy, project, character, source)
    assert result['body'][0] == source['body'][0]
    assert source['body'][0] in spy.prompts[1][1]  # original reference
    assert source['body'][0] in spy.prompts[3][1]  # still the original reference after edits


def test_failed_language_edits_are_bounded_and_do_not_publish_core(project, character):
    plan = replace_body(narration(character.presentation.segment_key), 'Chosen privacy differs from unexpected exposure.')
    spy = Spy([plan, issue('body_01', plan['body'][0])] * language.MAX_EDIT_ATTEMPTS)
    with pytest.raises(qstation.StageFailure, match='bounded text edits'):
        retain(spy, project, character, plan)
    assert len(spy.prompts) == 2 * language.MAX_EDIT_ATTEMPTS
    assert not (project / 'creative/SCRIPT_CORE_PLAN.json').exists()
    assert not spy.state.done('retention_edit')
    assert json.loads((project / language.REPORT_PATHS['core']).read_text())['passed'] is False


def test_later_language_repairs_keep_earlier_feedback_visible(project, character):
    first = replace_body(narration(character.presentation.segment_key), 'Chosen privacy differs from unexpected exposure.')
    second = replace_body(first, 'Being seen without permission can feel uncomfortable.')
    final = replace_body(second, 'Being seen when you want privacy can feel uncomfortable.')
    first_issue = issue('body_01', first['body'][0], suggestion=second['body'][0])
    second_issue = issue('body_01', second['body'][0], suggestion=final['body'][0])
    spy = Spy([first, first_issue, second, second_issue, final, passed()])
    retain(spy, project, character, first)
    correction = spy.prompts[4][1]
    assert first['body'][0] in correction
    assert second['body'][0] in correction


def test_malformed_review_retries_checker_not_script(project, character):
    plan = narration(character.presentation.segment_key)
    spy = Spy([plan, {'passed': True}, passed()])
    retain(spy, project, character, plan)
    assert len(spy.prompts) == 3
    assert all('language_review' in name for name, _ in spy.prompts[1:])


def test_core_resume_reuses_approved_words_and_ignores_provisional_cta(project, character):
    plan = narration(character.presentation.segment_key)
    spy = Spy([plan, passed()])
    original = retain(spy, project, character, plan)
    changed_cta = dict(plan, cta='This provisional CTA is never reviewed.')
    assert retain(spy, project, character, changed_cta) == original
    assert len(spy.prompts) == 2


@pytest.mark.parametrize('change', ['missing_receipt', 'changed_core', 'changed_reference'])
def test_core_reuse_requires_matching_review_not_silent_regeneration(project, character, change):
    plan = narration(character.presentation.segment_key)
    spy = Spy([plan, passed()])
    retain(spy, project, character, plan)
    if change == 'missing_receipt':
        (project / language.REPORT_PATHS['core']).unlink()
    elif change == 'changed_core':
        target = project / 'creative/SCRIPT_CORE_PLAN.json'
        changed = json.loads(target.read_text()); changed['body'][0] = 'Changed after approval.'
        target.write_text(json.dumps(changed))
    else:
        plan = replace_body(plan, 'The source says something different now.')
    with pytest.raises(qstation.StageFailure, match='Revise'):
        retain(spy, project, character, plan)
    assert len(spy.prompts) == 2


def test_legacy_completed_core_has_no_forced_language_migration(project, character):
    plan = narration(character.presentation.segment_key)
    target = project / 'creative/SCRIPT_CORE_PLAN.json'; target.write_text(json.dumps(plan))
    spy = Spy(); spy.state.completed.add('retention_edit')
    assert retain(spy, project, character, plan) == plan
    assert not spy.prompts


def cta(spy, project, character, plan):
    return qstation.stage_call_to_action(spy, project, load_content_project('q_station'), 'Source: keep the core unchanged.',
                                   plan, qstation.DurationTarget(30, 40), character.presentation)


def test_cta_simplification_never_edits_approved_core(project, character):
    plan = narration(character.presentation.segment_key); before = copy.deepcopy(plan)
    original = 'What do you think shapes our feelings about nudity most?'
    simple = 'Are the rules the same where you live?'
    spy = Spy([{'cta': original}, issue('cta', original, suggestion=simple), {'cta': simple}, passed()])
    result = cta(spy, project, character, plan)
    assert plan == before
    assert qstation.cta_source_context(result, character.presentation) == qstation.cta_source_context(plan, character.presentation)
    assert result['cta'] == simple and result['full_narration'].endswith(simple)
    report = json.loads((project / language.REPORT_PATHS['cta']).read_text())
    assert report['scope'] == 'cta'
    assert list(report['attempts'][-1]['segments']) == ['cta']
    assert 'Do not change the approved core' in spy.prompts[2][1]
    calls = len(spy.prompts)
    assert cta(spy, project, character, plan)['full_narration'] == result['full_narration']
    assert len(spy.prompts) == calls


def test_cta_missing_receipt_fails_without_changing_existing_script(project, character):
    plan = narration(character.presentation.segment_key)
    spy = Spy([{'cta': 'What question should we explore next?'}, passed()])
    cta(spy, project, character, plan)
    target = project / 'SCRIPT_FINAL.md'; original = target.read_bytes()
    (project / language.REPORT_PATHS['cta']).unlink()
    with pytest.raises(qstation.StageFailure, match='Revise'):
        cta(spy, project, character, plan)
    assert target.read_bytes() == original and len(spy.prompts) == 2


def test_cta_only_revision_preserves_core_review_and_rechecks_only_cta(project, character):
    plan = narration(character.presentation.segment_key)
    core_spy = Spy([plan, passed()]); core = retain(core_spy, project, character, plan)
    receipt = project / language.REPORT_PATHS['core']; before = receipt.read_bytes()
    spy = Spy([{'cta': 'What question should we explore next?'}, passed()])
    cta(spy, project, character, core)
    path = project / 'launch/CREATIVE_BRIEF.json'
    path.write_text(json.dumps({'_q_station': {'cta_hint': 'Invite a like.'}}))
    spy.responses.extend([{'cta': 'Like this video for more questions.'}, passed()])
    cta(spy, project, character, core)
    assert receipt.read_bytes() == before and len(spy.prompts) == 4
    graph = graph_for(project, include_disabled=True)
    assert 'retention_edit' not in affected_nodes(graph, ['call_to_action'])
    assert 'episode_director' not in affected_nodes(graph, ['call_to_action'])


def test_review_receipts_are_required_for_marked_new_runs_in_graph(project, character):
    plan = narration(character.presentation.segment_key)
    spy = Spy([plan, passed()]); core = retain(spy, project, character, plan)
    cta_spy = Spy([{'cta': 'What question should we explore next?'}, passed()]); cta(cta_spy, project, character, core)
    graph = graph_for(project, include_disabled=True)
    nodes = {node['id']: node for node in graph['nodes']}
    assert any(item['path'] == language.REPORT_PATHS['core'] for item in nodes['retention_edit']['artifacts'])
    assert any(item['path'] == language.REPORT_PATHS['cta'] for item in nodes['call_to_action']['artifacts'])


@pytest.mark.parametrize('label,owner', [('retention_edit_language_review_2_json3','retention_edit'),
                                       ('call_to_action_language_review_1_fix1_json2','call_to_action')])
def test_language_calls_route_fallback_to_their_owning_stage(label, owner):
    assert qstation.Runner._fallback_stage(label) == owner


def test_feedback_budget_preserves_whole_evidence_and_never_truncates_source():
    report = issue('body_01', 'Dense words.')
    line = language.correction_feedback(report)
    assert language.correction_feedback(report, max_chars=len(line)) == line
    with pytest.raises(language.LanguageContractError, match='prompt budget'):
        language.correction_feedback(report, max_chars=10)
    with pytest.raises(qstation.StageFailure, match='prompt budget'):
        qstation._language_correction_prompt('x' * qstation.ORDAK_QUESTION_LIMIT, 'Fix words', report, 'retention_edit')


def test_new_missing_core_cannot_migrate_an_unreviewed_final_script(project, character):
    plan = narration(character.presentation.segment_key)
    spy = Spy([plan, passed()]); retain(spy, project, character, plan)
    (project / 'creative/SCRIPT_CORE_PLAN.json').unlink()
    (project / 'creative/SCRIPT_PLAN.json').write_text(json.dumps(plan))
    with pytest.raises(qstation.StageFailure, match='Reviewed core is missing'):
        retain(spy, project, character, plan)
    assert len(spy.prompts) == 2


def test_language_policy_rollout_preserves_verified_legacy_concept(project, character, monkeypatch):
    import episode_history
    monkeypatch.setattr(episode_history, 'opening_history', lambda *args, **kwargs: [])
    variant = character.presentation.entry_variants[0]
    spy = Spy([candidates(variant), reviews()])
    content = load_content_project('q_station')
    concept = qstation.stage_opening_concept(spy, project, content, 'earworms', qstation.DurationTarget(30,40), character)
    context_path = project / 'creative/OPENING_CONTEXT.json'
    context = json.loads(context_path.read_text())
    context.pop('language_policy_version')
    context['writer_sha256'] = 'old writer before language policy'
    context['reviewer_sha256'] = 'old reviewer before language policy'
    keys = ('policy_version','brief','character','presentation','writer_sha256','reviewer_sha256')
    context['input_fingerprint'] = opening.fingerprint({key: context[key] for key in keys})
    concept['input_fingerprint'] = context['input_fingerprint']
    context_path.write_text(json.dumps(context))
    target = project / 'creative/OPENING_CONCEPT.json'; target.write_text(json.dumps(concept))
    before = target.read_bytes()
    assert qstation.stage_opening_concept(spy, project, content, 'earworms', qstation.DurationTarget(30,40), character) == concept
    assert target.read_bytes() == before and len(spy.prompts) == 2
    with pytest.raises(qstation.StageFailure, match='Revise'):
        qstation.stage_opening_concept(spy, project, content, 'a genuinely new topic', qstation.DurationTarget(30,40), character)


def _core_text(plan, entry_key):
    return ' '.join(filter(None, [plan['opening_question_spark'], plan[entry_key],
                                  *plan['body'], plan['optional_closing']]))


_FILLER_BANK = "Memory can replay each pattern softly again today while the room stays quiet and still".split()


def _padded_core(entry_key, target_words):
    from test_opening_concept_pipeline import narration
    plan = copy.deepcopy(narration(entry_key))
    deficit = target_words - qstation.word_count(_core_text(plan, entry_key))
    while deficit > 0:
        chunk = min(deficit, 14)
        words = (_FILLER_BANK * ((chunk // len(_FILLER_BANK)) + 1))[:chunk]
        words[0] = words[0].capitalize()
        plan['body'].append(' '.join(words) + '.')
        deficit -= chunk
    # A short provisional CTA keeps the whole plan inside the episode cap so the
    # room check — not the range check — is what the retention stage reacts to.
    plan['cta'] = 'Say more.'
    key = 'entry_transition' if 'entry_transition' in plan else 'book_transition'
    plan['full_narration'] = ' '.join(filter(None, [plan['opening_question_spark'], plan[key],
                                                    *plan['body'], plan['optional_closing'], plan['cta']]))
    assert qstation.word_count(_core_text(plan, entry_key)) == target_words
    return plan


def test_retention_leaves_room_for_the_downstream_cta(project, character):
    entry_key = character.presentation.segment_key
    long = _padded_core(entry_key, 98)
    short = _padded_core(entry_key, 90)
    assert qstation.DurationTarget(30, 40).word_max - qstation.word_count(_core_text(long, entry_key)) == 2
    spy = Spy([long, passed(), short, passed()])
    final = retain(spy, project, character, long)
    assert qstation._cta_word_room(final, qstation.DurationTarget(30, 40), character.presentation) >= 4
    assert len(spy.prompts) == 4
    assert 'Compress the current candidate by at least 2 words' in spy.prompts[2][1]
    assert (project / 'creative/SCRIPT_CORE_PLAN.json').is_file()
