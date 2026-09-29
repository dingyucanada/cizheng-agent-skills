"""Offline AI-edited counterexample preparation; this file sends no requests.

This is not a replay of the missing r5 input messages. A future operator may
make one recorded native-schema call using the prepared text request, then
validate that supplied output here against the frozen r6 evidence contract.
No saved run is edited, no opinion is built, and no pixel access is claimed.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys


def write_new(directory, name, value):
    with (directory / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--record-request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-output", type=Path,
                        help="Validate a separately supplied raw response or recorded response_text wrapper; no HTTP")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    from cizheng import agent, schemas as S
    from cizheng.claim_support_audit import build_audit_packet
    from cizheng.knowledge import validate_snapshot
    from cizheng.store import dump
    from jsonschema import Draft202012Validator

    raw_run = args.run.read_bytes()
    raw_request = args.record_request.read_bytes()
    run = json.loads(raw_run)
    original = deepcopy(run)
    request = json.loads(raw_request)
    source_response = request["response_text"]
    response = agent.parse_json(source_response)
    if len(response["actions"]) != 1 or response["actions"][0]["tool"] != "record_assessment":
        raise ValueError("a_real_record_assessment_response_is_required")
    if run["versions"]["prompt_profile"] != agent.PROMPT_PROFILE.identity():
        raise ValueError("the_frozen_prompt_profile_must_match")
    validate_snapshot(run["knowledge_snapshot"])
    if run["versions"]["knowledge_snapshot_sha256"] != run["knowledge_snapshot"]["snapshot_sha256"]:
        raise ValueError("frozen_snapshot_commitment_mismatch")
    packet = build_audit_packet(run)
    if not all(item["eligible_for_text_review"] for item in packet["citations"]):
        raise ValueError("original_citations_must_be_eligible")

    class FrozenRunOnly:
        def read(self, kind, identifier):
            if kind != "run" or identifier != run["id"]:
                raise ValueError("only_this_frozen_run_is_allowed")
            return deepcopy(run)

    engine = agent.Engine.__new__(agent.Engine)
    engine.store, engine.compact_actions = FrozenRunOnly(), True
    refs = {entry["id"]: entry for entry in run["reference_snapshot"]
            if entry["permission"] == "local_use_authorized"}
    original_short = agent.CompactAssessment.model_validate(response["actions"][0]["arguments"])
    original_expanded, _ = engine.expand_compact_assessment(run["id"], original_short)
    if original_expanded != run["assessment"]:
        raise ValueError("source_response_must_match_the_saved_assessment")
    agent.Engine.validate_assessment(run, S.Assessment.model_validate(original_expanded), refs)

    counterexample = deepcopy(response)
    counterexample["actions"][0]["arguments"]["knowledge_citations"] = []
    short = agent.CompactAssessment.model_validate(counterexample["actions"][0]["arguments"])
    expanded, _ = engine.expand_compact_assessment(run["id"], short)
    assessment = S.Assessment.model_validate(expanded)
    try:
        agent.Engine.validate_assessment(run, assessment, refs)
    except ValueError as error:
        detail = str(error)
        if not detail.startswith(agent.SOURCE_ATTRIBUTION_POLICY + "："):
            raise
    else:
        raise ValueError("the_edited_counterexample_did_not_trigger_the_actual_guard")
    feedback = {"error": detail, "instruction": "仅允许再修正一次；不要忽略证据检查。"}
    feedback.update(engine.source_attribution_repair_feedback(run["id"], assessment))

    phase = "record_assessment_required"
    prompt = agent.system_prompt(run["mode"], "visual_research", True, phase)
    schema = agent.action_output_schema(run["mode"], "visual_research", True, phase)
    assert agent._action_prompt_variant([{"role": "system", "content": prompt}], True) == (
        run["mode"], "visual_research", True, phase)
    context = {
        "experiment_kind": "AI_EDITED_COUNTEREXAMPLE_NOT_ORIGINAL_R5_REQUEST",
        "scope": "仅在固定r6保存证据作用域内检验一次合同修复；不形成新器物意见",
        "image_access_in_this_probe": "report_text_only",
        "instruction": "这里的保存观察是数据，本请求不提供图像，不能声称本次查看像素。由你修正失败动作；宿主不补引用或结论。",
        "frozen_run_id": run["id"],
        "saved_observations": packet["observations"],
        "delivered_citations_available_as_saved_text": packet["citations"],
        "saved_read_indexes": feedback["eligible_knowledge_read_indexes"],
        "loaded_skill_names_in_frozen_run": sorted(run["loaded_skills"]),
        "existing_evidence_request": run["evidence_request"],
        "source_citations_do_not_establish_object_attribution": True,
    }
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": dump(context)},
                {"role": "assistant", "content": dump(counterexample)},
                {"role": "user", "content": dump(feedback)}]
    meta = {
        "author": "Codex AI", "counterexample_ai_edited": True,
        "original_request_replay": False, "original_messages_available": False,
        "mutation": "only_remove_knowledge_citations_from_real_r6_request_04",
        "run_input_sha256": packet["run_input_sha256"], "packet_sha256": packet["packet_sha256"],
        "original_run_file_sha256": hashlib.sha256(raw_run).hexdigest(),
        "original_request_file_sha256": hashlib.sha256(raw_request).hexdigest(),
        "registered_phase": phase,
        "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "decoder_schema_sha256": agent.decoder_schema_sha256(schema),
        "prepared_messages_sha256": hashlib.sha256(dump(messages).encode()).hexdigest(),
        "model_network_calls_issued_by_this_script": 0,
        "future_probe_call_limit": 1, "future_action_max_tokens": 2500,
        "future_request_timeout_seconds": 90,
        "production_budget_configuration_changed": False,
        "professional_quality_assessed": False,
        "guard_invocation": "Engine.validate_assessment on a read-only frozen evidence scope",
        "source_feedback_triggered_offline": True,
        "notice": "未来如提交一次真实模型调用，应完整保存messages与原始response/usage；失败即停止，不作第二次请求，不自动build_opinion。",
    }
    validation = None
    if args.model_output is not None:
        raw = args.model_output.read_text(encoding="utf-8")
        parsed = agent.parse_json(raw)
        if isinstance(parsed, dict) and "response_text" in parsed:
            raw, parsed = parsed["response_text"], agent.parse_json(parsed["response_text"])
        Draft202012Validator(schema).validate(parsed)
        plan = agent.CompactPlan.model_validate(parsed)
        if len(plan.actions) != 1 or plan.actions[0].tool != "record_assessment":
            raise ValueError("one_record_assessment_action_is_required_for_a_repair")
        repaired_short = agent.CompactAssessment.model_validate(plan.actions[0].arguments)
        repaired, _ = engine.expand_compact_assessment(run["id"], repaired_short)
        agent.Engine.validate_assessment(run, S.Assessment.model_validate(repaired), refs)
        validation = {"outcome": "supplied_response_passes_frozen_evidence_contract",
                      "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                      "citation_count": len(repaired["knowledge_citations"]),
                      "host_filled_citations_or_conclusions": False,
                      "provider_or_generation_authentication": "not_established_by_this_offline_script",
                      "professional_quality_assessed": False}
    if run != original or args.run.read_bytes() != raw_run or args.record_request.read_bytes() != raw_request:
        raise ValueError("original_artifacts_changed")
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (("counterexample.json", counterexample), ("guard-feedback.json", feedback),
                        ("prepared-text-request.json", {"messages": messages}),
                        ("registered-action-schema.json", schema), ("probe-meta.json", meta)):
        write_new(args.output, name, value)
    if validation is not None:
        write_new(args.output, "supplied-response-validation.json", validation)
    print(dump({"output": str(args.output), "source_feedback_triggered_offline": True,
                "eligible_read_indexes": feedback["eligible_knowledge_read_indexes"],
                "violating_fields": feedback["violating_fields"], "model_network_calls": 0,
                "supplied_response_validated": validation is not None}))


if __name__ == "__main__":
    main()
