"""Bounded JSON structure decoding using the released LM Format Enforcer.

Schemas are in-memory JSON, never filenames or remote resources. Numeric range
and research-evidence checks remain the application's original tool contract.
"""
import copy
import hashlib
import importlib.metadata
import json
import math
import re

LMFE_VERSION = "0.11.3"
MAX_SCHEMA_BYTES = 100_000
MAX_SCHEMA_DEPTH = 24
MAX_SCHEMA_NODES = 4096
SAFE_HASH_PATTERN = r"^[a-f0-9]{64}$"
SAFE_COMPACT_TEXT_PATTERN = r"^[A-Za-z0-9一-鿿][^\r\n]{0,39}$"
ANNOTATIONS = {"title", "description", "default"}
KEYWORDS = ANNOTATIONS | {"type", "properties", "required", "additionalProperties",
                         "items", "minItems", "maxItems", "minLength", "maxLength",
                         "pattern", "enum", "const", "anyOf", "oneOf", "$ref", "$defs"}
_tokenizer_cache = None


class _JsonLiteral(str):
    """Unquoted JSON primitive for LMFE 0.11.3's exact-type const dispatch.

    That released parser tests type(value) == str to choose quotes but needs
    string prefix operations on every const. This explicit internal adapter
    preserves false/null/number literals, rather than Python False/None repr.
    """


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


class StructuredFormatError(ValueError):
    """A client requested a malformed or unsupported schema."""


class StructuredDependencyError(RuntimeError):
    """The requested decoder is unavailable; unrestricted fallback is forbidden."""


class StructuredGenerationError(RuntimeError):
    """Generated text failed the requested structure; it is never repaired."""


