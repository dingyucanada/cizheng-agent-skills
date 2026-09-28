"""Optional decoder contracts: real LMFE parser, no downloaded model or GPU.

Missing decoder dependencies skip only explicitly named real-parser contracts.
Run them in the documented independent environment before enabling deployment.
"""
import hashlib
import json
import re
import string
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from integrations.spark_transformers import adapter
from integrations.spark_transformers import structured_generation as structured


def envelope(schema=None):
    return {"type": "json_schema", "json_schema": {"name": "cizheng_actions", "strict": True,
            "schema": schema or {"type": "object", "additionalProperties": False,
            "properties": {"color": {"type": "string", "enum": ["red", "blue"]}}, "required": ["color"]}}}


@pytest.fixture
def real_parser():
    pytest.importorskip("lmformatenforcer", reason="Optional real decoder contract requires documented isolated environment")
    return structured.make_parser


def parser_accepts(parser, text):
    for character in text:
        if character not in parser.get_allowed_characters():
            return False
        parser = parser.add_character(character)
    return parser.can_end()


def test_real_parser_enforces_enum_and_required_fields(real_parser):
    schema = envelope()["json_schema"]["schema"]
    assert parser_accepts(real_parser(schema), '{"color":"red"}')
    assert not parser_accepts(real_parser(schema), '{"color":"green"}')
    assert not parser_accepts(real_parser(schema), '{}')
    assert not parser_accepts(real_parser(schema), '{"color":"red","extra":1}')


@pytest.mark.parametrize("mode,task", [("skills", "visual_research"), ("plain", "visual_research"),
                                      ("skills", "documentary_audit"), ("plain", "documentary_audit")])
def test_real_parser_compiles_all_actual_application_plans(real_parser, mode, task):
    from cizheng.agent import action_output_schema, decoder_schema_sha256
    schema = action_output_schema(mode, task)
    structured.validate_response_format(envelope(schema))
    assert hashlib.sha256(structured.canonical_schema(schema)).hexdigest() == decoder_schema_sha256(schema)
    text = '{"actions":[{"tool":"read_case","arguments":{}}]}'
    assert parser_accepts(real_parser(schema), text)
    assert structured.output_matches_schema(text, schema)


@pytest.mark.parametrize("mutation", ["missing_scope", "missing_alternatives", "invalid_dimension",
                                      "nine_claims", "empty_comparison", "long_reasoning"])
def test_real_parser_rejects_the_actual_run03_structure_failures(real_parser, mutation):
    from cizheng.agent import action_output_schema
    schema = action_output_schema()
    assessment = {"basic_info": "软件夹具", "scope": "ceramic_research",
        "claims": [{"dimension": dimension, "candidate": "未知", "status": "insufficient",
                    "support": [], "conflict": [], "reasoning_summary": "软件测试"}
                   for dimension in ("period", "kiln", "style")],
        "alternatives": ["证据不足"], "condition_hypotheses": [], "reference_ids": [],
        "reference_comparison": "没有实际参照", "limitations": ["软件测试不评价文物"],
        "revision_explanation": "仅协议测试", "knowledge_citations": []}
    def text():
        return json.dumps({"actions": [{"tool": "record_assessment", "arguments": assessment}]}, ensure_ascii=False)
    assert parser_accepts(real_parser(schema), text())
    if mutation.startswith("missing_"):
        assessment.pop(mutation[len("missing_"):])
    elif mutation == "invalid_dimension":
        assessment["claims"][0]["dimension"] = "shape"
    elif mutation == "nine_claims":
        assessment["claims"] *= 3
    elif mutation == "empty_comparison":
        assessment["reference_comparison"] = ""
    else:
        assessment["claims"][0]["reasoning_summary"] = "测" * 81
    assert not parser_accepts(real_parser(schema), text())
    assert not structured.output_matches_schema(text(), schema)


