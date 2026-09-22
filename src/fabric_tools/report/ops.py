"""Report download / create / overwrite / delete (Fabric + optional Power BI PBIX)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.text import Text

from fabric_tools import status as status_mod
from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.colours import STYLE_ID
from fabric_tools.confirm import status_item_label, status_item_label_for_id
from fabric_tools.definition_parts import encode_part
from fabric_tools.parsing import WorkItem
from fabric_tools.report.definition import (
    PBIR_PART,
    DefinitionError,
    ReportFormat,
    definition_has_platform,
    detect_report_path,
    display_name_from_path,
    is_pbix_path,
    load_pbir,
    pack_definition,
    parse_dataset_reference,
    part_payloads,
    resolve_local_join,
    rewrite_pbir_to_by_connection,
    unpack_definition,
    validate_local_report,
)
from fabric_tools.semantic_model.definition import (
    definition_has_platform as sm_has_platform,
)
from fabric_tools.semantic_model.definition import (
    display_name_from_path as sm_display_name,
)
from fabric_tools.semantic_model.definition import (
    pack_definition as pack_sm_definition,
)
from fabric_tools.semantic_model.ops import (
    create_semantic_model,
    get_semantic_model_definition,
    update_semantic_model_definition,
)
from fabric_tools.semantic_model.ops import (
    unpack_definition as unpack_semantic_model_definition,
)
from fabric_tools.status import BatchProgress, clear_aside, status_detail, warn_aside

ITEM_TYPE = "Report"


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None
    semantic_model_id: str | None = None


def _report_definition_cache_key(workspace_id: str, report_id: str) -> str:
    return f"{workspace_id}:{report_id}"


def get_cached_report_definition(
    client: FabricClient,
    workspace_id: str,
    report_id: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    key = _report_definition_cache_key(workspace_id, report_id)
    if key not in cache:
        cache[key] = get_report_definition(client, workspace_id, report_id)
    return cache[key]


def preflight_bound_model_id(
    client: FabricClient,
    workspace_id: str,
    report_id: str,
    *,
    independent: bool,
    powerbi_client: Any | None,
    definition_cache: dict[str, dict[str, Any]],
) -> str | None:
    """Return bound semantic model id while the spinner still says ``checking``.

    Order: cached definition → Power BI ``datasetId`` → Fabric ``getDefinition``
    (cached for the later download/compare). Never updates the download/compare
    progress line — callers do that only after this returns.
    """
    if independent:
        return None
    key = _report_definition_cache_key(workspace_id, report_id)
    if key in definition_cache:
        return resolve_bound_model_id(
            client,
            workspace_id,
            report_id,
            definition=definition_cache[key],
            powerbi_client=powerbi_client,
        )

    early = resolve_bound_model_id(
        client,
        workspace_id,
        report_id,
        definition=None,
        powerbi_client=powerbi_client,
    )
    if early:
        return early

    try:
        definition = get_cached_report_definition(
            client, workspace_id, report_id, definition_cache
        )
    except (FabricApiError, DefinitionError):
        return None
    return resolve_bound_model_id(
        client,
        workspace_id,
        report_id,
        definition=definition,
        powerbi_client=powerbi_client,
    )


def download_report(
    client: FabricClient,
    item: WorkItem,
    *,
    independent: bool = False,
    silent: bool = False,
    powerbi_client: Any | None = None,
    progress: BatchProgress | None = None,
    definition_cache: dict[str, dict[str, Any]] | None = None,
) -> OpResult:
    """Download one remote report (folder or ``.pbix``); join model when packable."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --target path")

    target = item.target
    dest = item.file
    cache = definition_cache if definition_cache is not None else {}

    if is_pbix_path(dest):
        if progress is not None:
            progress.advance(
                status_detail(
                    "report",
                    "downloading",
                    status_item_label(client, target),
                )
            )
        return _download_pbix(
            item,
            independent=independent,
            powerbi_client=powerbi_client,
        )

    report_label = status_item_label(client, target)
    model_id: str | None = None
    planned_model_step = False

    # 1) Check bind while spinner still says ``checking`` (orchestrator / batch).
    # 2) Only then show download status — ``1 of 2`` + warning when joined.
    if not independent:
        if progress is not None:
            status_mod.update(status_detail("report", "checking", report_label))
        model_id = preflight_bound_model_id(
            client,
            target.workspace_id,
            target.item_id,
            independent=False,
            powerbi_client=powerbi_client,
            definition_cache=cache,
        )
        if model_id:
            planned_model_step = True
            if progress is not None:
                progress.plan_extra(1)
            if not silent:
                _warn_connected_model_download(client, target.workspace_id, model_id)

    if progress is not None:
        progress.advance(status_detail("report", "downloading", report_label))

    try:
        dest = detect_report_path(dest)
        definition = get_cached_report_definition(
            client, target.workspace_id, target.item_id, cache
        )
        written = unpack_definition(definition, dest)
    except (FabricApiError, DefinitionError, OSError) as exc:
        if planned_model_step and progress is not None:
            progress.skip_planned()
        return OpResult(
            False,
            f"download failed {target.label()} -> {dest}: {exc}",
            target.workspace_id,
            target.item_id,
        )

    messages = [f"downloaded report {target.label()} -> {written}"]

    if not independent:
        # Definition is authoritative once fetched (byPath → no model download).
        resolved_id = resolve_bound_model_id(
            client,
            target.workspace_id,
            target.item_id,
            definition=definition,
            powerbi_client=powerbi_client,
        )
        if resolved_id and not model_id:
            model_id = resolved_id
            planned_model_step = True
            if progress is not None:
                progress.plan_extra(1)
            if not silent:
                _warn_connected_model_download(client, target.workspace_id, model_id)
        elif resolved_id and model_id != resolved_id:
            model_id = resolved_id
            if not silent:
                _warn_connected_model_download(client, target.workspace_id, model_id)
        elif not resolved_id:
            if planned_model_step and progress is not None:
                progress.skip_planned()
            planned_model_step = False
            model_id = None
            if not silent:
                clear_aside()
            messages.append(
                "report downloaded; semantic model not included "
                "(thin/live-connect or unbound — use semantic-model download if needed)"
            )

        if model_id:
            if progress is not None:
                progress.advance(
                    status_detail(
                        "semantic-model",
                        "downloading",
                        status_item_label_for_id(client, target.workspace_id, model_id),
                    )
                )
            model_dest = dest.parent / f"{display_name_from_path(dest)}.SemanticModel"
            try:
                sm_def = get_semantic_model_definition(
                    client, target.workspace_id, model_id
                )
                sm_written = unpack_semantic_model_definition(sm_def, model_dest)
                messages.append(
                    f"downloaded joined semantic model {target.workspace_id}:{model_id} "
                    f"-> {sm_written}"
                )
            except (FabricApiError, OSError) as exc:
                messages.append(
                    f"report downloaded; joined semantic model not included "
                    f"({target.workspace_id}:{model_id}): {exc}"
                )
                model_id = None

    return OpResult(
        True,
        "; ".join(messages),
        target.workspace_id,
        target.item_id,
        semantic_model_id=model_id,
    )


