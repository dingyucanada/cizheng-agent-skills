"""Execute selected pinned upstream functions with synthetic external IO.

No torch import, tensor allocation, real checkpoint read or GPU operation.
The source files are read from the installed NIM package. Their full hashes
must equal the public v0.5.16 commit before any function is executed.
"""
import ast
import enum
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

COMMIT = "fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1"
SOURCE_SHA256 = {
    "srt/model_loader/loader.py": "b7f2e19e4d6f37da77e4902e9d88ba1f37295b543deb8f915af3778a4985bd87",
    "srt/model_loader/weight_utils.py": "db4e9b797fbbd3af933323a28415620e7b8425ec9911daba1be734ee3900f526",
    "srt/configs/load_config.py": "524f6191963d5bc6944e7ab64ca1b8debfddaf74689f589cf6191718abd67324",
}


def require_serial_options(value):
    if isinstance(value, str):
        value = json.loads(value)
    if (not isinstance(value, dict) or set(value) != {"enable_multithread_load"}
            or value["enable_multithread_load"] is not False):
        raise ValueError("exact boolean enable_multithread_load=false required")
    return value


def _class(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def _method(class_node, name):
    return next(node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == name)


def _compile(nodes, namespace):
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(module, "<pinned-public-loader-contract>", "exec"), namespace)