def test_real_parser_fixed_hash_pattern_and_boolean_literal(real_parser):
    schema = {"type": "object", "required": ["sha", "verified"], "additionalProperties": False,
              "properties": {"sha": {"type": "string", "pattern": structured.SAFE_HASH_PATTERN,
                                     "minLength": 64, "maxLength": 64},
                             "verified": {"type": "boolean", "const": False}}}
    good = json.dumps({"sha": "a" * 64, "verified": False})
    assert parser_accepts(real_parser(schema), good)
    assert not parser_accepts(real_parser(schema), good.replace("false", "true"))
    assert not parser_accepts(real_parser(schema), good.replace("a" * 64, "a" * 63))
    assert structured.output_matches_schema(good, schema)


@pytest.mark.parametrize("ref", ["https://example.invalid/schema", "file:///tmp/link/schema.json",
                                 "../linked-schema.json", "#/$defs/Missing", "#/definitions/K",
                                 "#/$defs/K/properties/color"])
def test_external_file_symlink_and_nonlocal_references_are_rejected(ref):
    schema = envelope()["json_schema"]["schema"]
    schema["properties"]["color"] = {"$ref": ref}
    with pytest.raises(structured.StructuredFormatError):
        structured.validate_response_format(envelope(schema))


@pytest.mark.parametrize("mutation", ["numeric_bounds", "regex", "cycle", "depth", "bytes", "strict", "unknown", "format", "overlap"])
def test_unsupported_and_excessive_schema_never_silently_falls_back(mutation):
    value = envelope()
    schema = value["json_schema"]["schema"]
    if mutation == "numeric_bounds":
        schema["properties"]["color"] = {"type": "integer", "minimum": 1}
    elif mutation == "regex":
        schema["properties"]["color"] = {"type": "string", "pattern": "(a+)+$"}
    elif mutation == "cycle":
        schema["$defs"] = {"K": {"$ref": "#/$defs/K"}}
        schema["properties"]["color"] = {"$ref": "#/$defs/K"}
    elif mutation == "depth":
        child = {"type": "string"}
        for _ in range(30):
            child = {"type": "array", "items": child}
        schema["properties"]["color"] = child
    elif mutation == "bytes":
        schema["description"] = "x" * 100_000
    elif mutation == "strict":
        value["json_schema"]["strict"] = False
    elif mutation == "unknown":
        value["json_schema"]["schema_file"] = "/tmp/schema-symlink"
    elif mutation == "format":
        value["type"] = "json_object"
    else:
        schema["properties"]["color"] = {"oneOf": [{"type": "string"}, {"type": "string"}]}
    with pytest.raises(structured.StructuredFormatError):
        structured.validate_response_format(value)


@pytest.mark.parametrize("mutation", ["schema", "schema_bytes", "malformed_union", "malformed_definition",
                                      "malformed_properties", "messages", "unknown_body", "model_name"])
def test_native_body_caps_and_malformed_schema_do_not_call_the_worker(monkeypatch, mutation):
    runtime = adapter.Runtime()
    runtime.ready = True
    monkeypatch.setattr(runtime, "load", lambda: None)
    monkeypatch.setattr(adapter, "runtime", runtime)
    called = []
    monkeypatch.setattr(adapter, "infer", lambda request: called.append(request))
    body = {"model": runtime.name, "messages": []}
    if mutation == "schema":
        body["response_format"] = {"type": "json_object"}
    elif mutation == "schema_bytes":
        body["response_format"] = envelope()
        body["response_format"]["json_schema"]["schema"]["description"] = "x" * 100_000
    elif mutation in ("malformed_union", "malformed_definition", "malformed_properties"):
        body["response_format"] = envelope()
        schema = body["response_format"]["json_schema"]["schema"]
        if mutation == "malformed_union":
            schema["properties"]["color"] = {"oneOf": [None]}
        elif mutation == "malformed_definition":
            schema["$defs"] = {"K": None}
            schema["properties"]["color"] = {"$ref": "#/$defs/K"}
        else:
            schema["properties"]["color"] = {"oneOf": [{"type": "object", "properties": []}]}
    elif mutation == "messages":
        body["messages"] = [{"role": "user", "content": "x"}] * 65
    elif mutation == "unknown_body":
        body["schema_file"] = "/tmp/link"
    else:
        body["model"] = "x" * 129
    with TestClient(adapter.app) as client:
        assert client.post("/v1/chat/completions", json=body).status_code == 422
    assert called == []