def deploy_report(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    independent: bool = False,
    semantic_model_id: str | None = None,
    origin_definition_cache: dict[str, dict[str, Any]] | None = None,
    powerbi_client: Any | None = None,
    progress: BatchProgress | None = None,
) -> OpResult:
    """Create or overwrite one report from a local folder, ``.pbix``, or Fabric origin."""
    if item.target is None:
        return OpResult(False, "deploy requires a --target")
    if item.file is None and item.origin is None:
        return OpResult(False, "deploy requires a local path or remote --origin")
    if item.file is not None and item.origin is not None:
        return OpResult(False, "deploy cannot mix a local path and a remote --origin")

    target = item.target

    if item.file is not None and is_pbix_path(item.file):
        if progress is not None:
            progress.advance(
                status_detail(
                    "report",
                    "creating" if target.is_create else "deploying",
                    status_item_label(client, target, fallback=display_name),
                )
            )
        return _deploy_pbix(
            item,
            display_name=display_name,
            independent=independent,
            powerbi_client=powerbi_client,
        )

    if item.file is not None:
        try:
            join = resolve_local_join(item.file)
        except DefinitionError as exc:
            if progress is not None:
                progress.skip_planned()
            return OpResult(
                False,
                f"deploy source failed: {exc}",
                target.workspace_id,
                target.item_id,
            )
        if independent and join.model_path is not None:
            if progress is not None:
                progress.skip_planned()
            return OpResult(
                False,
                "report deploy --independent cannot join a packable sibling "
                "semantic model; omit --independent to deploy both, or remove the "
                "local model / use byConnection-only binding",
                target.workspace_id,
                target.item_id,
            )
        if (
            not independent
            and join.reference.kind == "byPath"
            and join.model_path is None
        ):
            if progress is not None:
                progress.skip_planned()
            return OpResult(
                False,
                "report byPath does not resolve to a packable semantic model",
                target.workspace_id,
                target.item_id,
            )
        if not independent and join.model_path is not None:
            return _deploy_joined_folder(
                client,
                item,
                join_model_path=join.model_path,
                display_name=display_name,
                semantic_model_id=semantic_model_id,
                progress=progress,
            )

    if progress is not None:
        progress.advance(
            status_detail(
                "report",
                "creating" if target.is_create else "deploying",
                status_item_label(client, target, fallback=display_name),
            )
        )
    return _deploy_report_only(
        client,
        item,
        display_name=display_name,
        origin_definition_cache=origin_definition_cache,
        bind_model_id=semantic_model_id,
        independent=independent,
    )


