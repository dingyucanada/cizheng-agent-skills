"""Exact excerpt delivery contracts, original/compact; no provider or truth proof."""
import asyncio
import time
from copy import deepcopy

import pytest

from cizheng import agent, schemas as S
from cizheng.agent import _ToolResultMessage, knowledge_body_identity
from cizheng.knowledge import read_snapshot
from cizheng.review_client import KNOWLEDGE_BODY_FIELDS, cited_knowledge_references
from cizheng.store import Problem, digest
from test_source_attribution_gate import reader, deliver, selected_opinion, OfflineDelivery


def shorter_read(reader, length=8):
    """Register a real read_snapshot excerpt as a synthetic future short-read receipt.

    Engine currently defaults to 800; this controlled receipt fixture checks the
    transport/provenance contract without changing its tool API or mocking charge.
    """
    store, engine, run_id, original = reader
    run = store.read('run', run_id)
    engine.store.charge(run_id, 'tool_calls')
    result = read_snapshot(run['knowledge_snapshot'], original['source']['document_id'],
                           original['chunks'][0]['chunk_id'], limit=1, max_chars=length)
    chunk = result['chunks'][0]
    receipt = {key: chunk[key] for key in KNOWLEDGE_BODY_FIELDS}
    if engine.compact_actions:
        index = max(item.get('read_index', 0) for item in run['read_knowledge']) + 1
        receipt.update(run_id=run_id, read_index=index)
        chunk.update(run_id=run_id, read_index=index)
    store.update_run(run_id, lambda value: value['read_knowledge'].append(receipt))
    return result, receipt


def preview(reader):
    store, engine, run_id, _ = reader
    asyncio.run(engine.tool(run_id, 'record_assessment', S.Assessment.model_validate(selected_opinion(reader))))
    return cited_knowledge_references(store.read('run', run_id))


def test_legitimate_shorter_delivered_read_has_its_own_body_proof(reader):
    store, _, run_id, _ = reader
    result, receipt = shorter_read(reader)
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    run = store.read('run', run_id)
    expected = knowledge_body_identity(receipt)
    assert expected == digest({key: receipt[key] for key in KNOWLEDGE_BODY_FIELDS})
    assert run['main_seen_knowledge_body_sha256'] == [expected]
    event = [event for event in run['events'] if event['type'] == 'model'][-1]
    assert event['outcome'] == 'succeeded' and event['successful_knowledge_body_sha256'] == [expected]
    references, bindings = preview(reader)
    assert references[receipt['chunk_id']]['excerpt'] == receipt['text']
    assert len(references[receipt['chunk_id']]['excerpt']) == 8
    assert bindings[receipt['chunk_id']]['body_sha256'] == expected
    assert bindings[receipt['chunk_id']]['snippet_start'] == 0
    assert bindings[receipt['chunk_id']]['snippet_end'] == 8


@pytest.mark.parametrize('long_first', [True, False], ids=['unexposed-long-first', 'unexposed-long-last'])
def test_short_exposed_long_only_read_never_discloses_the_longer_body(reader, long_first):
    store, _, run_id, _ = reader
    result, short = shorter_read(reader)
    def order(value):
        long = value['read_knowledge'][0]
        value['read_knowledge'] = [long, short] if long_first else [short, long]
    store.update_run(run_id, order)
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    references, _ = preview(reader)
    run = store.read('run', run_id)
    long = next(receipt for receipt in run['read_knowledge'] if len(receipt['text']) > 8)
    assert knowledge_body_identity(short) in run['main_seen_knowledge_body_sha256']
    assert knowledge_body_identity(long) not in run['main_seen_knowledge_body_sha256']
    assert references[short['chunk_id']]['excerpt'] == short['text']
    assert references[short['chunk_id']]['excerpt'] != long['text']


def test_longer_body_only_becomes_eligible_after_actual_successful_delivery(reader):
    store, _, run_id, original = reader
    short_result, short = shorter_read(reader)
    deliver(reader, _ToolResultMessage('read_knowledge', short_result))
    # The original longer read is deliberately first in the receipt list.
    first, _ = preview(reader)
    assert first[short['chunk_id']]['excerpt'] == short['text']
    deliver(reader, _ToolResultMessage('read_knowledge', original))
    second, _ = cited_knowledge_references(store.read('run', run_id))
    assert second[short['chunk_id']]['excerpt'] == original['chunks'][0]['text']


