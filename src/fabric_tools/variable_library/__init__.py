"""Microsoft Fabric Variable Library sync operations."""

# Submodules are imported by callers so package import stays light.

__all__ = [
    "CompareResult",
    "DefinitionError",
    "OpResult",
    "compare_variable_library",
    "create_variable_library",
    "definition_has_platform",
    "definition_to_diff_text",
    "delete_variable_library",
    "deploy_variable_library",
    "detect_variable_library_path",
    "display_name_from_path",
    "download_variable_library",
    "folder_to_diff_text",
    "get_variable_library_definition",
    "pack_definition",
    "part_payloads",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "unpack_definition",
    "update_variable_library_definition",
    "validate_json_dict",
    "validate_local_variable_library",
]
