"""Notebook sync operations."""

from fabric_tools.notebook.compare import CompareResult, compare_notebook, run_compare_batch
from fabric_tools.notebook.cells import (
    CellSelectionError,
    merge_notebook_cells,
    parse_cell_indices,
)
from fabric_tools.notebook.definition import (
    DefinitionError,
    NotebookFormat,
    definition_has_platform,
    detect_format,
    display_name_from_path,
    format_for_api,
    merge_remote_dependencies,
    pack_definition,
    strip_preserved_dependencies,
    unpack_definition,
    validate_local_notebook,
)
from fabric_tools.notebook.ops import (
    OpResult,
    create_notebook,
    delete_notebook,
    deploy_notebook,
    download_notebook,
    get_notebook_definition,
    run_delete_batch,
    run_deploy_batch,
    run_download_batch,
    update_notebook_definition,
)

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
