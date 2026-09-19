"""Selective cell replacement for notebook overwrite deploys."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fabric_tools.notebook.definition import (
    DefinitionError,
    NotebookFormat,
    detect_format,
)
from fabric_tools.parsing import CommandMode, ParseError, WorkItem


class CellSelectionError(ValueError):
    """Invalid ``--cells`` selection or merge failure."""


def parse_cell_indices(values: list[str] | None) -> list[int] | None:
    """Parse ``--cells`` / ``-c`` values into ordered unique 1-based indices.

    Accepts repeatable options and/or comma-separated lists (e.g. ``1,3,5``).
    Returns ``None`` when the flag is omitted.
    """
    if not values:
        return None
    indices: list[int] = []
    seen: set[int] = set()
    for raw in values:
        for piece in raw.split(","):
            text = piece.strip()
            if not text:
                continue
            try:
                index = int(text, 10)
            except ValueError as exc:
                raise CellSelectionError(
                    f"invalid --cells value '{text}': expected a positive integer"
                ) from exc
            if index < 1:
                raise CellSelectionError(
                    f"invalid --cells value '{text}': cell indices are 1-based"
                )
            if index not in seen:
                seen.add(index)
                indices.append(index)
    if not indices:
        raise CellSelectionError("--cells requires at least one cell index")
    return indices


def validate_cells_usage(
    mode: CommandMode,
    items: list[WorkItem],
    cell_indices: list[int] | None,
    *,
    dry_run: bool,
) -> None:
    """Enforce ``--cells`` constraints (single overwrite .ipynb deploy)."""
    if cell_indices is None:
        return
    if mode is not CommandMode.DEPLOY:
        raise ParseError("--cells is only valid with notebook deploy")
    if len(items) != 1:
        raise ParseError(
            "--cells requires exactly one notebook pair "
            "(one remote --target and one local --origin .ipynb; multi-target is not supported)"
        )
    item = items[0]
    if item.origin is not None:
        raise ParseError(
            "--cells requires a local --origin .ipynb; not valid with a remote --origin"
        )
    if item.file is None:
        raise ParseError("--cells requires a local --origin .ipynb")
    try:
        fmt = detect_format(item.file)
    except DefinitionError as exc:
        raise ParseError(str(exc)) from exc
    if fmt is not NotebookFormat.IPYNB:
        raise ParseError("--cells only supports .ipynb files (not Fabric Git folders)")
    if item.target is None:
        if dry_run:
            return
        raise ParseError("--cells requires an overwrite --target (workspace:artifact)")
    if item.target.is_create:
        raise ParseError(
            "--cells requires an overwrite target (workspace:artifact), not create"
        )


def validate_cell_indices(
    notebook: dict[str, Any],
    indices: list[int],
    *,
    side: str,
) -> None:
    """Fail if any 1-based index is missing from ``notebook['cells']``."""
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise CellSelectionError(f"{side} notebook is missing a cells list")
    count = len(cells)
    missing = [index for index in indices if index > count]
    if missing:
        missing_text = ", ".join(str(index) for index in missing)
        raise CellSelectionError(
            f"{side} notebook has {count} cell(s); missing index(es): {missing_text}"
        )


def merge_notebook_cells(
    remote: dict[str, Any],
    local: dict[str, Any],
    indices: list[int],
) -> dict[str, Any]:
    """Return a copy of *remote* with selected cells replaced from *local*.

    Indices are 1-based. Each selected cell is replaced wholesale (source,
    metadata, and outputs).
    """
    validate_cell_indices(local, indices, side="local")
    validate_cell_indices(remote, indices, side="remote")
    merged = deepcopy(remote)
    remote_cells = merged["cells"]
    local_cells = local["cells"]
    for index in indices:
        remote_cells[index - 1] = deepcopy(local_cells[index - 1])
    return merged


def format_cell_indices(indices: list[int]) -> str:
    """Human-readable comma-separated cell list."""
    return ", ".join(str(index) for index in indices)
