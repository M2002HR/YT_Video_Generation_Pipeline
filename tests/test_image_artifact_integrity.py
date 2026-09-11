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
import run_question_harvest_pipeline as qh
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
    runner=object.__new__(qh.Runner)
    runner._run=lambda *a,**kw:result(verified=False)
    runner.jobs=SimpleNamespace(download=lambda *a:pytest.fail('invalid model downloaded'))
    with pytest.raises(qh.StageFailure):
        runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert target.read_bytes()==before
    assert list(tmp_path.glob('.*.png'))==[]


def test_failed_content_does_not_publish_candidate(tmp_path):
    source=picture(tmp_path/'source.png');target=tmp_path/'out.png'
    runner=object.__new__(qh.Runner);runner._run=lambda *a,**k:result()
    runner.jobs=SimpleNamespace(download=lambda _,dst:dst.write_bytes(source.read_bytes()))
    runner.json=lambda *a,**k:{'passed':False,'description':'character sheet','violations':['not a scene']}
    with pytest.raises(qh.StageFailure,match='content QC'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert not target.exists()
    assert list(tmp_path.glob('.*.png'))==[]


def qc_result(check):
    item = result()
    item.generation_receipt['quality_check'] = check
    return item


def test_zero_qc_policy_reports_noncritical_findings_without_regeneration(tmp_path):
    runner=object.__new__(qh.Runner);runner.image_qc_correction_policy='0';calls=[]
    def attempt(_stage,_prompt,_references,*,model,destination):
        calls.append(destination);picture(destination,1)
        return qc_result({'passed':True,'review_status':'passed_with_warnings',
                          'observations':['minor framing issue'],'blocking_violations':[]})
    runner._image_attempt=attempt
    target=tmp_path/'out.png'
    selected=runner.image('beat_image_001','scene',[],model='nano_banana_2',destination=target)
    assert len(calls)==1 and target.is_file()
    assert selected.generation_receipt['qc_policy']=='0'
    assert selected.generation_receipt['qc_selected_attempt']==1


def test_one_qc_correction_uses_previous_candidate_as_a_quality_floor(tmp_path):
    runner=object.__new__(qh.Runner);runner.image_qc_correction_policy='1';calls=[]
    checks=[
        {'passed':True,'review_status':'passed_with_warnings','observations':['cropping is tight'],'blocking_violations':[]},
        {'passed':True,'review_status':'passed','observations':[],'blocking_violations':[]},
    ]
    def attempt(_stage,prompt,references,*,model,destination):
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
    runner=object.__new__(qh.Runner);runner.image_qc_correction_policy='2';calls=[]
    checks=[
        {'passed':True,'observations':['minor issue'],'blocking_violations':[]},
        {'passed':True,'observations':['minor issue','new defect'],'blocking_violations':[]},
        {'passed':False,'observations':[],'blocking_violations':['style continuity drift: wrong medium']},
    ]
    expected_first=picture(tmp_path/'expected.png',1).read_bytes()
    def attempt(_stage,_prompt,_references,*,model,destination):
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
    runner=object.__new__(qh.Runner);runner.image_qc_correction_policy='strict';calls=[]
    def attempt(_stage,_prompt,_references,*,model,destination):
        calls.append(destination);picture(destination,len(calls))
        return qc_result({'passed':True,'observations':['unresolved polish issue'],'blocking_violations':[]})
    runner._image_attempt=attempt
    with pytest.raises(qh.StageFailure,match='after 3 attempts'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert len(calls)==3 and target.read_bytes()==before


def test_minor_visual_qc_findings_are_accepted_and_preserved(tmp_path):
    candidate=picture(tmp_path/'candidate.png')
    runner=object.__new__(qh.Runner)
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
    runner=object.__new__(qh.Runner)
    runner.json=lambda *a,**k:{
        'passed':False,
        'description':'a character turnaround sheet instead of the requested scene',
        'violations':['A character turnaround was generated instead of a requested scene.'],
    }
    with pytest.raises(qh.StageFailure,match='content QC rejected'):
        runner.validate_image_content('world_keyframe','single host-free scene',candidate)


def test_reviewer_cannot_escalate_a_minor_finding_to_blocking(tmp_path):
    candidate=picture(tmp_path/'candidate.png')
    runner=object.__new__(qh.Runner)
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
    runner=object.__new__(qh.Runner)
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
    with pytest.raises(qh.StageFailure,match='content QC rejected'):
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
    runner=object.__new__(qh.Runner);calls=[]
    def generate(*a,**k):calls.append('generate');return result()
    runner._run=generate
    runner.jobs=SimpleNamespace(download=lambda _,dst:dst.write_bytes(source.read_bytes()))
    def pause(*a,**k):raise qh.StageFailure('review','ACTION_REQUIRED','approve fallback')
    runner.validate_image_content=pause
    with pytest.raises(qh.StageFailure,match='approve fallback'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert not target.exists()
    runner.validate_image_content=lambda *a,**k:{'passed':True,'description':'scene','violations':[]}
    runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=target)
    assert target.read_bytes()==source.read_bytes()
    assert calls==['generate']


def test_wrong_requested_model_is_rejected_before_download(tmp_path):
    runner=object.__new__(qh.Runner);runner._run=lambda *a,**k:result('different_model')
    runner.jobs=SimpleNamespace(download=lambda *a:pytest.fail('download should not occur'))
    with pytest.raises(qh.StageFailure,match='another requested model'):
        runner.image('world_keyframe','scene',[],model='nano_banana_2',destination=tmp_path/'out.png')


def test_structured_json_recovers_unescaped_visible_label_quotes():
    raw = (
        '{"passed":false,"description":"book sheet",'
        '"violations":["Readable labels are present: "CLOSED FRONT COVER" and '
        '"WIDE-OPEN TWO-PAGE SPREAD"."]}'
    )
    parsed, repaired = qh.parse_structured_json(raw)
    assert repaired is True
    assert parsed == {
        "passed": False,
        "description": "book sheet",
        "violations": ['Readable labels are present: "CLOSED FRONT COVER" and "WIDE-OPEN TWO-PAGE SPREAD".'],
    }


def test_structured_json_keeps_valid_json_unchanged():
    parsed, repaired = qh.parse_structured_json('{"passed":true,"description":"scene","violations":[]}')
    assert repaired is False
    assert parsed == {"passed": True, "description": "scene", "violations": []}


def test_structured_json_does_not_accept_unrelated_malformed_json():
    with pytest.raises(json.JSONDecodeError):
        qh.parse_structured_json('{"passed": false "violations": []}')
