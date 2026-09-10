"""Dataflow Gen2 (Fabric) sync operations."""

# Submodules are imported by callers so package import stays light.

__all__ = [
    "CompareResult",
    "DefinitionError",
    "OpResult",
    "compare_dataflow",
    "create_dataflow",
    "definition_has_platform",
    "definition_to_diff_text",
    "delete_dataflow",
    "deploy_dataflow",
    "detect_dataflow_path",
    "display_name_from_metadata",
    "display_name_from_path",
    "download_dataflow",
    "folder_to_diff_text",
    "get_dataflow_definition",
    "load_query_metadata",
    "pack_definition",
    "part_payloads",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "unpack_definition",
    "update_dataflow_definition",
    "validate_local_dataflow",
    "validate_query_metadata_dict",
]
