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


@pytest.mark.parametrize("mutation", ["malformed_numeric_bounds", "regex", "cycle", "depth", "bytes", "strict", "unknown", "format", "overlap"])
def test_unsupported_and_excessive_schema_never_silently_falls_back(mutation):
    value = envelope()
    schema = value["json_schema"]["schema"]
    if mutation == "malformed_numeric_bounds":
        schema["properties"]["color"] = {"type": "integer", "minimum": True}
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
                                   cuda=SimpleNamespace(synchronize=lambda: None,
                                       nvtx=SimpleNamespace(range_push=lambda label: None, range_pop=lambda: None)))
    monkeypatch.setattr(adapter, "runtime", runtime)
    monkeypatch.setattr(adapter, "record", logs.append)
    monkeypatch.setattr(adapter, "CudaGenerationMeasurement", Measurement)
    request = adapter.Completion(model=runtime.name, messages=[], response_format=envelope() if formatted else None)
    if valid_output:
        result = adapter.infer(request)
        assert result["choices"][0]["message"]["content"] == raw
        assert ("structured" in result["cizheng_runtime"]) is formatted
    else:
        with pytest.raises(structured.StructuredGenerationError) as rejected:
            adapter.infer(request)
        assert rejected.value.safe_detail() == {
            'type': 'structured_output_validation',
            'schema_sha256': hashlib.sha256(structured.canonical_schema(
                request.response_format['json_schema']['schema'])).hexdigest(),
            'response_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'usage': {'prompt_tokens': 3, 'completion_tokens': 15, 'total_tokens': 18}}
        assert raw not in str(rejected.value)
    assert ("prefix_allowed_tokens_fn" in captured[0]) is formatted
    assert 0 < captured[0]['max_time'] <= 80
    assert logs[0]["structured"]["enabled"] is formatted
    assert "schema" not in logs[0]["structured"]
    assert "color" not in json.dumps(logs)
    assert logs[0]["response_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert logs[0]["cuda"]["status"] == "test_double"
    if formatted:
        assert logs[0]["structured"]["output_valid"] is valid_output
        if valid_output:
            assert result["cizheng_runtime"]["structured"]["output_valid"] is True


@pytest.mark.parametrize("configured,fallback,ids,cap,reached,expected", [
    (7, None, [1, 7], 4, False, ("eos", "stop")),
    ([7, 8], None, [1, 8], 4, True, ("eos", "stop")),
    (7, 8, [1, 8], 4, True, ("deadline", "length")),
    (None, 7, [1, 7], 4, True, ("eos", "stop")),
    (None, 7, [1, 8], 4, True, ("deadline", "length")),
    (7, None, [1, 8], 4, False, ("unknown", "stop")),
    (None, None, [1, 8], 4, True, ("unknown", "stop")),
    ([], 7, [1, 8], 4, True, ("unknown", "stop")),
    (True, 7, [1, 8], 4, True, ("unknown", "stop")),
    ([7, "8"], 7, [1, 8], 4, True, ("unknown", "stop")),
    (7, None, [], 4, True, ("unknown", "stop")),
    (7, None, [1, "8"], 4, True, ("unknown", "stop")),
    (7, None, [1, 7], 2, True, ("token_limit", "length")),
])
def test_termination_uses_only_explicit_eos_token_limit_and_generation_deadline(
        configured, fallback, ids, cap, reached, expected):
    model = SimpleNamespace(generation_config=SimpleNamespace(eos_token_id=configured))
    tokenizer = SimpleNamespace(eos_token_id=fallback)
    assert adapter.generation_termination(model, tokenizer, ids, cap, reached) == expected


@pytest.mark.parametrize("ended,final,eos,valid,cap,expected", [
    (80.01, 8, 7, False, 4, "deadline"),
    (80.01, 7, 7, True, 4, "eos"),
    (1.0, 8, 7, True, 4, "unknown"),
    (1.0, 8, 7, False, 4, "schema_rejection"),
    (80.01, 8, None, False, 4, "schema_rejection"),
    (1.0, 7, 7, True, 2, "token_limit"),
    (1.0, 8, 7, False, 2, "token_limit"),
])
def test_native_deadline_is_not_postprocessing_or_schema_rejection(
        monkeypatch, ended, final, eos, valid, cap, expected):
    """No GPU/parser doubles can infer completion from the decoded JSON."""
    clock, logs = [0.0], []
    class Inputs(dict):
        def to(self, device): return self
    class Output:
        def __getitem__(self, key): return [1, final]
    class Measurement:
        metrics = {"status": "test_double"}
        def __init__(self, torch): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def generate(**kwargs):
        assert 0 < kwargs['max_time'] <= 80 and kwargs['max_new_tokens'] == cap
        clock[0] = ended
        return Output()
    raw = '{"color":"red"}' if valid else '{"color":"green"}'
    def decode(*args, **kwargs):
        clock[0] += 100  # Slow postprocessing must not turn early generation into a deadline.
        return raw
    runtime = adapter.Runtime()
    runtime.processor = SimpleNamespace(tokenizer=SimpleNamespace(eos_token_id=None), decode=decode,
        apply_chat_template=lambda *args, **kwargs: Inputs(input_ids=SimpleNamespace(shape=(1, 3))))
    runtime.model = SimpleNamespace(generate=generate, generation_config=SimpleNamespace(eos_token_id=eos))
    runtime.torch = SimpleNamespace(manual_seed=lambda seed: None, inference_mode=nullcontext,
        cuda=SimpleNamespace(synchronize=lambda: None,
            nvtx=SimpleNamespace(range_push=lambda label: None, range_pop=lambda: None)))
    metadata = {'enabled': True, 'schema_sha256': hashlib.sha256(
        structured.canonical_schema(envelope()['json_schema']['schema'])).hexdigest()}
    monkeypatch.setattr(adapter, 'runtime', runtime)
    monkeypatch.setattr(adapter, 'record', logs.append)
    monkeypatch.setattr(adapter, 'CudaGenerationMeasurement', Measurement)
    monkeypatch.setattr(adapter.time, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(adapter, 'build_structured_generation', lambda *args, **kwargs: (None, dict(metadata)))
    request = adapter.Completion(model=runtime.name, messages=[], max_tokens=cap, response_format=envelope())
    if expected == 'schema_rejection':
        with pytest.raises(structured.StructuredGenerationError) as rejected:
            adapter.infer(request)
        assert rejected.value.usage == {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}
        assert logs[0]['termination'] == 'unknown'
    else:
        result = adapter.infer(request)
        assert result['cizheng_runtime']['termination'] == logs[0]['termination'] == expected
        assert result['choices'][0]['finish_reason'] == ('length' if expected in ('deadline', 'token_limit') else 'stop')
        assert result['choices'][0]['message']['content'] == raw
        assert result['usage'] == {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}
    assert logs[0]['structured']['output_valid'] is valid
    assert logs[0]['response_sha256'] == hashlib.sha256(raw.encode()).hexdigest()


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


def test_bounded_projection_keeps_original_and_all_other_schema_constraints():
    schema = compact_text_schema(description="保留原始合同说明")
    short_text = json.loads(structured.canonical_schema(schema["properties"]["label"]))
    schema["$defs"] = {"ShortText": short_text}
    schema["properties"].update({
        "sha": {"type": "string", "pattern": structured.SAFE_HASH_PATTERN,
                "minLength": 64, "maxLength": 64},
        "labels": {"type": "array", "minItems": 1, "maxItems": 2,
                   "items": {"$ref": "#/$defs/ShortText"}},
        "optional": {"anyOf": [{"type": "null", "const": None},
                                {"type": "string", "pattern": COMPACT_TEXT_PATTERN}]},
    })
    before = structured.canonical_schema(schema)
    projected = structured.bounded_parser_schema(schema)
    expected = json.loads(before)
    for node in (expected["properties"]["label"], expected["$defs"]["ShortText"],
                 expected["properties"]["optional"]["anyOf"][1]):
        node.pop("pattern")
        node["minLength"], node["maxLength"] = 1, 40
    assert projected == expected
    assert structured.canonical_schema(schema) == before
    assert projected is not schema
    assert projected["properties"]["sha"] == schema["properties"]["sha"]
    structured.validate_response_format(envelope(schema))
    structured.validate_response_format(envelope(projected))


@pytest.mark.parametrize("pattern", [r"^[A-Za-z0-9一-鿿].{0,39}$",
    r"^[A-Za-z0-9一-鿿][^\r\n]{0,40}$", "(a+)+$"])
def test_bounded_policy_does_not_strip_unknown_patterns_or_bypass_validation(monkeypatch, pattern):
    schema = compact_text_schema(pattern=pattern)
    before = structured.canonical_schema(schema)
    projected = structured.bounded_parser_schema(schema)
    assert projected == schema
    assert projected["properties"]["label"]["pattern"] == pattern
    monkeypatch.setattr(structured, "make_parser", lambda _: pytest.fail("Validate the original before compiling a projection"))
    with pytest.raises(structured.StructuredFormatError):
        structured.build_structured_generation(None, envelope(schema),
            policy="bounded-semantic-postvalidation-v1")
    assert structured.canonical_schema(schema) == before


def test_default_policy_preserves_strict_prefix_and_original_schema_identity(actual_prefix):
    tokenizer, tensor, _ = actual_prefix
    schema = compact_text_schema()
    before = structured.canonical_schema(schema)
    default_prefix, default_metadata = structured.build_structured_generation(tokenizer, envelope(schema))
    strict_prefix, strict_metadata = structured.build_structured_generation(tokenizer, envelope(schema),
        policy="strict-token-v1")
    tokens = tokenizer.encode("0")
    for char in '{"label":"':
        token = tokenizer.encode(char)[0]
        assert token in default_prefix(0, tensor(tokens))
        assert token in strict_prefix(0, tensor(tokens))
        tokens.append(token)
    assert set(default_prefix(0, tensor(tokens))) == set(strict_prefix(0, tensor(tokens)))
    for char in ('?', '.', ' ', '"'):
        assert tokenizer.encode(char)[0] not in default_prefix(0, tensor(tokens))
    assert default_metadata == strict_metadata
    assert default_metadata["policy"] == "strict-token-v1"
    assert default_metadata["postvalidated_constraints"] == []
    assert default_metadata["decoder_schema_sha256"] == default_metadata["schema_sha256"]
    assert structured.canonical_schema(schema) == before


@pytest.mark.parametrize("label,parser_valid,projected_valid,original_valid", [
    ("A", True, True, True), ("测" * 40, True, True, True), ("?", True, True, False),
    (".", True, True, False), (" ", False, True, False), ("测\n", True, True, False),
    ("测\r", True, True, False), ("\n测", True, True, False), ("", False, False, False),
    ("测" * 41, False, False, False),
])
def test_bounded_parser_lengths_and_original_postvalidation_are_separate(real_parser, label, parser_valid, projected_valid, original_valid):
    schema = compact_text_schema()
    before = structured.canonical_schema(schema)
    projected = structured.bounded_parser_schema(schema)
    text = json.dumps({"label": label}, ensure_ascii=False)
    # Released LMFE rejects a whitespace-only string with minLength=1 even
    # though that JSON value satisfies the projected schema's length bounds.
    # Decoder acceptance can be a strict subset of the projected contract.
    assert parser_accepts(real_parser(projected), text) is parser_valid
    assert structured.output_matches_schema(text, projected) is projected_valid
    assert structured.output_matches_schema(text, schema) is original_valid
    assert structured.canonical_schema(schema) == before


@pytest.mark.parametrize("line_break", ["\r", "\n"])
def test_bounded_parser_does_not_permit_unescaped_json_line_breaks(real_parser, line_break):
    schema = compact_text_schema()
    projected = structured.bounded_parser_schema(schema)
    malformed_json = '{"label":"测' + line_break + '"}'
    assert not parser_accepts(real_parser(projected), malformed_json)
    assert not structured.output_matches_schema(malformed_json, projected)
    assert not structured.output_matches_schema(malformed_json, schema)


def test_bounded_prefix_keeps_empty_and_41st_character_blocked(actual_prefix):
    tokenizer, tensor, _ = actual_prefix
    schema = compact_text_schema()
    prefix, metadata = structured.build_structured_generation(tokenizer, envelope(schema),
        policy="bounded-semantic-postvalidation-v1")
    tokens = tokenizer.encode("0")
    for char in '{"label":"':
        token = tokenizer.encode(char)[0]
        assert token in prefix(0, tensor(tokens))
        tokens.append(token)
    assert tokenizer.encode('"')[0] not in prefix(0, tensor(tokens))
    assert tokenizer.encode('?')[0] in prefix(0, tensor(tokens))
    for char in "测" * 40:
        token = tokenizer.encode(char)[0]
        assert token in prefix(0, tensor(tokens))
        tokens.append(token)
    assert tokenizer.encode("测")[0] not in prefix(0, tensor(tokens))
    for char in '"}':
        token = tokenizer.encode(char)[0]
        assert token in prefix(0, tensor(tokens))
        tokens.append(token)
    assert tokenizer.eos_token_id in prefix(0, tensor(tokens))
    assert metadata["policy"] == "bounded-semantic-postvalidation-v1"
    assert metadata["original_schema_postvalidation_required"] is True
    assert metadata["postvalidated_constraints"] == ["compact-text-pattern"]
    assert metadata["schema_sha256"] == hashlib.sha256(structured.canonical_schema(schema)).hexdigest()
    assert metadata["decoder_schema_sha256"] != metadata["schema_sha256"]


def test_bounded_native_generation_rejects_projected_valid_question_mark_against_original(monkeypatch, actual_prefix):
    tokenizer, tensor, _ = actual_prefix
    schema = compact_text_schema()
    raw = '{"label":"?"}'
    assert structured.output_matches_schema(raw, structured.bounded_parser_schema(schema))
    assert not structured.output_matches_schema(raw, schema)
    class Inputs(dict):
        def to(self, device): return self
    class Output:
        def __getitem__(self, key): return tokenizer.encode(raw)
    class Measurement:
        metrics = {"status": "test_double", "elapsed_ms": 1}
        def __init__(self, torch): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
    generated = []
    def generate(**options):
        prefix = options["prefix_allowed_tokens_fn"]
        tokens = tokenizer.encode("0")
        for char in raw:
            token = tokenizer.encode(char)[0]
            assert token in prefix(0, tensor(tokens))
            tokens.append(token)
        assert tokenizer.eos_token_id in prefix(0, tensor(tokens))
        generated.append(raw)
        return Output()
    runtime = adapter.Runtime()
    runtime.processor = SimpleNamespace(tokenizer=tokenizer, decode=lambda *args, **kwargs: raw,
        apply_chat_template=lambda *args, **kwargs: Inputs(input_ids=SimpleNamespace(shape=(1, 1))))
    runtime.model = SimpleNamespace(generate=generate)
    runtime.torch = SimpleNamespace(manual_seed=lambda seed: None, inference_mode=nullcontext,
        cuda=SimpleNamespace(synchronize=lambda: None,
            nvtx=SimpleNamespace(range_push=lambda label: None, range_pop=lambda: None)))
    logs = []
    monkeypatch.setattr(adapter, "runtime", runtime)
    monkeypatch.setattr(adapter, "record", logs.append)
    monkeypatch.setattr(adapter, "CudaGenerationMeasurement", Measurement)
    monkeypatch.setenv("CIZHENG_SPARK_DECODER_POLICY", "bounded-semantic-postvalidation-v1")
    request = adapter.Completion(model=runtime.name, messages=[], response_format=envelope(schema))
    before = structured.canonical_schema(request.response_format)
    with pytest.raises(structured.StructuredGenerationError) as rejected:
        adapter.infer(request)
    assert generated == [raw]
    assert logs[0]["structured"]["policy"] == "bounded-semantic-postvalidation-v1"
    assert logs[0]["structured"]["output_valid"] is False
    assert logs[0]["decoder_cpu"]["calls"] > 0
    assert logs[0]["response_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert structured.canonical_schema(request.response_format) == before
    assert rejected.value.schema_sha256 == logs[0]['structured']['schema_sha256']
    assert rejected.value.schema_sha256 != logs[0]['structured']['decoder_schema_sha256']
    assert rejected.value.usage == {'prompt_tokens': 1, 'completion_tokens': len(tokenizer.encode(raw)),
                                  'total_tokens': 1 + len(tokenizer.encode(raw))}


def test_native_schema_rejection_has_only_typed_422_safe_metadata(monkeypatch):
    runtime = adapter.Runtime()
    runtime.ready = True
    monkeypatch.setattr(runtime, 'load', lambda: None)
    monkeypatch.setattr(adapter, 'runtime', runtime)
    schema_sha = hashlib.sha256(structured.canonical_schema(envelope()['json_schema']['schema'])).hexdigest()
    usage = {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10}
    rejected = structured.StructuredGenerationError(schema_sha256=schema_sha,
        response_sha256='a' * 64, usage=usage)
    called = []
    def fail(request):
        called.append(request)
        raise rejected
    monkeypatch.setattr(adapter, 'infer', fail)
    with TestClient(adapter.app) as client:
        response = client.post('/v1/chat/completions', json={
            'model': runtime.name, 'messages': [], 'response_format': envelope()})
    assert response.status_code == 422
    assert response.json() == {'detail': rejected.safe_detail()}
    assert len(called) == 1


@pytest.mark.parametrize('error,status', [(TimeoutError('secret timeout'), 500),
    (RuntimeError('secret GPU state'), 500),
    (structured.StructuredFormatError('secret schema'), 422),
    (structured.StructuredDependencyError('secret dependency'), 503)])
def test_other_native_errors_never_use_the_output_repair_marker(monkeypatch, error, status):
    runtime = adapter.Runtime()
    runtime.ready = True
    monkeypatch.setattr(runtime, 'load', lambda: None)
    monkeypatch.setattr(adapter, 'runtime', runtime)
    monkeypatch.setattr(adapter, 'record', lambda value: None)
    def fail(request):
        raise error
    monkeypatch.setattr(adapter, 'infer', fail)
    with TestClient(adapter.app) as client:
        response = client.post('/v1/chat/completions', json={
            'model': runtime.name, 'messages': [], 'response_format': envelope()})
    assert response.status_code == status
    assert 'structured_output_validation' not in response.text
    assert 'secret' not in response.text


def numeric_schema(kind='number', **constraints):
    return {'type': 'object', 'required': ['value'], 'additionalProperties': False,
            'properties': {'value': {'type': kind, **constraints}}}


@pytest.mark.parametrize('kind', ['number', 'integer'])
def test_numeric_projection_preserves_original_bounds_and_final_range_checks(kind):
    schema = numeric_schema(kind, minimum=0, maximum=1)
    before = structured.canonical_schema(schema)
    validated = structured.validate_response_format(envelope(schema))
    projected = structured.numeric_parser_schema(schema)
    assert projected == numeric_schema(kind)
    assert structured._compile_schema(schema) == projected
    assert validated['json_schema']['schema'] == schema
    assert structured.canonical_schema(schema) == before
    for value, expected in [(0, True), (1, True), (-1, False), (2, False), (True, False),
                            ('0', False), (None, False), (0.5, kind == 'number')]:
        assert structured.output_matches_schema(json.dumps({'value': value}), schema) is expected


@pytest.mark.parametrize('bounds', [
    {'minimum': True}, {'maximum': False}, {'minimum': '0'}, {'maximum': None},
    {'minimum': float('nan')}, {'maximum': float('inf')}, {'minimum': -float('inf')},
    {'minimum': 10**400}, {'minimum': 2, 'maximum': 1},
])
def test_malformed_nonfinite_or_reversed_numeric_bounds_are_not_projected_away(bounds):
    with pytest.raises(structured.StructuredFormatError):
        structured.validate_response_format(envelope(numeric_schema(**bounds)))


@pytest.mark.parametrize('constraints', [
    {'minimum': 0, 'maximum': 1, 'enum': [0, 2]},
    {'minimum': 0, 'maximum': 1, 'const': -1},
    {'exclusiveMinimum': 0}, {'exclusiveMaximum': 1}, {'multipleOf': 0.5},
])
def test_numeric_enum_conflicts_and_unimplemented_keywords_remain_rejected(constraints):
    with pytest.raises(structured.StructuredFormatError):
        structured.validate_response_format(envelope(numeric_schema(**constraints)))


def test_numeric_bounds_on_non_numeric_nodes_and_nonfinite_outputs_still_fail():
    with pytest.raises(structured.StructuredFormatError):
        structured.validate_response_format(envelope(numeric_schema('string', minimum=0)))
    schema = numeric_schema(minimum=0, maximum=1)
    for raw in ('{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}', '{"value":1e400}'):
        assert not structured.output_matches_schema(raw, schema)
    schema = numeric_schema('integer', minimum=1.5, maximum=2.5)
    assert structured.output_matches_schema('{"value":2}', schema)
    assert not structured.output_matches_schema('{"value":1}', schema)


def test_numeric_projection_visits_schema_edges_without_rewriting_annotation_data():
    annotation = {'type': 'number', 'minimum': 7, 'maximum': 9}
    schema = numeric_schema(minimum=0, maximum=1, default=annotation)
    schema['$defs'] = {'Bounded': {'type': 'number', 'minimum': 0, 'maximum': 1}}
    schema['properties']['extra'] = {'anyOf': [{'$ref': '#/$defs/Bounded'}, {'type': 'null'}]}
    before = structured.canonical_schema(schema)
    structured.validate_response_format(envelope(schema))
    projected = structured.numeric_parser_schema(schema)
    assert projected['properties']['value'] == {'type': 'number', 'default': annotation}
    assert projected['$defs']['Bounded'] == {'type': 'number'}
    assert projected['properties']['extra'] == schema['properties']['extra']
    assert structured.canonical_schema(schema) == before


def test_real_parser_full_original_vision_schema_and_range_postvalidation(real_parser):
    from cizheng.agent import vision_output_schema
    schema = vision_output_schema(['m2', 'm1'])
    value = {'observations': [{'media_id': media_id, 'region': [0, 0, 1, 1],
        'visible': '测', 'interpretation': '', 'limitation': ''} for media_id in ('m2', 'm1')]}
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    assert parser_accepts(real_parser(schema), raw) and structured.output_matches_schema(raw, schema)
    missing = json.loads(raw)
    missing['observations'][0].pop('region')
    assert not parser_accepts(real_parser(schema), json.dumps(missing, ensure_ascii=False))
    assert not structured.output_matches_schema(json.dumps(missing), schema)
    outside = json.loads(raw)
    outside['observations'][0]['region'][2] = 2
    outside_raw = json.dumps(outside, ensure_ascii=False, separators=(',', ':'))
    # Numeric syntax is prefix constrained; the unmodified schema rejects range.
    assert parser_accepts(real_parser(schema), outside_raw)
    assert not structured.output_matches_schema(outside_raw, schema)
    unknown = json.loads(raw)
    unknown['observations'][0]['media_id'] = 'other'
    assert not parser_accepts(real_parser(schema), json.dumps(unknown, ensure_ascii=False))
    assert not structured.output_matches_schema(json.dumps(unknown), schema)


def test_real_prefix_vision_metadata_keeps_original_schema_hash(actual_prefix):
    from cizheng.agent import vision_output_schema
    tokenizer, tensor, _ = actual_prefix
    schema = vision_output_schema(['m1'])
    response_format = {'type': 'json_schema', 'json_schema': {
        'name': 'cizheng_observations', 'strict': True, 'schema': schema}}
    before = structured.canonical_schema(response_format)
    prefix, metadata = structured.build_structured_generation(tokenizer, response_format)
    raw = '{"observations":[{"media_id":"m1","region":[0,0,1,1],"visible":"测","interpretation":"","limitation":""}]}'
    tokens = tokenizer.encode('0')
    for character in raw:
        token = tokenizer.encode(character)[0]
        assert token in prefix(0, tensor(tokens))
        tokens.append(token)
    assert tokenizer.eos_token_id in prefix(0, tensor(tokens))
    assert metadata['schema_sha256'] == hashlib.sha256(structured.canonical_schema(schema)).hexdigest()
    assert metadata['decoder_schema_sha256'] == hashlib.sha256(structured.canonical_schema(
        structured.numeric_parser_schema(schema))).hexdigest()
    assert metadata['schema_sha256'] != metadata['decoder_schema_sha256']
    assert metadata['postvalidated_constraints'] == ['inclusive-numeric-range']
    assert structured.canonical_schema(response_format) == before
