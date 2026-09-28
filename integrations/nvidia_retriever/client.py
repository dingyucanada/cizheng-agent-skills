"""Rank only explicitly bound frozen authorized text using a private NeMo NIM.

No database, crawler, image upload, generated evidence, or read receipt is used.
The host must still read returned chunk IDs with its existing read_snapshot tool.
An embedding score is semantic similarity, never a credibility/confidence score.
"""
from dataclasses import dataclass
import copy
import ipaddress
import json
import math
from urllib.parse import urlsplit

import httpx

IDENTITY_FIELDS = ("document_id", "document_revision", "document_sha256",
                   "chunk_id", "chunk_sha256", "locator")
MAX_CHUNKS = 512
MAX_INPUT_CHARS = 2000
MAX_RESPONSE_BYTES = 2_000_000


class RetrieverError(ValueError):
    """Bounded error codes, with no source text or credential-bearing details."""


def _endpoint(base_url):
    try:
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            raise ValueError
        if parsed.query or parsed.fragment or parsed.path.rstrip("/") not in ("", "/v1"):
            raise ValueError
        address = ipaddress.ip_address(parsed.hostname)
        # Literal addresses avoid DNS rebinding. Link-local and special addresses
        # are excluded; approved deployments can use an SSH loopback tunnel.
        private = ((address.version == 4 and any(address in ipaddress.ip_network(net)
                    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
                   or (address.version == 6 and address in ipaddress.ip_network("fc00::/7")))
        if not (address.is_loopback or private):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise RetrieverError("private_literal_endpoint_required") from None
    return base_url.rstrip("/").removesuffix("/v1")


def _vector(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 8192:
        raise RetrieverError("invalid_embedding_dimensions")
    try:
        if any(type(number) not in (int, float) or not math.isfinite(number) for number in value):
            raise RetrieverError("invalid_embedding_values")
        norm = math.sqrt(sum(number * number for number in value))
    except OverflowError:
        raise RetrieverError("invalid_embedding_values") from None
    if not math.isfinite(norm) or norm == 0:
        raise RetrieverError("invalid_embedding_norm")
    return tuple(number / norm for number in value)


@dataclass(frozen=True)
class SnapshotIndex:
    snapshot_sha256: str
    model: str
    runtime_identity: str
    chunk_json: tuple[str, ...]
    vectors: tuple[tuple[float, ...], ...]


class RetrieverClient:
    def __init__(self, base_url, model, runtime_identity, *, transport=None, timeout=20.0):
        self.base_url = _endpoint(base_url)
        if not isinstance(model, str) or not 1 <= len(model) <= 200:
            raise RetrieverError("embedding_model_required")
        if not isinstance(runtime_identity, str) or not runtime_identity.startswith("sha256:") or len(runtime_identity) != 71:
            raise RetrieverError("pinned_runtime_identity_required")
        try:
            int(runtime_identity[7:], 16)
        except ValueError:
            raise RetrieverError("pinned_runtime_identity_required") from None
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise RetrieverError("invalid_timeout")
        self.model, self.runtime_identity = model, runtime_identity
        self.http = httpx.Client(timeout=timeout, follow_redirects=False,
                                 trust_env=False, transport=transport)

    def close(self):
        self.http.close()

    def _embeddings(self, texts, input_type):
        if not texts:
            return ()
        if not 1 <= len(texts) <= 8 or any(not isinstance(text, str) or not 1 <= len(text) <= MAX_INPUT_CHARS for text in texts):
            raise RetrieverError("embedding_input_budget_exceeded")
        try:
            with self.http.stream("POST", self.base_url + "/v1/embeddings", json={
                "model": self.model, "input": texts, "input_type": input_type,
                "modality": "text", "embedding_type": "float", "encoding_format": "float"}) as response:
                if response.status_code != 200:
                    raise RetrieverError("embedding_service_error")
                content = bytearray()
                for part in response.iter_bytes():
                    if len(content) + len(part) > MAX_RESPONSE_BYTES:
                        raise RetrieverError("embedding_response_too_large")
                    content.extend(part)
                result = json.loads(content)
        except httpx.HTTPError:
            raise RetrieverError("embedding_transport_error") from None
        except (json.JSONDecodeError, UnicodeError):
            raise RetrieverError("embedding_response_not_json") from None
        if not isinstance(result, dict) or result.get("model") != self.model:
            raise RetrieverError("embedding_model_identity_changed")
        rows = result.get("data")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise RetrieverError("embedding_response_count_mismatch")
        mapped = {}
        for row in rows:
            if not isinstance(row, dict) or type(row.get("index")) is not int or row["index"] not in range(len(texts)) or row["index"] in mapped:
                raise RetrieverError("embedding_response_index_mismatch")
            mapped[row["index"]] = _vector(row.get("embedding"))
        vectors = tuple(mapped[index] for index in range(len(texts)))
        if len({len(vector) for vector in vectors}) != 1:
            raise RetrieverError("embedding_dimensions_changed")
        return vectors

    def build_index(self, snapshot, expected_snapshot_sha256, allowed_bindings):
        """Validate the host's frozen identity before sending authorized passages.

        allowed_bindings must be the case's exact version bindings. This refuses
        a whole-library snapshot or sources later rebound to a different version.
        The caller supplies the SHA already frozen in its run, not a new SHA
        computed from an untrusted retrieval response.
        """
        from cizheng.knowledge import sha, validate_snapshot
        try:
            frozen = copy.deepcopy(validate_snapshot(snapshot))
            if frozen["snapshot_sha256"] != expected_snapshot_sha256:
                raise RetrieverError("frozen_snapshot_identity_changed")
            fields = ("document_id", "document_revision", "document_sha256")
            supplied = [tuple(binding[field] for field in fields) for binding in allowed_bindings]
            actual = [tuple(entry["source"][field] for field in fields) for entry in frozen["sources"]]
            if len(set(supplied)) != len(supplied) or len(set(actual)) != len(actual) or set(actual) != set(supplied):
                raise RetrieverError("case_source_boundary_mismatch")
            chunks = []
            seen = set()
            for entry in frozen["sources"]:
                source = entry["source"]
                if source["rights"] != "authorized_text":
                    continue
                for chunk in entry["chunks"]:
                    if any(chunk[field] != source[field] for field in ("document_id", "document_revision")):
                        raise RetrieverError("paragraph_source_identity_changed")
                    if sha({"text": chunk["text"], "locator": chunk["locator"]}) != chunk["chunk_sha256"]:
                        raise RetrieverError("paragraph_content_identity_changed")
                    if not 1 <= len(chunk["text"]) <= MAX_INPUT_CHARS or not chunk["locator"]:
                        raise RetrieverError("paragraph_input_budget_exceeded")
                    identity = (chunk["document_id"], chunk["chunk_id"])
                    if identity in seen:
                        raise RetrieverError("duplicate_paragraph_identity")
                    seen.add(identity)
                    chunks.append({**{field: chunk[field] for field in IDENTITY_FIELDS if field != "document_sha256"},
                                   "document_sha256": source["document_sha256"], "text": chunk["text"]})
            if len(chunks) > MAX_CHUNKS:
                raise RetrieverError("corpus_budget_exceeded")
        except RetrieverError:
            raise
        except Exception:
            raise RetrieverError("invalid_authorized_snapshot") from None
        vectors = []
        for start in range(0, len(chunks), 8):
            vectors.extend(self._embeddings([chunk["text"] for chunk in chunks[start:start + 8]], "passage"))
        if vectors and len({len(vector) for vector in vectors}) != 1:
            raise RetrieverError("embedding_dimensions_changed")
        return SnapshotIndex(expected_snapshot_sha256, self.model, self.runtime_identity,
                             tuple(json.dumps(chunk, ensure_ascii=False, sort_keys=True) for chunk in chunks), tuple(vectors))

    def search(self, index, query, *, expected_snapshot_sha256, limit=8):
        if not isinstance(index, SnapshotIndex) or index.snapshot_sha256 != expected_snapshot_sha256:
            raise RetrieverError("frozen_snapshot_identity_changed")
        if index.model != self.model or index.runtime_identity != self.runtime_identity:
            raise RetrieverError("embedding_runtime_identity_changed")
        if not isinstance(query, str) or not 1 <= len(query) <= 200 or type(limit) is not int or not 1 <= limit <= 8:
            raise RetrieverError("invalid_search_budget")
        if len(index.chunk_json) != len(index.vectors):
            raise RetrieverError("index_shape_changed")
        if not index.vectors:
            return {"snapshot_sha256": index.snapshot_sha256, "results": [], "read_receipt_created": False}
        vector = self._embeddings([query], "query")[0]
        if any(len(stored) != len(vector) for stored in index.vectors):
            raise RetrieverError("embedding_dimensions_changed")
        matches = []
        for chunk_json, stored in zip(index.chunk_json, index.vectors):
            chunk = json.loads(chunk_json)
            # Candidate data is supplied by this local immutable index, never by
            # the service response. The host re-reads before granting citations.
            score = sum(x * y for x, y in zip(vector, stored))
            matches.append({**{field: chunk[field] for field in IDENTITY_FIELDS}, "semantic_score": score})
        matches.sort(key=lambda result: (-result["semantic_score"], result["document_id"], result["chunk_id"]))
        return {"snapshot_sha256": index.snapshot_sha256, "embedding_model": self.model,
                "embedding_runtime_identity": self.runtime_identity, "results": matches[:limit],
                "read_receipt_created": False, "claim_support_assessed": False,
                "notice": "semantic_score 是相似性排序分，不是真伪、可靠性或置信概率；候选段落必须经原阅读工具读取后才可引用。"}
