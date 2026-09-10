"""User Data Function sync operations."""

# Submodules are imported by callers (e.g. ``fabric_tools.udf.ops``).

__all__ = [
    "DefinitionError",
    "OpResult",
    "UdfAuthError",
    "check_udf_user_auth",
    "create_udf",
    "definition_has_platform",
    "delete_udf",
    "deploy_udf",
    "detect_udf_folder",
    "display_name_from_path",
    "download_udf",
    "get_udf_definition",
    "merge_remote_connections",
    "pack_definition",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "strip_connected_data_sources",
    "unpack_definition",
    "update_udf_definition",
    "validate_local_udf",
]