def test_failed_action_never_records_body_delivery(reader):
    store, _, run_id, _ = reader
    result, _ = shorter_read(reader)
    class Failed(OfflineDelivery):
        async def complete(self, messages, timeout):
            raise TimeoutError('SYNTHETIC failed delivery')
    with pytest.raises(TimeoutError):
        deliver(reader, _ToolResultMessage('read_knowledge', result), Failed())
    run = store.read('run', run_id)
    assert not run.get('main_seen_knowledge_body_sha256')
    event = [event for event in run['events'] if event['type'] == 'model'][-1]
    assert event['outcome'] == 'failed' and event['successful_knowledge_body_sha256'] == []


def test_final_real_budget_charge_failure_never_records_body_delivery(reader):
    store, _, run_id, _ = reader
    result, _ = shorter_read(reader)
    class Expires(OfflineDelivery):
        async def complete(self, messages, timeout):
            store.update_run(run_id, lambda value: value.update(started_at=time.time() - 301))
            return await super().complete(messages, timeout)
    with pytest.raises(Problem, match='预算'):
        deliver(reader, _ToolResultMessage('read_knowledge', result), Expires())
    run = store.read('run', run_id)
    assert not run.get('main_seen_knowledge_body_sha256')
    event = [event for event in run['events'] if event['type'] == 'model'][-1]
    assert event['outcome'] == 'failed' and event['successful_knowledge_body_sha256'] == []


def test_legacy_paragraph_hash_or_compact_index_does_not_create_retroactive_body_proof(reader):
    store, _, run_id, _ = reader
    result, receipt = shorter_read(reader)
    deliver(reader, _ToolResultMessage('read_knowledge', result))
    asyncio.run(reader[1].tool(run_id, 'record_assessment', S.Assessment.model_validate(selected_opinion(reader))))
    store.update_run(run_id, lambda value: value.pop('main_seen_knowledge_body_sha256'))
    run = store.read('run', run_id)
    assert run['main_seen_knowledge_receipt_sha256']
    if reader[1].compact_actions:
        assert receipt['read_index'] in run['compact_seen_read_indexes']
    with pytest.raises(Problem, match='确切片段'):
        cited_knowledge_references(run)
    assert 'main_seen_knowledge_body_sha256' not in store.read('run', run_id)


@pytest.mark.parametrize('change', ['changed_text', 'changed_range', 'boolean_range', 'wrong_kind'])
def test_body_proof_requires_exact_canonical_receipt_text_range_and_kind(reader, change):
    store, _, run_id, _ = reader
    result, _ = shorter_read(reader)
    changed = deepcopy(result)
    chunk = changed['chunks'][0]
    if change == 'changed_text':
        chunk['text'] += '伪造'
    elif change == 'changed_range':
        chunk['snippet_end'] += 1
    elif change == 'boolean_range':
        chunk['snippet_start'] = False
    else:
        chunk['content_kind'] = 'metadata'
    deliver(reader, _ToolResultMessage('read_knowledge', changed))
    assert not store.read('run', run_id).get('main_seen_knowledge_body_sha256')


def test_proven_body_range_must_still_match_the_frozen_snapshot(reader):
    store, _, run_id, _ = reader
    result, receipt = shorter_read(reader)
    # A canonical receipt is not sufficient if it describes a false frozen span.
    forged = deepcopy(receipt)
    forged['snippet_start'], forged['snippet_end'] = 1, 9
    forged_result = deepcopy(result)
    forged_result['chunks'][0].update(snippet_start=1, snippet_end=9)
    store.update_run(run_id, lambda value: value['read_knowledge'].append(forged))
    deliver(reader, _ToolResultMessage('read_knowledge', forged_result))
    assert knowledge_body_identity(forged) in store.read('run', run_id)['main_seen_knowledge_body_sha256']
    with pytest.raises(Problem, match='确切片段'):
        preview(reader)
