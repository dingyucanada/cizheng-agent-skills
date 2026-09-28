"""Offline identity/HTTP contracts only; no NVIDIA, model or ceramic evaluation."""
import copy
from dataclasses import replace
import json

import httpx
import pytest

from cizheng.knowledge import KnowledgeStore, sha
from integrations.nvidia_retriever import RetrieverClient, RetrieverError

MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2"
DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def snapshot(tmp_path):
    store = KnowledgeStore(tmp_path)
    source = store.add_document({
        "title": "合成检索合同样例", "institution": "协议测试",
        "source_url": "https://example.org/protocol", "locator": "测试页",
        "rights": "authorized_text", "rights_note": "自创协议文本",
        "scope": "测试", "source_type": "test_fixture",
        "text": "口沿为第一个合同测试段落。\n\n底足为第二个合同测试段落。",
        "limitations": ["不是专业资料或领域评测。"]})["source"]
    binding = {field: source[field] for field in ("document_id", "document_revision", "document_sha256")}
    return store.snapshot(document_ids=[source["document_id"]], bindings=[binding]), [binding]


def client(handler):
    return RetrieverClient("http://127.0.0.1:8003/v1", MODEL, DIGEST,
                           transport=httpx.MockTransport(handler))


def test_real_snapshot_identity_and_response_order(snapshot):
    frozen, bindings = snapshot
    requests = []
    def handler(request):
        assert request.url.path == "/v1/embeddings"
        payload = json.loads(request.content)
        requests.append(payload)
        vectors = [[0, 1], [1, 0]] if payload["input_type"] == "passage" else [[1, 0]]
        return httpx.Response(200, json={"model": MODEL, "data": [
            {"index": index, "embedding": vector} for index, vector in reversed(list(enumerate(vectors)))]})
    service = client(handler)
    index = service.build_index(frozen, frozen["snapshot_sha256"], bindings)
    matches = service.search(index, "底足", expected_snapshot_sha256=frozen["snapshot_sha256"])
    expected = frozen["sources"][0]["chunks"][1]
    assert matches["results"][0]["chunk_id"] == expected["chunk_id"]
    assert matches["results"][0]["chunk_sha256"] == expected["chunk_sha256"]
    assert matches["results"][0]["locator"] == expected["locator"]
    assert matches["results"][0]["semantic_score"] == 1
    assert matches["read_receipt_created"] is False
    assert matches["claim_support_assessed"] is False
    assert "source_url" not in json.dumps(requests)
    assert requests[0]["modality"] == "text"
    service.close()


@pytest.mark.parametrize("change", ["binding", "snapshot", "paragraph"])
def test_unauthorized_or_changed_content_refused_before_http(snapshot, change):
    frozen, bindings = copy.deepcopy(snapshot)
    expected = frozen["snapshot_sha256"]
    if change == "binding":
        bindings = []
    elif change == "snapshot":
        expected = "b" * 64
    else:
        frozen["sources"][0]["chunks"][0]["text"] = "篡改"
        # Even a re-hashed snapshot does not match the previously frozen run SHA.
        frozen["snapshot_sha256"] = sha({key: frozen[key] for key in
            ("schema_version", "indexer_version", "index_version", "sources")})
    service = client(lambda _: pytest.fail("An invalid snapshot must never reach the NIM"))
    with pytest.raises(RetrieverError):
        service.build_index(frozen, expected, bindings)
    service.close()


@pytest.mark.parametrize("endpoint", ["https://api.example.org", "http://169.254.169.254",
    "http://10.1.2.3@203.0.113.1", "http://127.0.0.1/v1?key=secret", "http://localhost:8003"])
def test_public_or_ambiguous_endpoint_refused(endpoint):
    with pytest.raises(RetrieverError, match="private_literal_endpoint_required"):
        RetrieverClient(endpoint, MODEL, DIGEST)


@pytest.mark.parametrize("rows", [[{"index": 8, "embedding": [1]}],
    [{"index": 0, "embedding": [0, 0]}], [{"index": 0, "embedding": [True, 1]}],
    [{"index": 0, "embedding": [float("nan")]}]])
def test_invalid_vectors_and_indices_fail_closed(rows):
    service = client(lambda _: httpx.Response(200, json={"model": MODEL, "data": rows})
        if not any(any(isinstance(x, float) and x != x for x in row["embedding"]) for row in rows)
        else httpx.Response(200, content=b'{"model":"' + MODEL.encode() + b'","data":[{"index":0,"embedding":[NaN]}]}'))
    with pytest.raises(RetrieverError):
        service._embeddings(["合同测试"], "query")
    service.close()


def test_runtime_and_snapshot_changes_do_not_reuse_index(snapshot):
    frozen, bindings = snapshot
    service = client(lambda request: httpx.Response(200, json={"model": MODEL, "data": [
        {"index": n, "embedding": [1, n + 1]} for n, _ in enumerate(json.loads(request.content)["input"])]}))
    index = service.build_index(frozen, frozen["snapshot_sha256"], bindings)
    with pytest.raises(RetrieverError, match="embedding_runtime_identity_changed"):
        service.search(replace(index, runtime_identity="sha256:" + "b" * 64), "口沿",
                       expected_snapshot_sha256=frozen["snapshot_sha256"])
    with pytest.raises(RetrieverError, match="frozen_snapshot_identity_changed"):
        service.search(index, "口沿", expected_snapshot_sha256="b" * 64)
    service.close()


def test_empty_case_makes_no_http_request():
    frozen = {"schema_version": 1, "indexer_version": "cizheng-zh-bigram-v1", "index_version": "c" * 64, "sources": []}
    frozen["snapshot_sha256"] = sha(frozen)
    service = client(lambda _: pytest.fail("An unbound case must not call any embedding service"))
    index = service.build_index(frozen, frozen["snapshot_sha256"], [])
    assert service.search(index, "口沿", expected_snapshot_sha256=frozen["snapshot_sha256"])["results"] == []
    service.close()


@pytest.mark.parametrize("response, error", [
    (httpx.Response(307, headers={"location": "https://api.example.org"}), "embedding_service_error"),
    (httpx.Response(200, json={"model": "different-model", "data": []}), "embedding_model_identity_changed"),
    (httpx.Response(200, content=b"x" * 2_000_001), "embedding_response_too_large"),
    (httpx.Response(200, content=b"not-json"), "embedding_response_not_json"),
    (httpx.Response(200, json={"model": MODEL, "data": []}), "embedding_response_count_mismatch"),
])
def test_service_contract_errors_do_not_retry_or_redirect(response, error):
    called = []
    def handler(request):
        called.append(str(request.url))
        return response
    service = client(handler)
    with pytest.raises(RetrieverError, match=error):
        service._embeddings(["合同测试"], "query")
    assert called == ["http://127.0.0.1:8003/v1/embeddings"]
    service.close()


def test_metadata_only_sources_never_reach_nim(snapshot):
    frozen, bindings = copy.deepcopy(snapshot)
    frozen["sources"][0]["source"]["rights"] = "public_metadata"
    frozen["sources"][0]["chunks"] = []
    frozen["snapshot_sha256"] = sha({key: frozen[key] for key in
        ("schema_version", "indexer_version", "index_version", "sources")})
    service = client(lambda _: pytest.fail("Metadata-only sources must not reach the NIM"))
    index = service.build_index(frozen, frozen["snapshot_sha256"], bindings)
    assert index.vectors == ()
    service.close()
