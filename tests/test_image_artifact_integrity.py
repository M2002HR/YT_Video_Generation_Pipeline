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
