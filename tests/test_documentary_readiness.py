"""Preparation counterexamples, not professional/model performance tests."""
import pytest
from cizheng.knowledge import KnowledgeDocumentIn, KnowledgeStore
from cizheng.preflight import case_preflight
from cizheng.store import Problem
from test_documentary_audit import new_case, mutation, attach, start


@pytest.mark.parametrize('rights', ['unknown', 'public_metadata', 'authorized_text'])
def test_source_card_without_body_cannot_start(tmp_path, rights):
    from cizheng.store import Store
    store = Store(tmp_path)
    case = new_case(store)
    KnowledgeStore(tmp_path).add_document(KnowledgeDocumentIn(
        title='SYNTHETIC unrelated authorized text', rights='authorized_text',
        rights_note='只供另案测试', text='未关联本案的许可段落不得使本案可核查。'))
    source = KnowledgeStore(tmp_path).add_document(KnowledgeDocumentIn(
        title='SYNTHETIC source card without body', rights=rights,
        rights_note='测试元数据，不包含许可正文'))['source']
    case = store.link_document(case['id'], mutation(case) | {
        'document_id': source['document_id'], 'document_revision': 1,
        'document_sha256': source['document_sha256']})
    assert case_preflight(store, case)['next_step'] == 'ask_user'
    with pytest.raises(Problem) as caught:
        start(store, case)
    assert caught.value.status == 422
    assert store.listing('run') == []


def test_pdf_without_txt_has_no_readable_body(tmp_path):
    from cizheng.store import Store
    store = Store(tmp_path)
    case, _ = attach(store, new_case(store), suffix='pdf')
    assert case_preflight(store, case)['next_step'] == 'ask_user'
    with pytest.raises(Problem) as caught:
        start(store, case)
    assert caught.value.status == 422
    assert store.listing('run') == []


def test_readiness_uses_pinned_authorized_revision(tmp_path):
    from cizheng.store import Store
    store = Store(tmp_path)
    case = new_case(store)
    knowledge = KnowledgeStore(tmp_path)
    source = knowledge.add_document(KnowledgeDocumentIn(title='SYNTHETIC pinned text',
        rights='authorized_text', rights_note='原创合成测试', text='第一版许可正文，不是真实文书。'))['source']
    case = store.link_document(case['id'], mutation(case) | {'document_id': source['document_id'],
        'document_revision': 1, 'document_sha256': source['document_sha256']})
    knowledge.add_document(KnowledgeDocumentIn(title=source['title'], document_id=source['document_id'],
        expected_revision=1, rights='unknown', rights_note='第二版只存来源卡'))
    assert case_preflight(store, case)['next_step'] == 'ready_for_analysis'
    _, rid = start(store, case)
    assert store.read('run', rid)['knowledge_snapshot']['sources'][0]['source']['revision'] == 1
