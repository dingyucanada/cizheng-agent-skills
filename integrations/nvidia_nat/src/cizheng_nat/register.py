"""Discoverable official NAT entry point; dependencies are resolved by Builder."""
import asyncio
import json
from importlib.metadata import PackageNotFoundError, version

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import FunctionRef
from nat.data_models.function import FunctionBaseConfig
from pydantic import Field

from .evidence import encoded, parse_request

# Preserve the runtime-only install; profiling remains an explicit optional extra.
try:
    version("nvidia-nat-profiler")
except PackageNotFoundError:
    def track_function(fn):
        return fn
else:
    from nat.plugins.profiler.decorators.function_tracking import track_function


class RetrieveConfig(FunctionBaseConfig, name="cizheng_evidence_retrieve"):
    """Search and actually read only explicitly bound Cizheng source versions."""
    data_dir: str = Field(min_length=1)
    max_tool_calls: int = Field(default=20, ge=1, le=20)
    max_seconds: float = Field(default=300, gt=0, le=300)


class VerifyConfig(FunctionBaseConfig, name="cizheng_evidence_verify"):
    """Match citation identity against this run's immutable read receipt."""
    data_dir: str = Field(min_length=1)


class WorkflowConfig(FunctionBaseConfig, name="cizheng_evidence_workflow"):
    """Compose actual registered retrieval and verification functions."""
    retrieve: FunctionRef
    verify: FunctionRef


@register_function(config_type=RetrieveConfig)
async def register_retrieve(config: RetrieveConfig, builder: Builder):
    from .evidence import retrieve_evidence

    @track_function
    async def retrieve(message: str) -> str:
        result = await asyncio.to_thread(retrieve_evidence, config.data_dir, message,
                                         config.max_tool_calls, config.max_seconds)
        return encoded(result)

    yield FunctionInfo.from_fn(retrieve, description="Case-scoped frozen source retrieval; no model calls.")


@register_function(config_type=VerifyConfig)
async def register_verify(config: VerifyConfig, builder: Builder):
    from .evidence import verify_evidence

    @track_function
    async def verify(message: str) -> str:
        return encoded(await asyncio.to_thread(verify_evidence, config.data_dir, message))

    yield FunctionInfo.from_fn(verify, description="Verify citation versions, hashes, and locators actually read.")


@register_function(config_type=WorkflowConfig)
async def register_workflow(config: WorkflowConfig, builder: Builder):
    retrieve = await builder.get_function(config.retrieve)
    verify = await builder.get_function(config.verify)

    @track_function
    async def workflow(message: str) -> str:
        request = parse_request(message)
        receipt = json.loads(await retrieve.ainvoke(message))
        payload = {"run_id": receipt["run_id"], "manifest_sha256": receipt["manifest_sha256"],
                   "case_id": request.case_id, "expected_case_revision": request.expected_case_revision,
                   "citations": [citation.model_dump() for citation in request.citations]}
        return await verify.ainvoke(encoded(payload))

    yield FunctionInfo.from_fn(workflow, description="Offline deterministic reference integrity workflow; no AI conclusion.")


# Evaluation is an optional official package, independent of evidence runtime.
try:
    version("nvidia-nat-eval")
except PackageNotFoundError:
    pass
else:
    from . import evaluators  # noqa: F401