def canonical_schema(schema):
    try:
        return json.dumps(schema, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise StructuredFormatError("Schema must be finite in-memory JSON") from error


def validate_response_format(value):
    if not isinstance(value, dict) or set(value) != {"type", "json_schema"}:
        raise StructuredFormatError("Only strict json_schema response_format is supported")
    spec = value["json_schema"]
    if value["type"] != "json_schema" or not isinstance(spec, dict):
        raise StructuredFormatError("Only strict json_schema response_format is supported")
    if set(spec) != {"name", "strict", "schema"} or spec["strict"] is not True:
        raise StructuredFormatError("json_schema requires name, strict=true and schema only")
    if not isinstance(spec["name"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", spec["name"]):
        raise StructuredFormatError("Invalid structured schema name")
    encoded = canonical_schema(spec["schema"])
    if len(encoded) > MAX_SCHEMA_BYTES:
        raise StructuredFormatError("Schema exceeds 100000 UTF-8 bytes")
    _compile_schema(spec["schema"])
    return copy.deepcopy(value)


def _compile_schema(schema):
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise StructuredFormatError("Structured output requires an object root schema")
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict) or len(definitions) > 128:
        raise StructuredFormatError("Invalid or excessive local definitions")
    for name in definitions:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
            raise StructuredFormatError("Unsupported local definition name")
    count = 0

    def resolve(node, trail=()):
        if not isinstance(node, dict):
            raise StructuredFormatError("Schema branches must be objects")
        if "$ref" not in node:
            return node
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            raise StructuredFormatError("Only in-memory #/$defs references are supported")
        name = ref[len("#/$defs/"):]
        if name not in definitions or name in trail:
            raise StructuredFormatError("Unknown or cyclic schema reference")
        return resolve(definitions[name], trail + (name,))

    def walk(node, depth=0, trail=()):
        nonlocal count
        count += 1
        if depth > MAX_SCHEMA_DEPTH or count > MAX_SCHEMA_NODES:
            raise StructuredFormatError("Schema depth or node budget exceeded")
        if not isinstance(node, dict) or not node or set(node) - KEYWORDS:
            raise StructuredFormatError("Unsupported JSON Schema keyword or shape")
        for annotation in ("title", "description"):
            if annotation in node and (not isinstance(node[annotation], str) or len(node[annotation]) > 4096):
                raise StructuredFormatError("Schema annotation exceeds its budget")
        if "$defs" in node and depth:
            raise StructuredFormatError("Definitions must be at the schema root")
        if "$ref" in node:
            if set(node) - (ANNOTATIONS | {"$ref"}):
                raise StructuredFormatError("Constraints beside a reference are unsupported")
            ref = node["$ref"]
            target = resolve(node, trail)
            name = ref[len("#/$defs/"):]
            walk(target, depth + 1, trail + (name,))
            return copy.deepcopy(node)
        result = copy.deepcopy(node)
        for union in ("anyOf", "oneOf"):
            if union not in node:
                continue
            options = node[union]
            if set(node) - (ANNOTATIONS | {union}) or not isinstance(options, list) or not 1 <= len(options) <= 32:
                raise StructuredFormatError("Unsupported union schema shape")
            compiled_options = [walk(option, depth + 1, trail) for option in options]
            if union == "oneOf":
                # LMFE's union implementation is inclusive. Disjoint required
                # tool tags make this conversion equivalent to the input oneOf.
                tags = []
                for option in options:
                    branch = resolve(option)
                    tool = branch.get("properties", {}).get("tool", {})
                    tag = tool.get("const")
                    if tag is None and isinstance(tool.get("enum"), list) and len(tool["enum"]) == 1:
                        tag = tool["enum"][0]
                    if branch.get("type") != "object" or "tool" not in branch.get("required", []) or not isinstance(tag, str):
                        raise StructuredFormatError("oneOf requires disjoint mandatory tool tags")
                    tags.append(tag)
                if len(set(tags)) != len(tags):
                    raise StructuredFormatError("Overlapping oneOf tool tags are unsupported")
                result.pop("oneOf")
            result["anyOf"] = compiled_options
            return result
        kind = node.get("type")
        if kind not in ("object", "array", "string", "integer", "number", "boolean", "null"):
            raise StructuredFormatError("Unsupported or missing schema type")
        relevant = {"object": {"properties", "required", "additionalProperties"},
                    "array": {"items", "minItems", "maxItems"},
                    "string": {"minLength", "maxLength", "pattern"}}.get(kind, set())
        if set(node) - (ANNOTATIONS | {"type", "enum", "const", "$defs"} | relevant):
            raise StructuredFormatError("Schema constraints do not match their type")
        if "enum" in node:
            options = node["enum"]
            if not isinstance(options, list) or not 1 <= len(options) <= 128:
                raise StructuredFormatError("Enum budget exceeded or empty enum")
            if kind == "string":
                valid = all(isinstance(item, str) for item in options)
            elif kind in ("integer", "number"):
                valid = all(_finite_number(item) for item in options)
                valid = valid and (kind != "integer" or all(int(item) == item for item in options))
            else:
                valid = False
            if not valid:
                raise StructuredFormatError("Unsupported enum type")
        if "const" in node:
            value = node["const"]
            supported = ((kind == "string" and isinstance(value, str)) or
                         (kind == "boolean" and type(value) is bool) or
                         (kind == "null" and value is None) or
                         (kind in ("number", "integer") and _finite_number(value) and
                          (kind != "integer" or int(value) == value)))
            if not supported or ("enum" in node and value not in node["enum"]):
                raise StructuredFormatError("Constant conflicts with its type or enum")
            if kind != "string":
                result["const"] = _JsonLiteral(json.dumps(value, allow_nan=False, separators=(",", ":")))
        if kind == "object":
            props = node.get("properties", {})
            required = node.get("required", [])
            if not isinstance(props, dict) or len(props) > 128 or not isinstance(required, list):
                raise StructuredFormatError("Invalid object properties or required fields")
            if any(not isinstance(key, str) or len(key) > 128 for key in props):
                raise StructuredFormatError("Invalid property name")
            if any(not isinstance(key, str) or key not in props for key in required) or len(set(required)) != len(required):
                raise StructuredFormatError("Required fields must be unique declared properties")
            result["properties"] = {key: walk(child, depth + 1, trail) for key, child in props.items()}
            extra = node.get("additionalProperties", True)
            if isinstance(extra, dict):
                result["additionalProperties"] = walk(extra, depth + 1, trail)
            elif type(extra) is not bool:
                raise StructuredFormatError("Invalid additionalProperties")
        if kind == "array":
            if not isinstance(node.get("items"), dict):
                raise StructuredFormatError("Arrays require one typed items schema")
            result["items"] = walk(node["items"], depth + 1, trail)
        for lower, upper, expected_kind in (("minItems", "maxItems", "array"), ("minLength", "maxLength", "string")):
            for keyword in (lower, upper):
                if keyword in node and (kind != expected_kind or type(node[keyword]) is not int or not 0 <= node[keyword] <= 2_000_000):
                    raise StructuredFormatError("Invalid length constraint")
            if node.get(lower, 0) > node.get(upper, 2_000_000):
                raise StructuredFormatError("Inconsistent length constraints")
        if "pattern" in node:
            if kind != "string" or node["pattern"] not in (SAFE_HASH_PATTERN, SAFE_COMPACT_TEXT_PATTERN):
                raise StructuredFormatError("Only fixed SHA256 and compact single-line text patterns are supported")
            if node["pattern"] == SAFE_HASH_PATTERN:
                if node.get("minLength", 0) > 64 or node.get("maxLength", 64) < 64:
                    raise StructuredFormatError("Hash pattern conflicts with string length")
            elif node.get("minLength", 0) > 1 or node.get("maxLength", 40) < 40:
                raise StructuredFormatError("Compact text pattern has nonredundant length constraints")
            # Both fixed patterns imply their complete length range. Released
            # LMFE rejects simultaneous pattern/length declarations. Strip only
            # redundant bounds from this parser copy; retain the original schema.
            result.pop("minLength", None)
            result.pop("maxLength", None)
        if "const" in node or "enum" in node:
            values = [node["const"]] if "const" in node else node["enum"]
            if kind == "string" and any(not node.get("minLength", 0) <= len(value) <= node.get("maxLength", 2_000_000) or
                                        ("pattern" in node and not re.fullmatch(node["pattern"], value)) for value in values):
                raise StructuredFormatError("Enum or constant conflicts with its constraints")
        if "$defs" in node:
            result["$defs"] = {key: walk(child, depth + 1, (key,)) for key, child in definitions.items()}
        return result

    return walk(schema)


def make_parser(schema):
    compiled = _compile_schema(schema)
    try:
        if importlib.metadata.version("lm-format-enforcer") != LMFE_VERSION:
            raise StructuredDependencyError("The pinned structured decoder version is required")
        from lmformatenforcer import JsonSchemaParser
        from lmformatenforcer.characterlevelparser import CharacterLevelParserConfig
        from lmformatenforcer.consts import COMPLETE_ALPHABET
    except ImportError as error:
        raise StructuredDependencyError("Structured decoder is not installed") from error
    # The official tokenizer integration replaces the alphabet with its actual
    # vocabulary. Include CJK here for independent character-parser validation.
    alphabet = COMPLETE_ALPHABET + "".join(chr(code) for code in range(0x3400, 0xA000)) + "，。；：、（）《》“”"
    config = CharacterLevelParserConfig(alphabet=alphabet, max_consecutive_whitespaces=12,
                                       force_json_field_order=False, max_json_array_length=256)
    try:
        return JsonSchemaParser(compiled, config=config)
    except Exception as error:
        raise StructuredFormatError("Schema cannot be compiled by the pinned decoder") from error


def build_structured_generation(tokenizer, response_format):
    if response_format is None:
        return None, {"enabled": False}
    validate_response_format(response_format)
    schema = response_format["json_schema"]["schema"]
    parser = make_parser(schema)
    global _tokenizer_cache
    try:
        import transformers.tokenization_utils as tokenization_utils
        if not hasattr(tokenization_utils, "PreTrainedTokenizerBase"):
            # Released LMFE 0.11.3 uses the former import location. This alias
            # points to the existing Transformers 5 class; no core upgrade.
            from transformers import PreTrainedTokenizerBase
            tokenization_utils.PreTrainedTokenizerBase = PreTrainedTokenizerBase
        from lmformatenforcer.integrations.transformers import (
            build_token_enforcer_tokenizer_data, build_transformers_prefix_allowed_tokens_fn)
        if _tokenizer_cache is None or _tokenizer_cache[0] is not tokenizer:
            _tokenizer_cache = (tokenizer, build_token_enforcer_tokenizer_data(tokenizer))
        prefix = build_transformers_prefix_allowed_tokens_fn(_tokenizer_cache[1], parser)
    except ImportError as error:
        raise StructuredDependencyError("Structured decoder integration is unavailable") from error
    metadata = {"enabled": True, "enforced": True, "library": "lm-format-enforcer", "version": LMFE_VERSION,
                "mode": "prefix_allowed_tokens_fn", "schema_sha256": hashlib.sha256(canonical_schema(schema)).hexdigest(),
                "schema_hash_canonicalization": "UTF8 json.dumps(ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)"}
    return prefix, metadata


def output_matches_schema(text, schema):
    """Reject invalid output without changing a byte of the model response."""
    try:
        if len(text.encode("utf-8")) > 200_000:
            return False
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        # Validate the original JSON contract, not the internal literal wrapper.
        _compile_schema(schema)
        compiled = schema
        definitions = compiled.get("$defs", {})

        def valid(item, node):
            if "$ref" in node:
                return valid(item, definitions[node["$ref"][len("#/$defs/"):]])
            if "anyOf" in node:
                return any(valid(item, option) for option in node["anyOf"])
            if "oneOf" in node:
                return sum(valid(item, option) for option in node["oneOf"]) == 1
            kind = node["type"]
            if kind == "object":
                if not isinstance(item, dict) or not set(node.get("required", [])).issubset(item):
                    return False
                props, extra = node.get("properties", {}), node.get("additionalProperties", True)
                return all(valid(child, props[key]) if key in props else
                           (valid(child, extra) if isinstance(extra, dict) else extra)
                           for key, child in item.items())
            if kind == "array":
                return (isinstance(item, list) and node.get("minItems", 0) <= len(item) <= node.get("maxItems", 2_000_000)
                        and all(valid(child, node["items"]) for child in item))
            if kind == "string":
                if not isinstance(item, str) or not node.get("minLength", 0) <= len(item) <= node.get("maxLength", 2_000_000):
                    return False
                if "pattern" in node and not re.fullmatch(node["pattern"], item):
                    return False
            elif kind in ("integer", "number"):
                if type(item) not in (int, float) or not math.isfinite(item) or (kind == "integer" and int(item) != item):
                    return False
            elif kind == "boolean" and type(item) is not bool:
                return False
            elif kind == "null" and item is not None:
                return False
            return ("enum" not in node or item in node["enum"]) and ("const" not in node or item == node["const"])

        return valid(value, compiled)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, UnicodeError):
        return False
