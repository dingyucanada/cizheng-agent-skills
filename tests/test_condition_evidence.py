"""Located condition records; entirely synthetic tests, no model or external calls."""
import copy

import pytest
from pydantic import ValidationError

from cizheng.business_records import ConditionCheckIn
from cizheng.store import Problem, Store
from test_business_records import service, client, new_case, mutation, attachment, check, add_knowledge


def located_attachment(document):
    return {'kind': 'attachment', 'document_id': document['id'], 'locator': '合成TXT第1行', 'sha256': document['sha256']}


def test_explicit_document_contract_requires_location(service):
    store, knowledge, records = service
    case = new_case(store)
    with pytest.raises(ValidationError, match='至少需要'):
        ConditionCheckIn.model_validate(check(case, evidence=[]))
    with pytest.raises(ValidationError, match='至少需要'):
        records.add_condition_check(case['id'], check(case, evidence=[]))
    assert store.read('case', case['id'])['condition_checks'] == []


def test_real_api_document_location_and_unlocated_legacy_contract(client):
    app, api, headers = client
    case = new_case(app.state.store)
    route = '/api/cases/'+case['id']
    added = api.post(route+'/evidence-documents', headers=headers, json=attachment(case))
    assert added.status_code == 201
    case, document = added.json()['case'], added.json()['document']
    explicit_missing = api.post(route+'/condition-checks', headers=headers, json=check(case, evidence=[]))
    assert explicit_missing.status_code == 422
    valid_body = check(case, evidence=[located_attachment(document)])
    original = api.post(route+'/condition-checks', headers=headers, json=valid_body)
    assert original.status_code == 201, original.text
    assert api.post(route+'/condition-checks', headers=headers, json=valid_body).json() == original.json()
    current = original.json()['case']
    record = original.json()['check']
    assert record['evidence'][0]['artifact_id'] == document['artifact_id']
    assert record['evidence'][0]['sha256'] == document['sha256']
    assert record['located_evidence_status'] == 'located_not_authenticity_verified'
    assert record['evidence_read_or_verified'] is record['authenticity_verified'] is False
    invalid = api.post(route+'/condition-checks', headers=headers,
        json=check(current, evidence=[located_attachment(document) | {'sha256':'0'*64}]))
    assert invalid.status_code == 422
    assert app.state.store.read('case', case['id'])['revision'] == current['revision']
    legacy = api.post(route+'/condition-checks', headers=headers, json=check(current))
    assert legacy.status_code == 201
    assert legacy.json()['check']['evidence'] == []
    assert legacy.json()['check']['located_evidence_status'] == 'legacy_unlocated_operator_declaration'
    assert '未进行资料核对' in legacy.json()['check']['notice']
    assert legacy.json()['case']['condition_checks'][0] == record


def test_foreign_attachment_condition_and_corrupt_sha_rejected(service):
    store, knowledge, records = service
    own, foreign = new_case(store), new_case(store)
    saved = records.add_document(foreign['id'], attachment(foreign))
    reference = located_attachment(saved['document'])
    with pytest.raises(Problem, match='属于本案'):
        records.add_condition_check(own['id'], check(own, evidence=[reference]))
    with store.tx() as db:
        db.execute('UPDATE blobs SET bytes=? WHERE id=?', (b'corrupt', saved['document']['artifact_id']))
    with pytest.raises(Problem) as bad:
        records.add_condition_check(foreign['id'], check(saved['case'], evidence=[reference]))
    assert bad.value.status == 409


def test_knowledge_condition_requires_case_pin_exact_revision_and_hash(service):
    store, knowledge, records = service
    case = new_case(store)
    source = add_knowledge(knowledge)
    chunk = knowledge.source(source['document_id'])['chunks'][0]
    reference = {'kind':'knowledge', 'document_id':source['document_id'], 'revision':1,
                 'chunk_id':chunk['chunk_id'], 'document_sha256':source['document_sha256'],
                 'chunk_sha256':chunk['chunk_sha256'], 'locator':chunk['locator']}
    with pytest.raises(Problem, match='已关联本案'):
        records.add_condition_check(case['id'], check(case, evidence=[reference]))
    case = store.link_document(case['id'], mutation(case) | {'document_id':source['document_id'],
        'document_revision':1, 'document_sha256':source['document_sha256']})
    saved = records.add_condition_check(case['id'], check(case, evidence=[reference]))
    original = copy.deepcopy(saved['check'])
    revised = knowledge.add_document({'document_id':source['document_id'], 'expected_revision':1,
        'title':source['title'], 'institution':source['institution'], 'source_url':source['source_url'],
        'rights':'authorized_text', 'rights_note':'本测试原创内容', 'scope':'协议测试', 'text':'后来更改的知识段落'})['source']
    assert revised['revision'] == 2
    again = records.add_condition_check(case['id'], check(saved['case'], evidence=[reference]))
    assert again['check']['evidence'] == original['evidence']
    for patch in ({'revision':2}, {'document_sha256':'0'*64}, {'chunk_sha256':'0'*64}, {'locator':'假定位'}):
        with pytest.raises(Problem):
            records.add_condition_check(case['id'], check(again['case'], evidence=[reference | patch]))
    assert Store(store.root).read('case', case['id'])['condition_checks'][0] == original


def test_existing_condition_history_preserved_and_other_methods_can_be_unlocated(service):
    store, knowledge, records = service
    case = new_case(store)
    old_record = {'id':'legacy-condition', 'method':'document', 'observation':'过去未定位声明', 'case_revision':1}
    with store.tx() as db:
        case['condition_checks'] = [copy.deepcopy(old_record)]
        store.put(db, 'case', case)
    for method in ('image', 'in_person'):
        result = records.add_condition_check(case['id'], check(case, method=method, evidence=[]))
        assert result['check']['evidence'] == []
        case = result['case']
    assert Store(store.root).read('case', case['id'])['condition_checks'][0] == old_record
