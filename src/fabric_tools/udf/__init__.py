"""User Data Function sync operations."""

# Submodules are imported by callers (e.g. ``fabric_tools.udf.ops``).

__all__ = [
    "CompareResult",
    "DefinitionError",
    "OpResult",
    "UdfAuthError",
    "check_udf_user_auth",
    "compare_udf",
    "create_udf",
    "definition_has_platform",
    "definition_to_diff_text",
    "delete_udf",
    "deploy_udf",
    "detect_udf_folder",
    "display_name_from_path",
    "download_udf",
    "folder_to_diff_text",
    "get_udf_definition",
    "merge_remote_connections",
    "pack_definition",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "strip_connected_data_sources",
    "unpack_definition",
    "update_udf_definition",
    "validate_local_udf",
]