def delete_report(client: FabricClient, item: WorkItem) -> OpResult:
    """Soft-delete one remote report (bound semantic model is left intact)."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    try:
        client.request(
            "DELETE",
            f"/workspaces/{target.workspace_id}/reports/{target.item_id}",
        )
    except FabricApiError as exc:
        return OpResult(
            False,
            f"delete failed {target.label()}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"deleted report {target.label()} (semantic model left intact if any)",
        target.workspace_id,
        target.item_id,
    )


def get_report_definition(
    client: FabricClient,
    workspace_id: str,
    report_id: str,
    *,
    format: ReportFormat | None = None,
) -> dict[str, Any]:
    """POST getDefinition and return the definition object (parts/format)."""
    params = {"format": format.value} if format is not None else None
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/reports/{report_id}/getDefinition",
        params=params,
    )
    return _extract_definition(result)


def create_report(
    client: FabricClient,
    workspace_id: str,
    *,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """POST /items to create a Report with definition."""
    payload = {
        "displayName": display_name,
        "type": ITEM_TYPE,
        "definition": definition,
    }
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/items",
        json=payload,
    )
    if not isinstance(result, dict):
        raise FabricApiError("Create report returned an empty response")
    return result


def update_report_definition(
    client: FabricClient,
    workspace_id: str,
    report_id: str,
    *,
    definition: dict[str, Any],
    update_metadata: bool = False,
) -> Any:
    """POST updateDefinition for an existing report."""
    params = {"updateMetadata": "true"} if update_metadata else None
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/reports/{report_id}/updateDefinition",
        params=params,
        json={"definition": definition},
    )


def run_download_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    independent: bool = False,
    silent: bool = False,
    powerbi_client: Any | None = None,
) -> list[OpResult]:
    # Base total = report steps only (no network). Each item may ``plan_extra``
    # a model step after bind check so ``1 of 2`` is accurate immediately.
    from fabric_tools.powerbi_client import PowerBiClient

    definition_cache: dict[str, dict[str, Any]] = {}
    progress = BatchProgress(total=_estimate_download_steps(items))
    owns_pbi = powerbi_client is None and not independent
    pbi = powerbi_client
    if owns_pbi:
        pbi = PowerBiClient()
        pbi.ensure_authenticated()
    results: list[OpResult] = []
    try:
        for item in items:
            results.append(
                download_report(
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


def run_deploy_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
    independent: bool = False,
    semantic_model_ids: list[str | None] | None = None,
    powerbi_client: Any | None = None,
) -> list[OpResult]:
    progress = BatchProgress(
        total=_estimate_deploy_steps(items, independent=independent)
    )
    results: list[OpResult] = []
    origin_cache: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        name = None
        if display_names and index < len(display_names):
            name = display_names[index]
        sm_id = None
        if semantic_model_ids and index < len(semantic_model_ids):
            sm_id = semantic_model_ids[index]
        results.append(
            deploy_report(
                client,
                item,
                display_name=name,
                independent=independent,
                semantic_model_id=sm_id,
                origin_definition_cache=origin_cache,
                powerbi_client=powerbi_client,
                progress=progress,
            )
        )
    return results


def run_delete_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        progress.advance(
            status_detail(
                "report",
                "deleting",
                status_item_label(client, item.target),
            )
        )
        results.append(delete_report(client, item))
    return results


def _estimate_download_steps(items: list[WorkItem]) -> int:
    """Count report-only steps (no network). Model steps are planned per item."""
    total = 0
    for item in items:
        if item.target is None or item.target.item_id is None or item.file is None:
            continue
        total += 1
    return total


def _estimate_deploy_steps(items: list[WorkItem], *, independent: bool) -> int:
    total = 0
    for item in items:
        if item.target is None:
            continue
        if item.file is None and item.origin is None:
            continue
        if item.file is not None and item.origin is not None:
            continue
        total += 1
        if _plans_deploy_model_step(item, independent=independent):
            total += 1
    return total


def _plans_deploy_model_step(item: WorkItem, *, independent: bool) -> bool:
    if independent or item.file is None or is_pbix_path(item.file):
        return False
    try:
        join = resolve_local_join(item.file)
    except DefinitionError:
        return False
    return join.model_path is not None


def _deploy_report_only(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None,
    origin_definition_cache: dict[str, dict[str, Any]] | None,
    bind_model_id: str | None,
    independent: bool,
) -> OpResult:
    del independent  # report-only path; flag already gated join above
    target = item.target
    assert target is not None

    try:
        definition, source_label = _resolve_source_definition(
            client,
            item,
            origin_definition_cache=origin_definition_cache,
            bind_model_id=bind_model_id,
        )
    except (FabricApiError, DefinitionError) as exc:
        return OpResult(
            False,
            f"deploy source failed: {exc}",
            target.workspace_id,
            target.item_id,
        )

    if target.is_create:
        name = display_name
        if not name:
            if item.file is not None:
                name = display_name_from_path(item.file)
            else:
                assert item.origin is not None and item.origin.item_id is not None
                try:
                    meta = client.get_item(
                        item.origin.workspace_id, item.origin.item_id
                    )
                    name = str(meta.get("displayName") or meta.get("name") or "Report")
                except FabricApiError:
                    name = "Report"
        try:
            created = create_report(
                client,
                target.workspace_id,
                display_name=name,
                definition=definition,
            )
        except FabricApiError as exc:
            return OpResult(
                False,
                f"create failed in {target.workspace_id} from {source_label}: {exc}",
                target.workspace_id,
            )
        item_id = str(created.get("id") or "")
        return OpResult(
            True,
            f"created report {target.workspace_id}:{item_id} from {source_label} "
            f"(name='{name}')",
            target.workspace_id,
            item_id or None,
        )

    assert target.item_id is not None
    try:
        update_report_definition(
            client,
            target.workspace_id,
            target.item_id,
            definition=definition,
            update_metadata=definition_has_platform(definition),
        )
    except FabricApiError as exc:
        return OpResult(
            False,
            f"overwrite failed {target.label()} from {source_label}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"updated report {target.label()} from {source_label}",
        target.workspace_id,
        target.item_id,
    )


def _deploy_joined_folder(
    client: FabricClient,
    item: WorkItem,
    *,
    join_model_path: Path,
    display_name: str | None,
    semantic_model_id: str | None,
    progress: BatchProgress | None = None,
) -> OpResult:
    target = item.target
    assert target is not None and item.file is not None

    report_name = display_name or display_name_from_path(item.file)
    model_name = sm_display_name(join_model_path)
    action = "creating" if target.is_create else "deploying"

    try:
        model_definition = pack_sm_definition(join_model_path)
    except Exception as exc:  # noqa: BLE001
        if progress is not None:
            progress.skip_planned()
            progress.skip_planned()
        return OpResult(
            False,
            f"joined semantic model pack failed: {exc}",
            target.workspace_id,
            target.item_id,
        )

    model_id = semantic_model_id
    messages: list[str] = []
    progress_at_entry = progress.current if progress is not None else 0

    try:
        if target.is_create:
            if progress is not None:
                progress.advance(status_detail("semantic-model", action, model_name))
            created_model = create_semantic_model(
                client,
                target.workspace_id,
                display_name=model_name,
                definition=model_definition,
            )
            model_id = str(created_model.get("id") or "")
            messages.append(
                f"created semantic model {target.workspace_id}:{model_id} "
                f"(name='{model_name}')"
            )
        else:
            if not model_id:
                model_id = resolve_bound_model_id(
                    client,
                    target.workspace_id,
                    target.item_id or "",
                    definition=None,
                    powerbi_client=None,
                )
            if not model_id:
                if progress is not None:
                    progress.skip_planned()
                    progress.skip_planned()
                return OpResult(
                    False,
                    "joined overwrite requires the target report's bound semantic "
                    "model id (could not resolve datasetId); pass it via manifest "
                    "semanticModelId or deploy the model separately",
                    target.workspace_id,
                    target.item_id,
                )
            if progress is not None:
                progress.advance(
                    status_detail(
                        "semantic-model",
                        action,
                        status_item_label_for_id(client, target.workspace_id, model_id),
                    )
                )
            update_semantic_model_definition(
                client,
                target.workspace_id,
                model_id,
                definition=model_definition,
                update_metadata=sm_has_platform(model_definition),
            )
            messages.append(f"updated semantic model {target.workspace_id}:{model_id}")

        assert model_id
        pbir = rewrite_pbir_to_by_connection(load_pbir(item.file), model_id)
        report_definition = pack_definition(item.file, pbir_override=pbir)

        if progress is not None:
            progress.advance(
                status_detail(
                    "report",
                    action,
                    status_item_label(client, target, fallback=report_name),
                )
            )

        if target.is_create:
            created = create_report(
                client,
                target.workspace_id,
                display_name=report_name,
                definition=report_definition,
            )
            report_id = str(created.get("id") or "")
            messages.append(
                f"created report {target.workspace_id}:{report_id} "
                f"(name='{report_name}') bound to semantic model {model_id}"
            )
            return OpResult(
                True,
                "; ".join(messages),
                target.workspace_id,
                report_id or None,
                semantic_model_id=model_id,
            )

        assert target.item_id is not None
        update_report_definition(
            client,
            target.workspace_id,
            target.item_id,
            definition=report_definition,
            update_metadata=definition_has_platform(report_definition),
        )
        messages.append(
            f"updated report {target.label()} bound to semantic model {model_id}"
        )
        return OpResult(
            True,
            "; ".join(messages),
            target.workspace_id,
            target.item_id,
            semantic_model_id=model_id,
        )
    except (FabricApiError, DefinitionError) as exc:
        if progress is not None:
            advanced = progress.current - progress_at_entry
            for _ in range(max(0, 2 - advanced)):
                progress.skip_planned()
        return OpResult(
            False,
            f"joined deploy failed: {exc}",
            target.workspace_id,
            target.item_id,
            semantic_model_id=model_id,
        )


def _independent_opt_hint() -> Text:
    """Cyan ``--independent / -i`` hint (command-hint role; see DESIGN.md)."""
    text = Text()
    text.append("--independent", style=STYLE_ID)
    text.append(" / ")
    text.append("-i", style=STYLE_ID)
    return text


def joined_model_aside_text(
    *,
    provisional: str | None = None,
    detail: str | None = None,
) -> Text:
    """Warning body for joined report ops (download/compare).

    Pass *provisional* for the early notice, or *detail* (without trailing
    period) once a connected model id is known.
    """
    text = Text()
    if detail:
        text.append(detail)
        if not detail.endswith((".", "!", "?")):
            text.append(".")
        text.append(" ")
    elif provisional:
        text.append(provisional)
        if not provisional.endswith(" "):
            text.append(" ")
    text.append("Use ")
    text.append_text(_independent_opt_hint())
    text.append(" for report only.")
    return text


def _warn_connected_model_download(
    client: FabricClient,
    workspace_id: str,
    model_id: str,
) -> None:
    """Non-blocking notice under the download spinner (see ``status.warn_aside``)."""
    label = status_item_label_for_id(client, workspace_id, model_id)
    warn_aside(
        joined_model_aside_text(
            detail=(
                f"Also downloading connected semantic model '{label}' "
                f"({workspace_id}:{model_id})"
            )
        )
    )


def _download_pbix(
    item: WorkItem,
    *,
    independent: bool,
    powerbi_client: Any | None,
) -> OpResult:
    from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient

    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None
    target = item.target
    download_type = "LiveConnect" if independent else "IncludeModel"

    owns_client = powerbi_client is None
    pbi = powerbi_client or PowerBiClient()
    try:
        if owns_client:
            pbi.ensure_authenticated()
        try:
            payload = pbi.export_report(
                target.workspace_id,
                target.item_id,
                download_type=download_type,
            )
        except PowerBiApiError as exc:
            if not independent and download_type == "IncludeModel":
                try:
                    payload = pbi.export_report(
                        target.workspace_id,
                        target.item_id,
                        download_type="LiveConnect",
                    )
                except PowerBiApiError as live_exc:
                    return OpResult(
                        False,
                        f"PBIX download failed {target.label()}: IncludeModel "
                        f"({exc}); LiveConnect ({live_exc})",
                        target.workspace_id,
                        target.item_id,
                    )
                item.file.parent.mkdir(parents=True, exist_ok=True)
                item.file.write_bytes(payload)
                return OpResult(
                    True,
                    f"downloaded report {target.label()} -> {item.file} "
                    f"(LiveConnect only; model not included — thin/live-connect)",
                    target.workspace_id,
                    target.item_id,
                )
            return OpResult(
                False,
                f"PBIX download failed {target.label()}: {exc}",
                target.workspace_id,
                target.item_id,
            )
        item.file.parent.mkdir(parents=True, exist_ok=True)
        item.file.write_bytes(payload)
        note = (
            " (report only / LiveConnect)"
            if independent
            else " (IncludeModel — report + semantic model)"
        )
        return OpResult(
            True,
            f"downloaded {target.label()} -> {item.file}{note}",
            target.workspace_id,
            target.item_id,
        )
    finally:
        if owns_client:
            pbi.close()


def _deploy_pbix(
    item: WorkItem,
    *,
    display_name: str | None,
    independent: bool,
    powerbi_client: Any | None,
) -> OpResult:
    from fabric_tools.powerbi_client import (
        PowerBiApiError,
        PowerBiClient,
        report_and_dataset_ids_from_import,
    )

    assert item.target is not None and item.file is not None
    target = item.target

    if independent:
        return OpResult(
            False,
            "report deploy --independent cannot publish a thick .pbix "
            "(Import always replaces the embedded model with the report). "
            "Omit --independent for full publish, use a *.Report folder, "
            "or use semantic-model deploy --independent for skipReport",
            target.workspace_id,
            target.item_id,
        )

    if not item.file.is_file():
        return OpResult(
            False,
            f"PBIX file not found: {item.file}",
            target.workspace_id,
            target.item_id,
        )

    name = display_name or display_name_from_path(item.file)
    dataset_display_name = name if name.lower().endswith(".pbix") else f"{name}.pbix"
    name_conflict = "CreateOrOverwrite" if not target.is_create else "Abort"

    owns_client = powerbi_client is None
    pbi = powerbi_client or PowerBiClient()
    try:
        if owns_client:
            pbi.ensure_authenticated()
        pbix_bytes = item.file.read_bytes()
        imported = pbi.import_pbix(
            target.workspace_id,
            pbix_bytes,
            dataset_display_name=dataset_display_name,
            name_conflict=name_conflict,
            skip_report=False,
        )
        report_id, dataset_id = report_and_dataset_ids_from_import(imported)
        if target.item_id and report_id and report_id != target.item_id:
            return OpResult(
                False,
                f"PBIX import succeeded but report id {report_id} does not match "
                f"target {target.item_id} (name-based overwrite safety check failed)",
                target.workspace_id,
                report_id,
                semantic_model_id=dataset_id,
            )
        action = "created" if target.is_create else "updated"
        return OpResult(
            True,
            f"{action} report {target.workspace_id}:{report_id or '?'} from "
            f"{item.file} (dataset={dataset_id or '?'})",
            target.workspace_id,
            report_id,
            semantic_model_id=dataset_id,
        )
    except (PowerBiApiError, OSError) as exc:
        return OpResult(
            False,
            f"PBIX deploy failed: {exc}",
            target.workspace_id,
            target.item_id,
        )
    finally:
        if owns_client:
            pbi.close()


def _resolve_source_definition(
    client: FabricClient,
    item: WorkItem,
    *,
    origin_definition_cache: dict[str, dict[str, Any]] | None,
    bind_model_id: str | None,
) -> tuple[dict[str, Any], str]:
    if item.file is not None:
        validate_local_report(item.file)
        pbir_override = None
        if bind_model_id:
            pbir_override = rewrite_pbir_to_by_connection(
                load_pbir(item.file), bind_model_id
            )
        else:
            ref = parse_dataset_reference(load_pbir(item.file))
            if ref.kind == "byPath":
                raise DefinitionError(
                    "report still uses byPath; omit --independent to deploy the "
                    "joined semantic model (rewrites to byConnection), or bind "
                    "definition.pbir to byConnection first"
                )
        return pack_definition(item.file, pbir_override=pbir_override), str(item.file)

    assert item.origin is not None and item.origin.item_id is not None
    origin = item.origin
    label = f"origin {origin.label()}"
    cache_key = origin.label()
    if origin_definition_cache is not None and cache_key in origin_definition_cache:
        definition = dict(origin_definition_cache[cache_key])
    else:
        definition = get_report_definition(client, origin.workspace_id, origin.item_id)
        if origin_definition_cache is not None:
            origin_definition_cache[cache_key] = definition

    if bind_model_id:
        definition = _rewrite_definition_pbir(definition, bind_model_id)
    return definition, label


def _rewrite_definition_pbir(
    definition: dict[str, Any], semantic_model_id: str
) -> dict[str, Any]:
    payloads = part_payloads(definition)
    raw = payloads.get(PBIR_PART)
    if raw is None:
        raise DefinitionError("origin definition is missing definition.pbir")
    pbir = json.loads(raw.decode("utf-8-sig"))
    rewritten = rewrite_pbir_to_by_connection(pbir, semantic_model_id)
    payload = json.dumps(rewritten, indent=2, ensure_ascii=False).encode("utf-8")
    new_parts: list[Any] = []
    replaced = False
    for part in definition.get("parts") or []:
        if isinstance(part, dict) and str(part.get("path")) == PBIR_PART:
            new_parts.append(encode_part(PBIR_PART, payload))
            replaced = True
        else:
            new_parts.append(part)
    if not replaced:
        new_parts.append(encode_part(PBIR_PART, payload))
    out = dict(definition)
    out["parts"] = new_parts
    return out


def resolve_bound_model_id(
    client: FabricClient,
    workspace_id: str,
    report_id: str,
    *,
    definition: dict[str, Any] | None,
    powerbi_client: Any | None,
) -> str | None:
    del client  # reserved for future Fabric-native bind lookup
    if definition is not None:
        try:
            payloads = part_payloads(definition)
            raw = payloads.get(PBIR_PART)
            if raw:
                ref = parse_dataset_reference(json.loads(raw.decode("utf-8-sig")))
                if ref.semantic_model_id:
                    return ref.semantic_model_id
                if ref.kind == "byPath":
                    return None
        except (DefinitionError, KeyError, json.JSONDecodeError, UnicodeError):
            pass

    if not report_id:
        return None

    from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient

    owns_client = powerbi_client is None
    pbi = powerbi_client or PowerBiClient()
    try:
        if owns_client:
            pbi.ensure_authenticated()
        report = pbi.get_report(workspace_id, report_id)
        dataset_id = report.get("datasetId")
        return str(dataset_id) if dataset_id else None
    except (PowerBiApiError, Exception):  # noqa: BLE001 - best-effort join
        return None
    finally:
        if owns_client:
            pbi.close()


def _extract_definition(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise FabricApiError("Report definition response was empty")
    if "definition" in result and isinstance(result["definition"], dict):
        return result["definition"]
    if "parts" in result:
        return result
    raise FabricApiError(
        "Report definition response missing 'definition'",
        details=result,
    )
