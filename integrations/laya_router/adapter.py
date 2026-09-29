"""Explicit optional offline CPU shadow. Not enabled by the case API and never edits indices."""
import hashlib
import os
import json
from pathlib import Path
from cizheng.laya_shadow import run_shadow

OFFICIAL_REPOSITORY = 'https://github.com/NandhaKishorM/laya'
PROBED_OFFICIAL_PACKAGE_VERSION = '0.3.21'


def status():
    # Importing or detecting a package is not a successful model integration.
    return {'enabled':False,'executed_for_ceramics':False,'state':'disabled_pending_cpu_checkpoint_test',
            'scope':'text_next_step_shadow_only','pixels_accepted':False,
            'can_override_priority_index':False,'can_override_review':False,
            'official_repository':OFFICIAL_REPOSITORY}


def predict_local(model_dir, state):
    """Caller explicitly invokes a previously downloaded checkpoint; no automatic model fetch."""
    if not isinstance(state,dict) or set(state)!={'facts','incumbent_next_step','review_required'}:
        raise ValueError('Expected compact saved-fact shadow state')
    facts=state['facts']
    if not isinstance(facts,dict) or set(facts)-{'conflict_dimensions','unknown_dimensions','saved_photo_count','readable_text_count','task'}:
        raise ValueError('Only compact text-task facts are accepted; no image/body/URL fields')
    if len(json.dumps(state,ensure_ascii=False,allow_nan=False))>3000:
        raise ValueError('Text routing state exceeds bounded scope')
    if type(state['review_required']) is not bool or state['incumbent_next_step'] not in ('continue_analysis','request_evidence','out_of_scope'):
        raise ValueError('Invalid authoritative routing state')
    for key in ('saved_photo_count','readable_text_count'):
        if key in facts and (type(facts[key]) is not int or not 0<=facts[key]<=100):
            raise ValueError('Saved counts must be bounded nonnegative integers')
    for key in ('conflict_dimensions','unknown_dimensions'):
        if key in facts and (not isinstance(facts[key],list) or len(facts[key])>6 or any(v not in ('period','kiln','style','provenance','condition','capture') for v in facts[key])):
            raise ValueError('Dimension list must use the fixed local vocabulary')
    if 'task' in facts and (not isinstance(facts['task'],str) or len(facts['task'])>500):
        raise ValueError('Task text exceeds bounded scope')
    root=Path(model_dir).resolve(strict=True)
    if not root.is_dir() or not (root/'config.json').is_file():
        raise ValueError('Use a prepared local checkpoint with config.json')
    files=sorted(root.rglob('*'))
    if any(p.is_symlink() for p in files):
        raise ValueError('Checkpoint symlinks are not accepted')
    hashes={}
    for p in files:
        if p.is_file():
            with p.open('rb') as stream:
                hashes[str(p.relative_to(root))]=hashlib.file_digest(stream,'sha256').hexdigest()
    if not any(p.endswith('.safetensors') for p in hashes):
        raise ValueError('Prepared local checkpoint has no safetensors weights')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    os.environ['OMP_NUM_THREADS']='2';os.environ['MKL_NUM_THREADS']='2'
    import torch
    torch.set_num_threads(2)
    from laya import Agent
    with Agent(str(root),device='cpu') as engine:
        return run_shadow(state,engine,{'device':'cpu','files_sha256':hashes,
                                       'scope':'unvalidated_ceramic_text_shadow'})