@pytest.fixture
def actual_prefix(monkeypatch, real_parser):
    """Real released prefix builder/core with tiny CPU tokenizer/type bridges.

    Torch/Transformers type bridges replace only absent heavyweight packages;
    LMFE's parser, tokenizer preprocessing and token filtering are not mocked.
    """
    pytest.importorskip("numpy", reason="Optional released prefix module needs documented CPU NumPy dependency")
    class Tensor(list):
        def tolist(self):
            return list(self)
    class Tokenizer:
        chars = list(dict.fromkeys(string.printable + "测软件未知证据不足没有实际参照文物期间窑口风格器形"))
        eos_token_id = len(chars)
        all_special_ids = [eos_token_id]
        def __len__(self):
            return len(self.chars) + 1
        def encode(self, text):
            return [self.chars.index(char) for char in text]
        def decode(self, ids, **kwargs):
            return "".join(self.chars[index] for index in ids if index != self.eos_token_id)
    tf = ModuleType("transformers")
    tf.__path__ = []
    tf.AutoModelForCausalLM = object
    tf.PreTrainedTokenizerBase = Tokenizer
    utils = ModuleType("transformers.tokenization_utils")  # Reproduce Transformers 5 moved class.
    generation = ModuleType("transformers.generation")
    generation.__path__ = []
    logits = ModuleType("transformers.generation.logits_process")
    logits.LogitsProcessor = type("LogitsProcessor", (), {})
    logits.PrefixConstrainedLogitsProcessor = type("PrefixConstrainedLogitsProcessor", (), {})
    torch = ModuleType("torch")
    torch.Tensor = torch.LongTensor = torch.FloatTensor = Tensor
    for name, module in (("transformers", tf), ("transformers.tokenization_utils", utils),
                         ("transformers.generation", generation),
                         ("transformers.generation.logits_process", logits), ("torch", torch)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(structured, "_tokenizer_cache", None)
    return Tokenizer(), Tensor, utils


def test_real_released_prefix_filters_tokens_and_reuses_tokenizer_preprocessing(actual_prefix):
    tokenizer, tensor, legacy_module = actual_prefix
    prefix, metadata = structured.build_structured_generation(tokenizer, envelope())
    assert legacy_module.PreTrainedTokenizerBase is type(tokenizer)
    tokens = tokenizer.encode("0")  # Prompt is not parsed as generated JSON.
    for char in '{"color":"red"}':
        token = tokenizer.encode(char)[0]
        assert token in prefix(0, tensor(tokens))
        tokens.append(token)
    assert tokenizer.eos_token_id in prefix(0, tensor(tokens))
    cache = structured._tokenizer_cache[1]
    another, _ = structured.build_structured_generation(tokenizer, envelope())
    assert structured._tokenizer_cache[1] is cache
    bad = tokenizer.encode("0")
    for char in '{"color":"':
        assert tokenizer.encode(char)[0] in another(0, tensor(bad))
        bad += tokenizer.encode(char)
    assert tokenizer.encode("g")[0] not in another(0, tensor(bad))
    assert metadata["enforced"] is True and metadata["version"] == "0.11.3"
    assert metadata["schema_sha256"] == hashlib.sha256(structured.canonical_schema(envelope()["json_schema"]["schema"])).hexdigest()


@pytest.mark.parametrize("formatted,valid_output", [(False, True), (True, True), (True, False)])
def test_native_generate_receives_real_prefix_and_preserves_unformatted_behavior(monkeypatch, actual_prefix, formatted, valid_output):
    tokenizer, _, _ = actual_prefix
    class Inputs(dict):
        def to(self, device):
            return self
    class Output:
        def __getitem__(self, key):
            return list(range(15))
    class Measurement:
        metrics = {"status": "test_double", "elapsed_ms": 1}
        def __init__(self, torch): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
    captured = []
    logs = []
    raw = '{"color":"red"}' if valid_output else '{"color":"green"}'
    runtime = adapter.Runtime()
    runtime.processor = SimpleNamespace(tokenizer=tokenizer, decode=lambda *args, **kwargs: raw,
        apply_chat_template=lambda *args, **kwargs: Inputs(input_ids=SimpleNamespace(shape=(1, 3))))
    runtime.model = SimpleNamespace(generate=lambda **kwargs: captured.append(kwargs) or Output())
    runtime.torch = SimpleNamespace(manual_seed=lambda seed: None, inference_mode=nullcontext,
                                   cuda=SimpleNamespace(synchronize=lambda: None))
    monkeypatch.setattr(adapter, "runtime", runtime)
    monkeypatch.setattr(adapter, "record", logs.append)
    monkeypatch.setattr(adapter, "CudaGenerationMeasurement", Measurement)
    request = adapter.Completion(model=runtime.name, messages=[], response_format=envelope() if formatted else None)
    if valid_output:
        result = adapter.infer(request)
        assert result["choices"][0]["message"]["content"] == raw
        assert ("structured" in result["cizheng_runtime"]) is formatted
    else:
        with pytest.raises(structured.StructuredGenerationError):
            adapter.infer(request)
    assert ("prefix_allowed_tokens_fn" in captured[0]) is formatted
    assert logs[0]["structured"]["enabled"] is formatted
    assert "schema" not in logs[0]["structured"]
    assert "color" not in json.dumps(logs)
    assert logs[0]["response_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert logs[0]["cuda"]["status"] == "test_double"
    if formatted:
        assert logs[0]["structured"]["output_valid"] is valid_output
        if valid_output:
            assert result["cizheng_runtime"]["structured"]["output_valid"] is True


COMPACT_TEXT_PATTERN = r"^[A-Za-z0-9一-鿿][^\r\n]{0,39}$"


def compact_text_schema(**constraints):
    return {"type": "object", "required": ["label"], "additionalProperties": False,
            "properties": {"label": {"type": "string", "minLength": 1, "maxLength": 40,
                                      "pattern": COMPACT_TEXT_PATTERN, **constraints}}}


def test_fixed_compact_text_only_removes_redundant_lengths_in_parser_copy():
    schema = compact_text_schema()
    before = structured.canonical_schema(schema)
    validated = structured.validate_response_format(envelope(schema))
    compiled = structured._compile_schema(schema)
    assert structured.SAFE_COMPACT_TEXT_PATTERN == COMPACT_TEXT_PATTERN
    assert "minLength" not in compiled["properties"]["label"]
    assert "maxLength" not in compiled["properties"]["label"]
    assert validated["json_schema"]["schema"]["properties"]["label"]["minLength"] == 1
    assert validated["json_schema"]["schema"]["properties"]["label"]["maxLength"] == 40
    assert structured.canonical_schema(schema) == before


def test_real_parser_fixed_compact_text_character_boundaries(real_parser):
    schema = compact_text_schema()
    for label in ("A", "0", "一", "鿿", "测" * 40, "A。", "软件测试"):
        text = json.dumps({"label": label}, ensure_ascii=False)
        assert parser_accepts(real_parser(schema), text), label
        assert structured.output_matches_schema(text, schema), label
    for label in ("", "...", "！！", " ", "#测", "测" * 41, "测\n", "测\r", "\n测"):
        text = json.dumps({"label": label}, ensure_ascii=False)
        assert not parser_accepts(real_parser(schema), text), repr(label)
        assert not structured.output_matches_schema(text, schema), repr(label)
    for line_break in ("\r", "\n"):
        assert not parser_accepts(real_parser(schema), '{"label":"测' + line_break + '"}')


def test_real_released_prefix_fixed_compact_text_blocks_empty_punctuation_and_41st_character(actual_prefix):
    tokenizer, tensor, _ = actual_prefix
    schema = compact_text_schema()
    prefix, metadata = structured.build_structured_generation(tokenizer, envelope(schema))
    tokens = tokenizer.encode("0")
    for char in '{"label":"':
        assert tokenizer.encode(char)[0] in prefix(0, tensor(tokens))
        tokens += tokenizer.encode(char)
    for char in ('"', '.', ' ', '!'):
        assert tokenizer.encode(char)[0] not in prefix(0, tensor(tokens))
    for char in "测" * 40:
        assert tokenizer.encode(char)[0] in prefix(0, tensor(tokens))
        tokens += tokenizer.encode(char)
    allowed = prefix(0, tensor(tokens))
    assert tokenizer.encode("测")[0] not in allowed
    assert tokenizer.encode('"')[0] in allowed
    for char in '"}':
        assert tokenizer.encode(char)[0] in prefix(0, tensor(tokens))
        tokens += tokenizer.encode(char)
    assert tokenizer.eos_token_id in prefix(0, tensor(tokens))
    assert metadata["schema_sha256"] == hashlib.sha256(structured.canonical_schema(schema)).hexdigest()


@pytest.mark.parametrize("label", ['测"试', r"测\试"])
def test_real_parser_documents_escaped_quote_and_backslash_subset(real_parser, actual_prefix, label):
    # Released LMFE regex strings prohibit JSON escaping. These valid original
    # schema values are rejected by the prefix; they are never rewritten.
    schema = compact_text_schema()
    text = json.dumps({"label": label}, ensure_ascii=False)
    assert structured.output_matches_schema(text, schema)
    assert not parser_accepts(real_parser(schema), text)
    tokenizer, tensor, _ = actual_prefix
    prefix, _ = structured.build_structured_generation(tokenizer, envelope(schema))
    tokens = tokenizer.encode("0")
    for char in '{"label":"测':
        assert tokenizer.encode(char)[0] in prefix(0, tensor(tokens))
        tokens += tokenizer.encode(char)
    assert tokenizer.encode('\\')[0] not in prefix(0, tensor(tokens))


def test_fixed_compact_text_final_validation_rejects_dollar_terminal_newline_boundary():
    schema = compact_text_schema()
    assert re.search(COMPACT_TEXT_PATTERN, "测\n") is not None
    assert not structured.output_matches_schema(json.dumps({"label": "测\n"}, ensure_ascii=False), schema)


@pytest.mark.parametrize("constraints", [{"minLength": 2}, {"maxLength": 39}])
def test_fixed_compact_text_nonredundant_lengths_are_rejected(constraints):
    with pytest.raises(structured.StructuredFormatError):
        structured.validate_response_format(envelope(compact_text_schema(**constraints)))


@pytest.mark.parametrize("keyword", ["const", "enum"])
def test_fixed_compact_text_constants_and_enums_keep_pattern_constraints(keyword):
    for label, valid in (("软件测试", True), ("...", False), ("测" * 41, False)):
        schema = compact_text_schema(**{keyword: label if keyword == "const" else [label]})
        if valid:
            structured.validate_response_format(envelope(schema))
            assert structured.output_matches_schema(json.dumps({"label": label}, ensure_ascii=False), schema)
        else:
            with pytest.raises(structured.StructuredFormatError):
                structured.validate_response_format(envelope(schema))


def test_only_exact_fixed_compact_text_pattern_is_whitelisted():
    for pattern in (r"^[A-Za-z0-9一-鿿][\s\S]{0,39}$", r"^[A-Za-z0-9一-鿿][^\r\n]{0,40}$",
                    r"[A-Za-z0-9一-鿿][^\r\n]{0,39}", r"^[A-Za-z0-9一-鿿].{0,39}$", "(a+)+$"):
        schema = compact_text_schema(pattern=pattern)
        with pytest.raises(structured.StructuredFormatError):
            structured.validate_response_format(envelope(schema))
        assert not structured.output_matches_schema('{"label":"A"}', schema)


@pytest.mark.parametrize("mode", ["plain", "skills"])
def test_real_parser_actual_compact_plan_uses_exact_short_text_rule(real_parser, mode):
    from cizheng.agent import action_output_schema
    schema = action_output_schema(mode, "visual_research", compact=True)
    branch = next(branch for branch in schema["properties"]["actions"]["items"]["oneOf"]
                  if branch["properties"]["tool"]["const"] == "record_assessment")
    for field in ("alternatives", "condition_hypotheses"):
        item = branch["properties"]["arguments"]["properties"][field]["items"]
        assert item["pattern"] == COMPACT_TEXT_PATTERN and item["minLength"] == 1 and item["maxLength"] == 40
    structured.validate_response_format(envelope(schema))
    text = '{"actions":[{"tool":"read_case","arguments":{}}]}'
    assert parser_accepts(real_parser(schema), text)
    assert structured.output_matches_schema(text, schema)
