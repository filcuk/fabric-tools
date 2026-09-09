"""Dataflow Gen1 (Power BI) sync operations."""

from fabric_tools.dataflow_gen1.compare import (
    CompareResult,
    compare_dataflow,
    run_compare_batch,
)
from fabric_tools.dataflow_gen1.definition import (
    DefinitionError,
    display_name_from_model,
    load_model,
    model_to_bytes,
    normalize_model_for_compare,
    prepare_model_for_import,
    validate_local_model,
    write_model,
)
from fabric_tools.dataflow_gen1.ops import (
    OpResult,
    delete_dataflow,
    deploy_dataflow,
    download_dataflow,
    run_delete_batch,
    run_deploy_batch,
    run_download_batch,
)

__all__ = [
    "CompareResult",
    "DefinitionError",
    "OpResult",
    "compare_dataflow",
    "delete_dataflow",
    "deploy_dataflow",
    "display_name_from_model",
    "download_dataflow",
    "load_model",
    "model_to_bytes",
    "normalize_model_for_compare",
    "prepare_model_for_import",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "validate_local_model",
    "write_model",
]
