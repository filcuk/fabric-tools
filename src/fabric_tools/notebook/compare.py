"""Compare remote Fabric notebooks to local files."""

from __future__ import annotations

import difflib
import json
import tempfile
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

import nbformat
from nbdime.diffing.notebooks import diff_notebooks, set_notebook_diff_targets
from nbdime.prettyprint import PrettyPrintConfig, pretty_print_notebook_diff

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.confirm import resolve_item_name, resolve_workspace_name
from fabric_tools.notebook.definition import (
    FABRIC_GIT_CONTENT_NAMES,
    PLATFORM_PART_PATH,
    DefinitionError,
    NotebookFormat,
    read_ipynb,
    unpack_definition,
    validate_local_notebook,
)
from fabric_tools.notebook.ops import get_notebook_definition
from fabric_tools.parsing import WorkItem


@dataclass
class CompareResult:
    ok: bool
    identical: bool
    header: str
    diff_text: str = ""
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def compare_notebook(
    client: FabricClient,
    item: WorkItem,
    *,
    ignore_outputs: bool = False,
) -> CompareResult:
    """Fetch remote definition to a temp path and diff against the local file."""
    if item.target is None or item.target.item_id is None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare requires workspace:artifact target",
        )
    if item.file is None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare requires a local --file path",
        )

    target = item.target
    local_path = item.file
    try:
        fmt = validate_local_notebook(local_path)
    except DefinitionError as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=str(local_path),
            error=str(exc),
        )

    remote_label = resolve_item_name(client, target)
    workspace_label = resolve_workspace_name(client, target.workspace_id)
    header = f"remote {remote_label} in {workspace_label}  vs  local `{local_path}`"

    try:
        definition = get_notebook_definition(
            client,
            target.workspace_id,
            target.item_id,
            format=fmt,
        )
    except FabricApiError as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
        )

    with tempfile.TemporaryDirectory(prefix="fabric-tools-compare-") as tmp:
        tmp_root = Path(tmp)
        if fmt is NotebookFormat.IPYNB:
            remote_path = tmp_root / "remote.ipynb"
        else:
            remote_path = tmp_root / "remote.Notebook"
        try:
            unpack_definition(definition, remote_path, format_hint=fmt)
        except DefinitionError as exc:
            return CompareResult(
                ok=False,
                identical=False,
                header=header,
                error=f"failed to unpack remote definition: {exc}",
            )

        if fmt is NotebookFormat.IPYNB:
            return _diff_ipynb(
                header,
                remote_path=remote_path,
                local_path=local_path,
                ignore_outputs=ignore_outputs,
            )
        return _diff_fabric_git(
            header,
            remote_dir=remote_path,
            local_dir=local_path,
        )


def run_compare_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    ignore_outputs: bool = False,
) -> list[CompareResult]:
    return [
        compare_notebook(client, item, ignore_outputs=ignore_outputs) for item in items
    ]


def _diff_ipynb(
    header: str,
    *,
    remote_path: Path,
    local_path: Path,
    ignore_outputs: bool,
) -> CompareResult:
    set_notebook_diff_targets(
        sources=True,
        outputs=not ignore_outputs,
        attachments=False,
        metadata=False,
        identifier=False,
        details=False,
    )
    nb_remote = _load_notebook_for_diff(remote_path)
    nb_local = _load_notebook_for_diff(local_path)
    diff = diff_notebooks(nb_remote, nb_local)
    if not diff:
        return CompareResult(ok=True, identical=True, header=header, diff_text="")

    buffer = StringIO()
    config = PrettyPrintConfig(out=buffer)
    pretty_print_notebook_diff(
        f"remote:{remote_path.name}",
        f"local:{local_path}",
        nb_remote,
        diff,
        config,
    )
    return CompareResult(
        ok=True,
        identical=False,
        header=header,
        diff_text=buffer.getvalue(),
    )


def _load_notebook_for_diff(path: Path) -> nbformat.NotebookNode:
    # read_ipynb normalises (adds missing cell ids); reads() builds a proper
    # NotebookNode (e.g. joins source lines) without MissingIDFieldWarning.
    notebook = nbformat.reads(json.dumps(read_ipynb(path)), as_version=4)
    # Drop cell ids: Fabric vs local exports often differ only by generated ids.
    for cell in notebook.get("cells", []):
        if isinstance(cell, dict) or hasattr(cell, "pop"):
            cell.pop("id", None)
    return notebook


def _diff_fabric_git(
    header: str,
    *,
    remote_dir: Path,
    local_dir: Path,
) -> CompareResult:
    names: list[str] = []
    for name in FABRIC_GIT_CONTENT_NAMES:
        if (remote_dir / name).is_file() or (local_dir / name).is_file():
            names.append(name)
    if (remote_dir / PLATFORM_PART_PATH).is_file() or (
        local_dir / PLATFORM_PART_PATH
    ).is_file():
        names.append(PLATFORM_PART_PATH)

    # Deduplicate while preserving order.
    ordered: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    chunks: list[str] = []
    any_diff = False
    for name in ordered:
        remote_file = remote_dir / name
        local_file = local_dir / name
        if not remote_file.is_file() and not local_file.is_file():
            continue
        if not remote_file.is_file():
            chunks.append(f"--- remote/{name} (missing)\n+++ local/{name}\n")
            any_diff = True
            continue
        if not local_file.is_file():
            chunks.append(f"--- remote/{name}\n+++ local/{name} (missing)\n")
            any_diff = True
            continue
        remote_lines = remote_file.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        local_lines = local_file.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        diff = list(
            difflib.unified_diff(
                remote_lines,
                local_lines,
                fromfile=f"remote/{name}",
                tofile=f"local/{name}",
            )
        )
        if diff:
            any_diff = True
            chunks.append("".join(diff))

    if not any_diff:
        return CompareResult(ok=True, identical=True, header=header, diff_text="")
    return CompareResult(
        ok=True,
        identical=False,
        header=header,
        diff_text="\n".join(chunks),
    )
