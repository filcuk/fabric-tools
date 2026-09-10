"""Notebook sync operations."""

# Submodules are imported by callers (e.g. ``fabric_tools.notebook.ops``) so that
# ``import fabric_tools.notebook`` does not pull nbdime/nbformat eagerly.

__all__ = [
    "CellSelectionError",
    "CompareResult",
    "DefinitionError",
    "NotebookFormat",
    "OpResult",
    "compare_notebook",
    "create_notebook",
    "definition_has_platform",
    "delete_notebook",
    "deploy_notebook",
    "detect_format",
    "display_name_from_path",
    "download_notebook",
    "format_for_api",
    "get_notebook_definition",
    "merge_notebook_cells",
    "merge_remote_dependencies",
    "pack_definition",
    "parse_cell_indices",
    "run_compare_batch",
    "run_delete_batch",
    "run_deploy_batch",
    "run_download_batch",
    "strip_preserved_dependencies",
    "unpack_definition",
    "update_notebook_definition",
    "validate_local_notebook",
]
