"""Compare remote report definitions to local folders or other remotes."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from fabric_tools import status as status_mod
from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.confirm import item_display_name, resolve_workspace_name
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.report.definition import (
    DefinitionError,
    align_local_bind_for_diff,
    definition_to_diff_text,
    folder_payloads,
    is_pbix_path,
    packable_local_model,
    part_payloads,
    payloads_to_diff_text,
    validate_local_report,
)
from fabric_tools.report.ops import (
    _report_definition_cache_key,
    get_cached_report_definition,
    get_report_definition,
    joined_model_aside_text,
    preflight_bound_model_id,
    resolve_bound_model_id,
)
from fabric_tools.semantic_model.compare import compare_semantic_model
from fabric_tools.status import BatchProgress, clear_aside, status_detail, warn_aside


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


def compare_report(
    client: FabricClient,
    item: WorkItem,
    *,
    independent: bool = False,
    silent: bool = False,
    powerbi_client: Any | None = None,
    progress: BatchProgress | None = None,
    definition_cache: dict[str, dict[str, Any]] | None = None,
) -> list[CompareResult]:
    """Diff target report against a local folder or another remote.

    When not ``independent``, also compares a packable local (or origin-bound)
    semantic model using the same bind resolution as report download.
    """
    if item.target is None or item.target.item_id is None:
        return [
            CompareResult(
                ok=False,
                identical=False,
                header="compare",
                error="compare requires workspace:artifact target",
            )
        ]
    if item.file is None and item.origin is None:
        return [
            CompareResult(
                ok=False,
                identical=False,
                header="compare",
                error="compare requires a local path or remote --origin",
                target_ref=item.target.label(),
            )
        ]
    if item.file is not None and item.origin is not None:
        return [
            CompareResult(
                ok=False,
                identical=False,
                header="compare",
                error="compare cannot mix a local path and a remote --origin",
                target_ref=item.target.label(),
            )
        ]
    if item.file is not None and is_pbix_path(item.file):
        return [
            CompareResult(
                ok=False,
                identical=False,
                header=str(item.file),
                error="compare does not support .pbix (use a *.Report folder or remote --origin)",
                local_name=item.file.name,
                target_ref=item.target.label(),
            )
        ]

    cache = definition_cache if definition_cache is not None else {}
    name = item_display_name(client, item.target)
    # Check bind while spinner says ``checking``; only then show compare status.
    if progress is not None and not independent:
        status_mod.update(status_detail("report", "checking", name))

    will_join_model, join_warn_detail = _compare_join_preflight(
        client,
        item,
        independent=independent,
        powerbi_client=powerbi_client,
        definition_cache=cache,
    )
    if will_join_model:
        if progress is not None:
            progress.plan_extra(1)
        if join_warn_detail and not silent:
            warn_aside(joined_model_aside_text(detail=join_warn_detail))

    if progress is not None:
        progress.advance(status_detail("report", "comparing", name))

    if item.origin is not None:
        origin_def: dict[str, Any] | None = None
        target_def: dict[str, Any] | None = None
        if item.origin.item_id and item.target.item_id:
            try:
                origin_def = get_cached_report_definition(
                    client,
                    item.origin.workspace_id,
                    item.origin.item_id,
                    cache,
                )
                target_def = get_cached_report_definition(
                    client,
                    item.target.workspace_id,
                    item.target.item_id,
                    cache,
                )
            except (FabricApiError, DefinitionError):
                pass
        report_result, origin_def, target_def = _compare_origin_to_target(
            client,
            item,
            origin_definition=origin_def,
            target_definition=target_def,
        )
        results = [report_result]
        if not independent and report_result.ok and report_result.error is None:
            model_results = _joined_origin_model_results(
                client,
                item,
                report_result=report_result,
                origin_definition=origin_def,
                target_definition=target_def,
                powerbi_client=powerbi_client,
                progress=progress,
                silent=silent,
                planned_model_step=will_join_model,
            )
            results.extend(model_results)
        elif will_join_model and progress is not None:
            progress.skip_planned()
        return results

    remote_def: dict[str, Any] | None = None
    if item.target.item_id:
        remote_def = cache.get(
            _report_definition_cache_key(item.target.workspace_id, item.target.item_id)
        )
    report_result, remote_definition = _compare_file_to_target(
        client,
        item,
        remote_definition=remote_def,
    )
    results = [report_result]
    if (
        not independent
        and item.file is not None
        and report_result.ok
        and report_result.error is None
    ):
        model_results = _joined_file_model_results(
            client,
            item,
            report_result=report_result,
            remote_definition=remote_definition,
            powerbi_client=powerbi_client,
            progress=progress,
            silent=silent,
            planned_model_step=will_join_model,
        )
        results.extend(model_results)
    elif will_join_model and progress is not None:
        progress.skip_planned()
    return results


def run_compare_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    independent: bool = False,
    silent: bool = False,
    powerbi_client: Any | None = None,
) -> list[CompareResult]:
    from fabric_tools.powerbi_client import PowerBiClient

    definition_cache: dict[str, dict[str, Any]] = {}
    progress = BatchProgress(total=_estimate_compare_steps(items))
    owns_pbi = powerbi_client is None and not independent
    pbi = powerbi_client
    if owns_pbi:
        pbi = PowerBiClient()
        pbi.ensure_authenticated()
    results: list[CompareResult] = []
    try:
        for item in items:
            results.extend(
                compare_report(
                    client,
                    item,
                    independent=independent,
                    silent=silent,
                    powerbi_client=pbi,
                    progress=progress,
                    definition_cache=definition_cache,
                )
            )
    finally:
        if owns_pbi and pbi is not None:
            pbi.close()
    return results


def _estimate_compare_steps(items: list[WorkItem]) -> int:
    """Count report-only compare steps (no network)."""
    total = 0
    for item in items:
        if item.target is None or item.target.item_id is None:
            continue
        if item.file is None and item.origin is None:
            continue
        if item.file is not None and item.origin is not None:
            continue
        if item.file is not None and is_pbix_path(item.file):
            continue
        total += 1
    return total


def _compare_join_preflight(
    client: FabricClient,
    item: WorkItem,
    *,
    independent: bool,
    powerbi_client: Any | None,
    definition_cache: dict[str, dict[str, Any]],
) -> tuple[bool, str | None]:
    """Return whether a model compare step is planned and optional warn detail text."""
    if independent or item.target is None or item.target.item_id is None:
        return False, None

    if item.file is not None:
        if is_pbix_path(item.file) or packable_local_model(item.file) is None:
            return False, None
        model_id = preflight_bound_model_id(
            client,
            item.target.workspace_id,
            item.target.item_id,
            independent=False,
            powerbi_client=powerbi_client,
            definition_cache=definition_cache,
        )
        if not model_id:
            return False, None
        model_name = item_display_name(
            client, Target(item.target.workspace_id, model_id)
        )
        return True, (
            f"Also comparing connected semantic model '{model_name}' "
            f"({item.target.workspace_id}:{model_id})"
        )

    if item.origin is None or item.origin.item_id is None:
        return False, None

    try:
        origin_def = get_cached_report_definition(
            client,
            item.origin.workspace_id,
            item.origin.item_id,
            definition_cache,
        )
        target_def = get_cached_report_definition(
            client,
            item.target.workspace_id,
            item.target.item_id,
            definition_cache,
        )
    except (FabricApiError, DefinitionError):
        return False, None

    origin_model_id = resolve_bound_model_id(
        client,
        item.origin.workspace_id,
        item.origin.item_id,
        definition=origin_def,
        powerbi_client=powerbi_client,
    )
    target_model_id = resolve_bound_model_id(
        client,
        item.target.workspace_id,
        item.target.item_id,
        definition=target_def,
        powerbi_client=powerbi_client,
    )
    if not origin_model_id or not target_model_id:
        return False, None
    model_name = item_display_name(
        client, Target(item.target.workspace_id, target_model_id)
    )
    return True, (
        f"Also comparing connected semantic model '{model_name}' "
        f"({item.target.workspace_id}:{target_model_id})"
    )


def _compare_file_to_target(
    client: FabricClient,
    item: WorkItem,
    *,
    remote_definition: dict[str, Any] | None = None,
) -> tuple[CompareResult, dict[str, Any] | None]:
    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None
    target = item.target
    local_path = item.file
    local_name = local_path.name
    target_ref = target.label()

    try:
        validate_local_report(local_path)
        local_payloads = folder_payloads(local_path)
    except DefinitionError as exc:
        return (
            CompareResult(
                ok=False,
                identical=False,
                header=str(local_path),
                error=str(exc),
                local_name=local_name,
                target_ref=target_ref,
            ),
            None,
        )

    remote_name = item_display_name(client, target)
    workspace_label = resolve_workspace_name(client, target.workspace_id)
    header = f"remote {remote_name} in {workspace_label}  vs  local `{local_path}`"

    try:
        if remote_definition is None:
            remote_definition = get_report_definition(
                client, target.workspace_id, target.item_id
            )
        remote_payloads = part_payloads(remote_definition)
    except (FabricApiError, DefinitionError) as exc:
        return (
            CompareResult(
                ok=False,
                identical=False,
                header=header,
                error=f"failed to fetch remote definition: {exc}",
                remote_name=remote_name,
                local_name=local_name,
                target_ref=target_ref,
            ),
            None,
        )

    remote_text = payloads_to_diff_text(remote_payloads)
    local_text = payloads_to_diff_text(
        align_local_bind_for_diff(local_payloads, remote_payloads)
    )
    return (
        _diff_texts(
            header,
            left_text=remote_text,
            right_text=local_text,
            left_label=f"remote:{target.label()}",
            right_label=f"local:{local_path}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        ),
        remote_definition,
    )


def _compare_origin_to_target(
    client: FabricClient,
    item: WorkItem,
    *,
    origin_definition: dict[str, Any] | None = None,
    target_definition: dict[str, Any] | None = None,
) -> tuple[CompareResult, dict[str, Any] | None, dict[str, Any] | None]:
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
        if origin_definition is None:
            origin_definition = get_report_definition(
                client, origin.workspace_id, origin.item_id
            )
        if target_definition is None:
            target_definition = get_report_definition(
                client, target.workspace_id, target.item_id
            )
        origin_text = definition_to_diff_text(origin_definition)
        target_text = definition_to_diff_text(target_definition)
    except (FabricApiError, DefinitionError) as exc:
        return (
            CompareResult(
                ok=False,
                identical=False,
                header=header,
                error=f"failed to fetch remote definition: {exc}",
                remote_name=remote_name,
                local_name=local_name,
                target_ref=target_ref,
            ),
            None,
            None,
        )

    return (
        _diff_texts(
            header,
            left_text=target_text,
            right_text=origin_text,
            left_label=f"target:{target.label()}",
            right_label=f"origin:{origin.label()}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        ),
        origin_definition,
        target_definition,
    )


def _joined_file_model_results(
    client: FabricClient,
    item: WorkItem,
    *,
    report_result: CompareResult,
    remote_definition: dict[str, Any] | None,
    powerbi_client: Any | None,
    progress: BatchProgress | None,
    silent: bool,
    planned_model_step: bool = False,
) -> list[CompareResult]:
    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None

    model_path = packable_local_model(item.file)
    if model_path is None:
        if not silent:
            clear_aside()
        return []

    model_id = resolve_bound_model_id(
        client,
        item.target.workspace_id,
        item.target.item_id,
        definition=remote_definition,
        powerbi_client=powerbi_client,
    )
    if not model_id:
        report_result.messages.append(
            f"local packable model present at {model_path}; "
            "semantic model not compared "
            "(thin/live-connect or unbound — use semantic-model compare if needed)"
        )
        if not silent:
            clear_aside()
        if progress is not None and planned_model_step:
            progress.skip_planned()
        return []

    if progress is not None:
        progress.advance(
            status_detail(
                "semantic-model",
                "comparing",
                item_display_name(client, Target(item.target.workspace_id, model_id)),
            )
        )
    model_result = compare_semantic_model(
        client,
        WorkItem(Target(item.target.workspace_id, model_id), model_path),
    )
    return [
        CompareResult(
            ok=model_result.ok,
            identical=model_result.identical,
            header=model_result.header,
            diff_text=model_result.diff_text,
            error=model_result.error,
            messages=list(model_result.messages),
            remote_name=model_result.remote_name,
            local_name=model_result.local_name,
            target_ref=model_result.target_ref,
        )
    ]


def _joined_origin_model_results(
    client: FabricClient,
    item: WorkItem,
    *,
    report_result: CompareResult,
    origin_definition: dict[str, Any] | None,
    target_definition: dict[str, Any] | None,
    powerbi_client: Any | None,
    progress: BatchProgress | None,
    silent: bool,
    planned_model_step: bool = False,
) -> list[CompareResult]:
    assert item.target is not None and item.target.item_id is not None
    assert item.origin is not None and item.origin.item_id is not None

    origin_model_id = resolve_bound_model_id(
        client,
        item.origin.workspace_id,
        item.origin.item_id,
        definition=origin_definition,
        powerbi_client=powerbi_client,
    )
    target_model_id = resolve_bound_model_id(
        client,
        item.target.workspace_id,
        item.target.item_id,
        definition=target_definition,
        powerbi_client=powerbi_client,
    )
    if not origin_model_id or not target_model_id:
        if origin_model_id or target_model_id:
            report_result.messages.append(
                "joined semantic model not compared "
                "(one side is thin/live-connect or unbound — "
                "use semantic-model compare if needed)"
            )
        if not silent:
            clear_aside()
        if progress is not None and planned_model_step:
            progress.skip_planned()
        return []

    model_name = item_display_name(
        client, Target(item.target.workspace_id, target_model_id)
    )
    if progress is not None:
        progress.advance(status_detail("semantic-model", "comparing", model_name))
    model_result = compare_semantic_model(
        client,
        WorkItem(
            Target(item.target.workspace_id, target_model_id),
            None,
            origin=Target(item.origin.workspace_id, origin_model_id),
        ),
    )
    return [
        CompareResult(
            ok=model_result.ok,
            identical=model_result.identical,
            header=model_result.header,
            diff_text=model_result.diff_text,
            error=model_result.error,
            messages=list(model_result.messages),
            remote_name=model_result.remote_name,
            local_name=model_result.local_name,
            target_ref=model_result.target_ref,
        )
    ]


def _diff_texts(
    header: str,
    *,
    left_text: str,
    right_text: str,
    left_label: str,
    right_label: str,
    remote_name: str = "-",
    local_name: str = "-",
    target_ref: str = "-",
) -> CompareResult:
    if left_text == right_text:
        return CompareResult(
            ok=True,
            identical=True,
            header=header,
            diff_text="",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

    diff = list(
        difflib.unified_diff(
            left_text.splitlines(keepends=True),
            right_text.splitlines(keepends=True),
            fromfile=left_label,
            tofile=right_label,
        )
    )
    return CompareResult(
        ok=True,
        identical=False,
        header=header,
        diff_text="".join(diff),
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )
