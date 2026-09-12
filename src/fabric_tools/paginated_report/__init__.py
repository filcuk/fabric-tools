"""Paginated report (Power BI RDL) sync operations."""

# Submodules are imported by callers so package import stays light.

__all__ = [
    "CompareResult",
    "DefinitionError",
    "OpResult",
    "compare_paginated_report",
    "delete_paginated_report",
    "deploy_paginated_report",
    "display_name_from_path",
    "download_paginated_report",
    "load_rdl",
    "normalize_rdl_for_compare",
    "rdl_to_diff_text",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "validate_local_rdl",
    "write_rdl",
]
