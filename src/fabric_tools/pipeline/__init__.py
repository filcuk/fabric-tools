"""DataPipeline (Fabric) sync operations."""

# Submodules are imported by callers so package import stays light.

__all__ = [
    "CompareResult",
    "DefinitionError",
    "OpResult",
    "compare_pipeline",
    "create_pipeline",
    "definition_has_platform",
    "definition_to_diff_text",
    "definition_without_schedules",
    "delete_pipeline",
    "deploy_pipeline",
    "detect_pipeline_path",
    "display_name_from_path",
    "download_pipeline",
    "folder_to_diff_text",
    "get_pipeline_definition",
    "load_pipeline_content",
    "pack_definition",
    "part_payloads",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "unpack_definition",
    "update_pipeline_definition",
    "validate_local_pipeline",
    "validate_pipeline_content_dict",
]
