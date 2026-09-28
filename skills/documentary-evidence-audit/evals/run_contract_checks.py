"""Execute structured fixture boundaries; no model/remote/professional evaluation."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from pydantic import ValidationError
from cizheng.agent import tools_for_mode
from cizheng import schemas as S
from cizheng.skill_runtime import SkillRuntime


def run():
    fixture = json.loads(Path(__file__).with_name('evals.json').read_text())
    for case in fixture['cases']:
        declared_applicable = (case['research_task'] == 'documentary_audit'
                               and case['intent'] in fixture['allowed_intents'])
        assert declared_applicable is case['expected_trigger'], case['id']
    tools = tools_for_mode('skills', 'documentary_audit')
    forbidden = {'inspect_images', 'inspect_region', 'record_assessment'}
    assert not forbidden.intersection(tools)
    required = {'read_case', 'read_case_records', 'read_evidence_document', 'read_knowledge',
                'record_documentary_findings', 'build_opinion'}
    assert required.issubset(tools)
    skill = SkillRuntime(ROOT/'skills').catalog()[fixture['skill']]
    assert skill['metadata']['expert-review'] == 'pending'
    for invalid in ({'document_id':'synthetic', 'limit':4}, {'document_id':'synthetic', 'offset':-1}):
        try:
            S.ReadEvidenceDocument.model_validate(invalid)
        except ValidationError:
            continue
        raise AssertionError('Oversized/negative reads must be rejected')
    print(json.dumps({'scope':'synthetic structured fixture/software contract only',
                      'trigger_cases':len(fixture['cases']), 'passed':True,
                      'model_calls':0, 'expert_review':'pending'}, ensure_ascii=False))


if __name__ == '__main__':
    run()