def verify_serial_loader(source_root, options, server_args):
    options = require_serial_options(options)
    trees = {}; receipts = []
    for relative, expected in SOURCE_SHA256.items():
        raw = (Path(source_root) / relative).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise ValueError("installed loader differs from fixed public source: " + relative)
        trees[relative] = ast.parse(raw)
        receipts.append({"path": relative, "bytes": len(raw), "sha256": digest})
    if (server_args.weight_loader_disable_mmap is not False
            or server_args.weight_loader_prefetch_checkpoints is not False
            or server_args.weight_loader_drop_cache_after_load is not False):
        raise ValueError("serial mmap with no checkpoint prefetch/cache-drop required")

    def forbidden(*_, **__):
        raise AssertionError("unexpected threaded, prefetch, PT or real model IO")

    # Normalize using the actual LoadConfig methods, replacing only its JSON
    # implementation and unrelated runtime dependency. CPU NIM also constructs
    # the real LoadConfig to verify installed orjson parsing independently.
    config_tree = trees["srt/configs/load_config.py"]
    config_class = _class(config_tree, "LoadConfig")
    normalization = ast.ClassDef(name="ContractLoadConfig", bases=[], keywords=[],
        body=[_method(config_class, "__post_init__"), _method(config_class, "_verify_load_format")],
        decorator_list=[], type_params=[])
    namespace = {"enum": enum, "orjson": SimpleNamespace(loads=json.loads),
                 "is_hip": lambda: False, "logger": SimpleNamespace(info=forbidden)}
    _compile([_class(config_tree, "LoadFormat"), normalization], namespace)
    config = namespace["ContractLoadConfig"]()
    config.model_loader_extra_config = json.dumps(options)
    config.load_format = "auto"; config.ignore_patterns = None; config.modelopt_config = object()
    config.__post_init__()
    assert config.model_loader_extra_config == {"enable_multithread_load": False}
    config.draft_model_idx = None

    selections = []
    def serial_factory(files, **kwargs):
        selections.append({"iterator": "safetensors_weights_iterator", "files": files, "kwargs": kwargs})
        return iter([("contract.weight", "synthetic-no-tensor")])

    loader_tree = trees["srt/model_loader/loader.py"]
    default_class = _class(loader_tree, "DefaultModelLoader")
    default_nodes = [_method(default_class, "__init__"), _method(default_class, "_get_weights_iterator")]
    default_nodes += [node for node in default_class.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "DEFAULT_NUM_THREADS" for target in node.targets)]
    modelopt_class = _class(loader_tree, "ModelOptModelLoader")
    classes = [
        ast.ClassDef(name="BaseModelLoader", bases=[], keywords=[], decorator_list=[],
                     body=[_method(_class(loader_tree, "BaseModelLoader"), "__init__")], type_params=[]),
        ast.ClassDef(name="DefaultModelLoader", bases=[ast.Name(id="BaseModelLoader", ctx=ast.Load())],
                     keywords=[], decorator_list=[], body=default_nodes, type_params=[]),
        ast.ClassDef(name="ModelOptModelLoader", bases=[ast.Name(id="DefaultModelLoader", ctx=ast.Load())],
                     keywords=[], decorator_list=[], body=[_method(modelopt_class, "__init__")], type_params=[]),
    ]
    namespace.update(time=time, get_server_args=lambda: server_args,
        safetensors_weights_iterator=serial_factory,
        buffered_multi_thread_safetensors_weights_iterator=forbidden,
        fastsafetensors_weights_iterator=forbidden, np_cache_weights_iterator=forbidden,
        multi_thread_pt_weights_iterator=forbidden, pt_weights_iterator=forbidden,
        logger=SimpleNamespace(warning=forbidden))
    _compile(classes, namespace)
    loader = namespace["ModelOptModelLoader"](config)
    loader._prepare_weights = lambda *_: ("synthetic", ["synthetic-a", "synthetic-b"], True)
    loader.counter_before_loading_weights = 0.0
    source = SimpleNamespace(model_or_path="synthetic", revision=None, fall_back_to_pt=False,
                             model_config=None, prefix="")
    yielded = list(loader._get_weights_iterator(source))
    assert yielded == [("contract.weight", "synthetic-no-tensor")]
    assert len(selections) == 1 and selections[0]["iterator"] == "safetensors_weights_iterator"
    assert selections[0]["kwargs"]["disable_mmap"] is False
    assert selections[0]["kwargs"]["prefetch"] is False

    # Run the actual serial iterator. Fake safe_open exposes two tiny keys per
    # file. Taking one next() must neither load the second tensor nor open the
    # second shard; no checkpoint file or tensor exists in this contract.
    events = []
    class FakeOpen:
        def __init__(self, path, **kwargs):
            assert kwargs == {"framework": "pt", "device": "cpu"}
            self.path = path
        def __enter__(self):
            events.append(("open", self.path)); return self
        def __exit__(self, *_):
            events.append(("close", self.path))
        def keys(self):
            return ["a", "b"]
        def get_tensor(self, key):
            events.append(("get", self.path, key)); return "synthetic-no-tensor"
    def progress(values, **_):
        return values
    progress._get_free_pos = lambda: 0
    serial_node = next(node for node in trees["srt/model_loader/weight_utils.py"].body
                       if isinstance(node, ast.FunctionDef) and node.name == "safetensors_weights_iterator")
    serial_namespace = {"torch": SimpleNamespace(distributed=SimpleNamespace(is_initialized=lambda: False)),
        "safetensors": SimpleNamespace(safe_open=FakeOpen), "tqdm": progress, "BAR_FORMAT": "",
        "_prefetch_all_checkpoints": forbidden, "_drop_file_cache_after_load": forbidden}
    _compile([serial_node], serial_namespace)
    iterator = serial_namespace["safetensors_weights_iterator"](["synthetic-a", "synthetic-b"],
        disable_mmap=False, prefetch=False, drop_cache_after_load=False)
    assert next(iterator) == ("a", "synthetic-no-tensor")
    assert events == [("open", "synthetic-a"), ("get", "synthetic-a", "a")]
    iterator.close()
    return {"public_commit": COMMIT, "source_files": receipts, "extra_config": options,
            "selected_iterator": selections[0]["iterator"], "iterator_kwargs": selections[0]["kwargs"],
            "selection_verified": True, "lazy_one_tensor_one_shard_verified": True,
            "synthetic_external_io": True, "real_model_weight_tensors_loaded": False,
            "gpu_initialized_by_contract": False, "memory_reduction_measured": False}
