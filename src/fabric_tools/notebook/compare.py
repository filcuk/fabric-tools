"""Compare remote Fabric notebooks to local files or other remotes."""

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
from fabric_tools.confirm import item_display_name, resolve_workspace_name
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
from fabric_tools.status import BatchProgress, status_detail


@dataclass
class CompareResult:
    ok: bool
    identical: bool
    header: str
    diff_text: str = ""
    error: str | None = None
    messages: list[str] = field(default_factory=list)
    remote_name: str = "-"
    local_name: str = "-"
    target_ref: str = "-"


def compare_notebook(
    client: FabricClient,
    item: WorkItem,
    *,
    ignore_outputs: bool = False,
) -> CompareResult:
    """Diff target notebook against a local file or a Fabric origin."""
    if item.target is None or item.target.item_id is None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare requires workspace:artifact target",
        )
    if item.file is None and item.origin is None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare requires a local --file or --origin",
            target_ref=item.target.label(),
        )
    if item.file is not None and item.origin is not None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare cannot use both --file and --origin",
            target_ref=item.target.label(),
        )

    if item.origin is not None:
        return _compare_origin_to_target(client, item, ignore_outputs=ignore_outputs)
    return _compare_file_to_target(client, item, ignore_outputs=ignore_outputs)


def _compare_file_to_target(
    client: FabricClient,
    item: WorkItem,
    *,
    ignore_outputs: bool,
) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None
    target = item.target
    local_path = item.file
    local_name = local_path.name
    target_ref = target.label()
    try:
        fmt = validate_local_notebook(local_path)
    except DefinitionError as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=str(local_path),
            error=str(exc),
            local_name=local_name,
            target_ref=target_ref,
        )

    remote_name = item_display_name(client, target)
    workspace_label = resolve_workspace_name(client, target.workspace_id)
    header = f"remote {remote_name} in {workspace_label}  vs  local `{local_path}`"

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
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
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
                remote_name=remote_name,
                local_name=local_name,
                target_ref=target_ref,
            )

        if fmt is NotebookFormat.IPYNB:
            return _diff_ipynb(
                header,
                left_path=remote_path,
                right_path=local_path,
                left_label=f"remote:{remote_path.name}",
                right_label=f"local:{local_path}",
                ignore_outputs=ignore_outputs,
                remote_name=remote_name,
                local_name=local_name,
                target_ref=target_ref,
            )
        return _diff_fabric_git(
            header,
            remote_dir=remote_path,
            local_dir=local_path,
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )


def _compare_origin_to_target(
    client: FabricClient,
    item: WorkItem,
    *,
    ignore_outputs: bool,
) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.origin is not None and item.origin.item_id is not None
    target = item.target
    origin = item.origin
    remote_name = item_display_name(client, target)
    local_name = item_display_name(client, origin)
    target_ref = target.label()

    origin_ws = resolve_workspace_name(client, origin.workspace_id)
    target_ws = resolve_workspace_name(client, target.workspace_id)
    header = (
        f"origin {local_name} in {origin_ws}  vs  target {remote_name} in {target_ws}"
    )

    try:
        origin_definition = get_notebook_definition(
            client,
            origin.workspace_id,
            origin.item_id,
            format=NotebookFormat.IPYNB,
        )
        target_definition = get_notebook_definition(
            client,
            target.workspace_id,
            target.item_id,
            format=NotebookFormat.IPYNB,
        )
    except FabricApiError as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

    with tempfile.TemporaryDirectory(prefix="fabric-tools-compare-") as tmp:
        tmp_root = Path(tmp)
        origin_path = tmp_root / "origin.ipynb"
        target_path = tmp_root / "target.ipynb"
        try:
            unpack_definition(
                origin_definition, origin_path, format_hint=NotebookFormat.IPYNB
            )
            unpack_definition(
                target_definition, target_path, format_hint=NotebookFormat.IPYNB
            )
        except DefinitionError as exc:
            return CompareResult(
                ok=False,
                identical=False,
                header=header,
                error=f"failed to unpack remote definition: {exc}",
                remote_name=remote_name,
                local_name=local_name,
                target_ref=target_ref,
            )
        return _diff_ipynb(
            header,
            left_path=target_path,
            right_path=origin_path,
            left_label=f"target:{target.label()}",
            right_label=f"origin:{origin.label()}",
            ignore_outputs=ignore_outputs,
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )


def run_compare_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    ignore_outputs: bool = False,
) -> list[CompareResult]:
    progress = BatchProgress(total=len(items))
    results: list[CompareResult] = []
    for item in items:
        item_id = item.target.item_id if item.target is not None else None
        progress.advance(status_detail("Comparing", "notebook", item_id))
        results.append(compare_notebook(client, item, ignore_outputs=ignore_outputs))
    return results


def _diff_ipynb(
    header: str,
    *,
    left_path: Path,
    right_path: Path,
    left_label: str,
    right_label: str,
    ignore_outputs: bool,
    remote_name: str = "-",
    local_name: str = "-",
    target_ref: str = "-",
) -> CompareResult:
    set_notebook_diff_targets(
        sources=True,
        outputs=not ignore_outputs,
        attachments=False,
        metadata=False,
        identifier=False,
        details=False,
    )
    nb_left = _load_notebook_for_diff(left_path)
    nb_right = _load_notebook_for_diff(right_path)
    diff = diff_notebooks(nb_left, nb_right)
    if not diff:
        return CompareResult(
            ok=True,
            identical=True,
            header=header,
            diff_text="",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

    buffer = StringIO()
    config = PrettyPrintConfig(out=buffer)
    pretty_print_notebook_diff(
        left_label,
        right_label,
        nb_left,
        diff,
        config,
    )
    return CompareResult(
        ok=True,
        identical=False,
        header=header,
        diff_text=buffer.getvalue(),
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
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
    remote_name: str = "-",
    local_name: str = "-",
    target_ref: str = "-",
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
        remote_lines = remote_file.read_text(encoding="utf-8-sig").splitlines(
            keepends=True
        )
        local_lines = local_file.read_text(encoding="utf-8-sig").splitlines(
            keepends=True
        )
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
        return CompareResult(
            ok=True,
            identical=True,
            header=header,
            diff_text="",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )
    return CompareResult(
        ok=True,
        identical=False,
        header=header,
        diff_text="\n".join(chunks),
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )
