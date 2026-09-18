"""Regressions: failed images, changed inputs and concurrent previews never pass as ready."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_q_station_pipeline as qstation
from image_artifacts import digest, request_fingerprint, receipt_status, CONTRACT_VERSION
from ordak_jobs import Reference, JobResult
from panel_previews import preview


def picture(path, seed=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    import random
    Image.frombytes('RGB', (576,1024), random.Random(seed).randbytes(576*1024*3)).save(path)
    return path


def result(model='nano_banana_2', verified=True):
    return JobResult(job_id='test',status='completed',answer=None,output_images=['one'],generation_receipt={
        'requested_model':model,'model_verified':verified,'actual_model_label':'Nano Banana 2',
        'notes':['artifact_source=download']})


def test_rejected_model_never_overwrites_previous_output(tmp_path):
    target=picture(tmp_path/'beat.png'); before=target.read_bytes()
    runner=object.__new__(qstation.Runner)
    runner._run=lambda *a,**kw:result(verified=False)
    runner.jobs=SimpleNamespace(download=lambda *a:pytest.fail('invalid model downloaded'))
    with pytest.raises(qstation.StageFailure):
        runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert target.read_bytes()==before
    assert list(tmp_path.glob('.*.png'))==[]


def test_failed_content_does_not_publish_candidate(tmp_path):
    source=picture(tmp_path/'source.png');target=tmp_path/'out.png'
    runner=object.__new__(qstation.Runner);runner._run=lambda *a,**k:result()
    runner.jobs=SimpleNamespace(download=lambda _,dst:dst.write_bytes(source.read_bytes()))
    runner.json=lambda *a,**k:{'passed':False,'description':'character sheet','violations':['not a scene']}
    with pytest.raises(qstation.StageFailure,match='content QC'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert not target.exists()
    assert list(tmp_path.glob('.*.png'))==[]


def qc_result(check):
    item = result()
    item.generation_receipt['quality_check'] = check
    return item


def test_zero_qc_policy_reports_noncritical_findings_without_regeneration(tmp_path):
    runner=object.__new__(qstation.Runner);runner.image_qc_correction_policy='0';calls=[]
    def attempt(_stage,_prompt,_references,*,model,destination,provider="gemini"):
        calls.append(destination);picture(destination,1)
        return qc_result({'passed':True,'review_status':'passed_with_warnings',
                          'observations':['minor framing issue'],'blocking_violations':[]})
    runner._image_attempt=attempt
    target=tmp_path/'out.png'
    selected=runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert len(calls)==1 and target.is_file()
    assert selected.generation_receipt['qc_policy']=='0'
    assert selected.generation_receipt['qc_selected_attempt']==1


def test_disabled_beat_qc_never_uploads_generated_image_to_chatgpt(tmp_path):
    source=picture(tmp_path/'source.png');target=tmp_path/'out.png'
    runner=object.__new__(qstation.Runner)
    runner.beat_image_qc_disabled=True
    runner.image_qc_correction_policy='strict'
    runner._run=lambda *a,**k:result()
    runner.jobs=SimpleNamespace(download=lambda _,dst:dst.write_bytes(source.read_bytes()))
    runner.validate_image_content=lambda *a,**k:pytest.fail('beat image was sent to ChatGPT QC')
    selected=runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert target.is_file()
    assert selected.generation_receipt['qc_policy']=='disabled'
    assert selected.generation_receipt['quality_check']['review_status']=='disabled'
    assert selected.generation_receipt['quality_check']['review_provider'] is None


def test_pre_generation_feedback_mode_never_uploads_gemini_replacement_to_chatgpt(tmp_path):
    source=picture(tmp_path/'source.png');target=tmp_path/'out.png'
    runner=object.__new__(qstation.Runner)
    runner.beat_image_qc_disabled=False
    runner.image_qc_correction_policy='strict'
    runner._run=lambda *a,**k:result()
    runner.jobs=SimpleNamespace(download=lambda _,dst:dst.write_bytes(source.read_bytes()))
    runner.validate_image_content=lambda *a,**k:pytest.fail('replacement was sent to ChatGPT QC')
    selected=runner.image(
        'beat_image_001','scene',[],model='nano_banana_2',destination=target,
        skip_content_qc=True,
    )
    assert target.is_file()
    assert selected.generation_receipt['qc_policy']=='disabled'
    assert selected.generation_receipt['quality_check']['review_status']=='skipped_after_pre_generation_feedback'


def test_one_qc_correction_uses_previous_candidate_as_a_quality_floor(tmp_path):
    runner=object.__new__(qstation.Runner);runner.image_qc_correction_policy='1';calls=[]
    checks=[
        {'passed':True,'review_status':'passed_with_warnings','observations':['cropping is tight'],'blocking_violations':[]},
        {'passed':True,'review_status':'passed','observations':[],'blocking_violations':[]},
    ]
    def attempt(_stage,prompt,references,*,model,destination,provider="gemini"):
        calls.append((prompt,references));picture(destination,len(calls))
        return qc_result(checks[len(calls)-1])
    runner._image_attempt=attempt
    target=tmp_path/'out.png'
    selected=runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert len(calls)==2
    assert [ref.role for ref in calls[1][1]]==['qc_previous_candidate']
    assert 'smallest targeted changes' in calls[1][0]
    assert 'cropping is tight' in calls[1][0]
    assert selected.generation_receipt['qc_selected_attempt']==2


def test_two_qc_corrections_keep_the_best_candidate_when_retries_regress(tmp_path):
    runner=object.__new__(qstation.Runner);runner.image_qc_correction_policy='2';calls=[]
    checks=[
        {'passed':True,'observations':['minor issue'],'blocking_violations':[]},
        {'passed':True,'observations':['minor issue','new defect'],'blocking_violations':[]},
        {'passed':False,'observations':[],'blocking_violations':['style continuity drift: wrong medium']},
    ]
    expected_first=picture(tmp_path/'expected.png',1).read_bytes()
    def attempt(_stage,_prompt,_references,*,model,destination,provider="gemini"):
        calls.append(destination);picture(destination,len(calls))
        return qc_result(checks[len(calls)-1])
    runner._image_attempt=attempt
    target=tmp_path/'out.png'
    selected=runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert len(calls)==3
    assert target.read_bytes()==expected_first
    assert selected.generation_receipt['qc_selected_attempt']==1
    assert [item['selected'] for item in selected.generation_receipt['quality_iterations']]==[True,False,False]


def test_strict_qc_fails_after_three_unresolved_attempts_without_overwriting(tmp_path):
    target=picture(tmp_path/'out.png',9);before=target.read_bytes()
    runner=object.__new__(qstation.Runner);runner.image_qc_correction_policy='strict';calls=[]
    def attempt(_stage,_prompt,_references,*,model,destination,provider="gemini"):
        calls.append(destination);picture(destination,len(calls))
        return qc_result({'passed':True,'observations':['unresolved polish issue'],'blocking_violations':[]})
    runner._image_attempt=attempt
    with pytest.raises(qstation.StageFailure,match='after 3 attempts'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert len(calls)==3 and target.read_bytes()==before


def test_minor_visual_qc_findings_are_accepted_and_preserved(tmp_path):
    candidate=picture(tmp_path/'candidate.png')
    runner=object.__new__(qstation.Runner)
    runner.json=lambda *a,**k:{
        'passed':False,
        'description':'book sheet with labels and an imperfect empty page',
        'violations':['Readable labels are present.', 'The ribbon slightly overlaps the empty page.'],
    }
    check=runner.validate_image_content('book_design_sheet','book sheet',candidate)
    assert check['passed'] is True
    assert check['review_status']=='passed_with_warnings'
    assert check['raw_passed'] is False
    assert check['blocking_violations']==[]
    assert len(check['observations'])==2


def test_fundamental_visual_qc_failure_still_rejects(tmp_path):
    candidate=picture(tmp_path/'candidate.png')
    runner=object.__new__(qstation.Runner)
    runner.json=lambda *a,**k:{
        'passed':False,
        'description':'a character turnaround sheet instead of the requested scene',
        'violations':['A character turnaround was generated instead of a requested scene.'],
    }
    with pytest.raises(qstation.StageFailure,match='content QC rejected'):
        runner.validate_image_content('world_keyframe','single host-free scene',candidate)


def test_reviewer_cannot_escalate_a_minor_finding_to_blocking(tmp_path):
    candidate=picture(tmp_path/'candidate.png')
    runner=object.__new__(qstation.Runner)
    runner.json=lambda *a,**k:{
        'passed':False,
        'description':'a usable scene with readable text',
        'violations':['Readable label is present.'],
        'blocking_violations':['Readable label is present.'],
    }
    check=runner.validate_image_content('beat_image_001','scene',candidate)
    assert check['passed'] is True
    assert check['blocking_violations']==[]


def test_character_or_style_continuity_drift_is_blocking(tmp_path):
    candidate=picture(tmp_path/'candidate.png')
    character=picture(tmp_path/'character.png',2)
    style=picture(tmp_path/'style.png',3)
    runner=object.__new__(qstation.Runner)
    captured={}
    def review(_stage,_prompt,*,references):
        captured['roles']=[reference.role for reference in references]
        return {
            'passed':False,
            'description':'the candidate changes the host silhouette and the recurring print treatment',
            'violations':[
                'character identity drift: horn silhouette differs from the canonical sheet.',
                'style continuity drift: rendering loses the supplied print texture.',
            ],
            'blocking_violations':[],
        }
    runner.json=review
    with pytest.raises(qstation.StageFailure,match='content QC rejected'):
        runner.validate_image_content(
            'beat_image_001','scene',candidate,
            references=[Reference('character_sheet',character),Reference('style_reference',style)],
        )
    assert captured['roles']==['candidate_output','character_sheet','style_reference']


def test_receipt_reuse_rejects_changed_reference_and_prompt(tmp_path):
    output=picture(tmp_path/'beat.png');ref=picture(tmp_path/'style.png',2)
    references=[Reference('style_reference',ref)];model='nano_banana_2'
    receipt=tmp_path/'receipt.json'
    receipt.write_text(json.dumps({'contract_version':CONTRACT_VERSION,'model_verified':True,
        'quality_check':{'passed':True},'output_sha256':digest(output),
        'request_fingerprint':request_fingerprint('scene',model,references),
        'references':[{'role':'style_reference','path':str(ref),'sha256':digest(ref)}]}))
    assert receipt_status(tmp_path,output,receipt,fingerprint=request_fingerprint('scene',model,references))['status']=='verified'
    stale=receipt_status(tmp_path,output,receipt,fingerprint=request_fingerprint('new scene',model,references))
    assert stale['status']=='stale'
    assert [ref['role'] for ref in stale['references']]==['style_reference']
    picture(ref,3)
    assert receipt_status(tmp_path,output,receipt)['status']=='stale'


def test_corrupt_or_missing_receipt_is_never_verified(tmp_path):
    output=picture(tmp_path/'beat.png');receipt=tmp_path/'receipt.json'
    assert receipt_status(tmp_path,output,receipt)['status']=='unverified'
    receipt.write_text('{')
    assert receipt_status(tmp_path,output,receipt)['status']=='unverified'


def test_canonical_receipt_survives_episode_model_change(tmp_path):
    project=tmp_path/'video';output=picture(tmp_path/'book.png');receipt=tmp_path/'book.receipt.json'
    (project/'launch').mkdir(parents=True)
    (project/'launch/LAUNCH_REQUEST.json').write_text(json.dumps({
        'image_generation':{'model':'a_new_model'}}))
    fingerprint=request_fingerprint('book identity','canonical',[])
    receipt.write_text(json.dumps({'contract_version':CONTRACT_VERSION,'source_type':'canonical',
        'quality_check':{'passed':True},'output_sha256':digest(output),
        'request_fingerprint':fingerprint,'references':[]}))
    assert receipt_status(project,output,receipt,fingerprint=fingerprint)['status']=='verified'


def test_concurrent_previews_publish_one_complete_derivative(tmp_path):
    source=picture(tmp_path/'source.png');cache=tmp_path/'cache'
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths=list(pool.map(lambda _:preview(source,cache)[0],range(16)))
    assert len(set(paths))==1
    with Image.open(paths[0]) as image:
        image.load();assert max(image.size)<=480
    assert len(list(cache.iterdir()))==1
    picture(source,2)
    assert preview(source,cache)[0]!=paths[0]


def test_preview_failure_leaves_no_cache_artifact(tmp_path,monkeypatch):
    source=tmp_path/'video.mp4';source.write_bytes(b'video');cache=tmp_path/'cache'
    def fail(command,**kw):
        Path(command[-1]).write_bytes(b'partial')
        raise TimeoutError('interrupted')
    monkeypatch.setattr('panel_previews.subprocess.run',fail)
    with pytest.raises(TimeoutError):preview(source,cache)
    assert list(cache.iterdir())==[]


def test_review_pause_resumes_paid_candidate_without_new_generation(tmp_path):
    source=picture(tmp_path/'source.png');target=tmp_path/'out.png'
    runner=object.__new__(qstation.Runner);calls=[]
    def generate(*a,**k):calls.append('generate');return result()
    runner._run=generate
    runner.jobs=SimpleNamespace(download=lambda _,dst:dst.write_bytes(source.read_bytes()))
    def pause(*a,**k):raise qstation.StageFailure('review','ACTION_REQUIRED','approve fallback')
    runner.validate_image_content=pause
    with pytest.raises(qstation.StageFailure,match='approve fallback'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert not target.exists()
    runner.validate_image_content=lambda *a,**k:{'passed':True,'description':'scene','violations':[]}
    runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert target.read_bytes()==source.read_bytes()
    assert calls==['generate']


def test_wrong_requested_model_is_rejected_before_download(tmp_path):
    runner=object.__new__(qstation.Runner);runner._run=lambda *a,**k:result('different_model')
    runner.jobs=SimpleNamespace(download=lambda *a:pytest.fail('download should not occur'))
    with pytest.raises(qstation.StageFailure,match='another requested model'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=tmp_path/'out.png')


def test_provider_alternation_retries_failed_attempt_on_other_provider(tmp_path):
    runner=object.__new__(qstation.Runner)
    runner.image_qc_correction_policy='1';runner.image_provider_alternation=True;providers=[]
    def attempt(_stage,_prompt,_references,*,model,destination,provider="gemini"):
        providers.append(provider)
        if len(providers)==1:
            raise qstation.StageFailure('beat_image_001','FAILED_DOWNLOAD','boom')
        picture(destination,2)
        return qc_result({'passed':True,'review_status':'passed','observations':[],'blocking_violations':[]})
    runner._image_attempt=attempt
    target=tmp_path/'out.png'
    selected=runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert providers==['gemini','chatgpt']
    assert target.is_file()
    iterations=selected.generation_receipt['quality_iterations']
    assert [(item['attempt'],item['provider']) for item in iterations]==[(1,'gemini'),(2,'chatgpt')]
    assert iterations[0]['error'].startswith('FAILED_DOWNLOAD')
    assert selected.generation_receipt['qc_selected_attempt']==2


def test_provider_failure_without_alternation_fails_immediately(tmp_path):
    target=picture(tmp_path/'out.png',9);before=target.read_bytes()
    runner=object.__new__(qstation.Runner);runner.image_qc_correction_policy='1'
    def attempt(*a,**k):
        raise qstation.StageFailure('beat_image_001','FAILED_DOWNLOAD','boom')
    runner._image_attempt=attempt
    with pytest.raises(qstation.StageFailure,match='boom'):
        runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert target.read_bytes()==before


def test_alternation_cycles_back_to_gemini_on_third_attempt(tmp_path):
    runner=object.__new__(qstation.Runner)
    runner.image_qc_correction_policy='2';runner.image_provider_alternation=True;providers=[]
    def attempt(_stage,_prompt,_references,*,model,destination,provider="gemini"):
        providers.append(provider)
        raise qstation.StageFailure('beat_image_001','FAILED_DOWNLOAD','boom')
    runner._image_attempt=attempt
    with pytest.raises(qstation.StageFailure,match='boom'):
        runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=tmp_path/'out.png')
    assert providers==['gemini','chatgpt','gemini']


def test_structured_json_recovers_unescaped_visible_label_quotes():
    raw = (
        '{"passed":false,"description":"book sheet",'
        '"violations":["Readable labels are present: "CLOSED FRONT COVER" and '
        '"WIDE-OPEN TWO-PAGE SPREAD"."]}'
    )
    parsed, repaired = qstation.parse_structured_json(raw)
    assert repaired is True
    assert parsed == {
        "passed": False,
        "description": "book sheet",
        "violations": ['Readable labels are present: "CLOSED FRONT COVER" and "WIDE-OPEN TWO-PAGE SPREAD".'],
    }


def test_structured_json_keeps_valid_json_unchanged():
    parsed, repaired = qstation.parse_structured_json('{"passed":true,"description":"scene","violations":[]}')
    assert repaired is False
    assert parsed == {"passed": True, "description": "scene", "violations": []}


def test_structured_json_recovers_citation_newline_and_one_final_candidate_closer():
    raw = (
        '{"candidates":[{"id":"c3","factual_anchor":"Supported source.\n'
        'Museum citation\n+1","novelty":{"action_family":"comparison"}\n]}'
    )

    parsed, repaired = qstation.parse_structured_json(raw)

    assert repaired is True
    assert parsed == {
        "candidates": [{
            "id": "c3",
            "factual_anchor": "Supported source. Museum citation +1",
            "novelty": {"action_family": "comparison"},
        }],
    }


def test_json_repair_excerpt_includes_the_invalid_response_ending():
    raw = "start" + "x" * 2_100 + "missing-final-closer"
    excerpt = qstation.json_repair_excerpt(raw)

    assert excerpt.startswith("start")
    assert excerpt.endswith("missing-final-closer")
    assert "[middle omitted]" in excerpt


def test_structured_json_does_not_accept_unrelated_malformed_json():
    with pytest.raises(json.JSONDecodeError):
        qstation.parse_structured_json('{"passed": false "violations": []}')


def _attempt_runner(tmp_path, output_images):
    source = picture(tmp_path / 'source.png')
    runner = object.__new__(qstation.Runner)
    runner._run = lambda *a, **k: SimpleNamespace(
        job_id='t', status='completed', answer=None, output_images=list(output_images),
        generation_receipt={'notes': ['artifact_source=download']}, elapsed_seconds=1.0)
    seen = []

    def fake_download(src, dst):
        seen.append(src)
        dst.write_bytes(source.read_bytes())

    runner.jobs = SimpleNamespace(download=fake_download)
    runner.image_qc_disabled_for = lambda stage: True
    return runner, seen


def test_multi_image_turn_keeps_first_instead_of_failing(tmp_path):
    runner, seen = _attempt_runner(tmp_path, ['a.png', 'b.png', 'c.png'])
    target = tmp_path / 'out.png'
    result = runner._image_attempt('book_cover', 'scene', [], model='nano_banana_2',
                                   destination=target, provider='chatgpt')
    assert seen == ['a.png']
    assert target.is_file()
    assert result.output_images == ['a.png']


def test_empty_image_turn_still_fails_closed(tmp_path):
    runner, seen = _attempt_runner(tmp_path, [])
    with pytest.raises(qstation.StageFailure, match='returned no images'):
        runner._image_attempt('book_cover', 'scene', [], model='nano_banana_2',
                              destination=tmp_path / 'out.png', provider='chatgpt')
    assert seen == []


def test_structured_json_strips_prose_wrapped_around_object():
    raw = 'Here is my review:\n{"passed":true,"description":"scene","violations":[]}\nLet me know if you need more.'
    parsed, repaired = qstation.parse_structured_json(raw)
    assert repaired is True
    assert parsed == {"passed": True, "description": "scene", "violations": []}


def test_structured_json_completes_truncated_verdict_without_changing_passed():
    raw = '{"passed": false,\n"description": "A bordered wash area with framed sand and driftwood'
    parsed, repaired = qstation.parse_structured_json(raw)
    assert repaired is True
    assert parsed["passed"] is False
    assert parsed["description"].startswith("A bordered wash area")


def test_structured_json_completes_truncated_open_arrays():
    raw = '{"passed":true,"description":"scene","violations":["minor frame'
    parsed, repaired = qstation.parse_structured_json(raw)
    assert repaired is True
    assert parsed["passed"] is True


def test_complete_truncated_json_leaves_balanced_or_mismatched_text_alone():
    assert qstation.complete_truncated_json('{"a":1}') == '{"a":1}'
    assert qstation.complete_truncated_json('{"a":1]') == '{"a":1]'


def test_json_looks_truncated_detects_partial_objects():
    assert qstation._json_looks_truncated('{"passed": false,\n"description": "cut off') is True
    assert qstation._json_looks_truncated('{"passed":true,"description":"ok"}') is False
    assert qstation._json_looks_truncated('not json at all') is False


def test_json_correction_prompt_names_truncation_only_for_partial_objects():
    truncated = qstation.Runner._json_correction_prompt('task', '{"passed": "cut', 'boom')
    assert 'cut off' in truncated
    balanced = qstation.Runner._json_correction_prompt('task', '{"passed": true "violations": []}', 'boom')
    assert 'cut off' not in balanced
    assert 'not valid JSON' in balanced


def test_json_escalation_reasks_unrepairable_output_and_parses():
    runner = object.__new__(qstation.Runner)
    calls = []
    good = '{"passed":true,"description":"ok","violations":[]}'
    bad = '{"passed": false "violations": []}'
    def fake_text(label, prompt, *, references=()):
        calls.append((label, prompt))
        return bad if len(calls) == 1 else good
    runner.text = fake_text
    assert runner.json('probe_stage', 'task') == {"passed": True, "description": "ok", "violations": []}
    assert [label for label, _ in calls] == ['probe_stage_json1', 'probe_stage_json2']
    assert 'not valid JSON' in calls[1][1]


def test_json_persistent_malformation_falls_back_to_gemini_in_auto_mode():
    runner = object.__new__(qstation.Runner)
    runner.chatgpt_fallback_mode = 'auto'
    runner.text = lambda label, prompt, *, references=(): '{"passed": tru'
    runner._run = lambda label, question, *, provider, mode, references=(): SimpleNamespace(
        answer='{"passed":true,"description":"via gemini","violations":[]}')
    runner.state = SimpleNamespace(mark=lambda *a, **k: None)
    assert runner.json('probe_stage', 'task') == {"passed": True, "description": "via gemini", "violations": []}


def test_json_persistent_malformation_parks_for_approval_instead_of_dying():
    runner = object.__new__(qstation.Runner)
    runner.chatgpt_fallback_mode = 'approval'
    runner.text = lambda label, prompt, *, references=(): '{"passed": tru'
    def boom(*a, **k):
        raise qstation.StageFailure('probe_stage', 'FAILED', 'transport down')
    runner._run = boom
    runner._consume_fallback_approval = lambda label: False
    def need_approval(label, failure):
        raise qstation.StageFailure(label, 'ACTION_REQUIRED', 'approval needed')
    runner._require_fallback_approval = need_approval
    with pytest.raises(qstation.StageFailure, match='approval needed'):
        runner.json('probe_stage', 'task')
