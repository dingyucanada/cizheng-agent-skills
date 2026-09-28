"""Software contract evaluator, not an LLM-quality or ceramic-accuracy score."""
import json

from nat.builder.builder import EvalBuilder
from nat.builder.evaluator import EvaluatorInfo
from nat.cli.register_workflow import register_evaluator
from nat.data_models.evaluator import EvalInputItem, EvaluatorBaseConfig
from nat.plugins.eval.data_models.evaluator_io import EvalOutputItem
from nat.plugins.eval.evaluator.base_evaluator import BaseEvaluator


class ReferenceContractConfig(EvaluatorBaseConfig, name="cizheng_reference_contract"):
    """Check explicit expected software statuses and the zero-inference boundary."""
    pass


class ReferenceContractEvaluator(BaseEvaluator):
    async def evaluate_item(self, item: EvalInputItem) -> EvalOutputItem:
        try:
            result = json.loads(item.output_obj) if isinstance(item.output_obj, str) else item.output_obj
            expected = json.loads(item.expected_output_obj) if isinstance(item.expected_output_obj, str) else item.expected_output_obj
            failures = [key for key, value in expected.items() if result.get(key) != value]
            if result["usage"]["model_calls"] != 0 or result["inference_performed"] is not False:
                failures.append("zero_inference")
            if not result["review_required"] or result["expert_reviewed"]:
                failures.append("review_boundary")
            if result["usage"]["tool_calls"] > result["usage"]["max_tool_calls"]:
                failures.append("tool_budget")
            return EvalOutputItem(id=item.id, score=0.0 if failures else 1.0,
                                  reasoning={"contract_failures": failures,
                                             "scope": "deterministic software contract only"})
        except (KeyError, TypeError, ValueError):
            return EvalOutputItem(id=item.id, score=0.0, reasoning={"error": "invalid_output_or_reference"})


@register_evaluator(config_type=ReferenceContractConfig)
async def register_reference_contract(config: ReferenceContractConfig, builder: EvalBuilder):
    evaluator = ReferenceContractEvaluator(max_concurrency=builder.get_max_concurrency())
    yield EvaluatorInfo(config=config, evaluate_fn=evaluator.evaluate,
                        description="Case-scoped reference-integrity software contract; not AI efficacy.")
