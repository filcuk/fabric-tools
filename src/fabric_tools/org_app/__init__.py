"""Microsoft Fabric Org App sync operations."""

# Submodules are imported by callers so package import stays light.

__all__ = [
    "CompareResult",
    "DefinitionError",
    "OpResult",
    "compare_org_app",
    "create_org_app",
    "definition_has_platform",
    "definition_to_diff_text",
    "delete_org_app",
    "deploy_org_app",
    "detect_org_app_path",
    "display_name_from_path",
    "download_org_app",
    "folder_to_diff_text",
    "get_org_app_definition",
    "load_org_app_definition",
    "pack_definition",
    "part_payloads",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "unpack_definition",
    "update_org_app_definition",
    "validate_definition_dict",
    "validate_local_org_app",
]
