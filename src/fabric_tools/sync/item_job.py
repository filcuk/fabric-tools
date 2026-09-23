"""Remote-only run / refresh orchestration (Fabric Job Scheduler, Power BI refresh).

Sits beside ``run_sync_command``: no local paths, no manifest rewrite. Targets
resolve like delete (``-t`` / ``workspaceId:*`` / ``-f`` / ``-m`` with itemId).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import typer

from fabric_tools.auth import AuthError
from fabric_tools.colours import FG_OK, print_error_panel, print_info_panel
from fabric_tools.confirm import CONFIRM_ABORT_MESSAGE
from fabric_tools.display import format_item_ref
from fabric_tools.exit_codes import EXIT_API, EXIT_OK
from fabric_tools.manifest import ManifestError
from fabric_tools.parsing import CommandMode, ParseError, Target
from fabric_tools.sync.common import (
    _KIND_EXPAND_LABELS,
    _authenticate_client,
    _cli_needs_wildcard_expand,
    _enforce_readonly_mutation,
    _exit_error,
    _exit_user_abort,
    _exit_warn,
    _fail_auth,
    _list_items_fn_for_kind,
    _resolve_sync_inputs,
)

if TYPE_CHECKING:
    from fabric_tools.client import FabricClient, ItemJobStart

_MISSING_TARGETS_MESSAGE = (
    "Provide --target / -t with workspace:artifact or workspaceId:*, "
    "or --manifest / -m with itemId entries."
)

# Builds a per-job poll hook that returns live spinner detail (or ``None``).
ProgressFactory = Callable[
    ["FabricClient", Target, "ItemJobStart"],
    Callable[[dict[str, Any]], str | None],
]


@dataclass(frozen=True)
class ItemJobSpec:
    """How one kind runs or refreshes remotely."""

    kind: str
    noun: str
    label: str
    verb: str
    progressive: str
    backend: Literal["fabric", "powerbi"] = "fabric"
    job_type: str | None = None
    execution_data: dict[str, Any] | None = None
    progress: ProgressFactory | None = None


@dataclass(frozen=True)
class _JobTarget:
    target: Target
    name: str
    workspace: str

    @property
    def ref(self) -> str:
        return format_item_ref(self.name, self.target.item_id)


def run_item_job_command(
    spec: ItemJobSpec,
    *,
    target_values: list[str] | None,
    manifest: str | None = None,
    name_filter: str | None = None,
    silent: bool = False,
    dry_run: bool = False,
    no_wait: bool = False,
) -> None:
    """Resolve targets, confirm, then start (and by default wait for) each job."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.status import busy, status_detail

    _enforce_readonly_mutation(f"{spec.noun} {spec.verb}", dry_run=dry_run)

    if not target_values and not manifest:
        _exit_error(_MISSING_TARGETS_MESSAGE)

    try:
        _cli_needs_wildcard_expand(
            origin_values=None,
            target_values=target_values,
            mode=CommandMode.DELETE,
            name_filter=name_filter,
        )
    except ParseError as exc:
        _exit_error(str(exc))

    with busy(status_detail("auth", "authenticating")):
        client = FabricClient()
        _authenticate_client(client)

    try:
        with busy(status_detail(spec.noun, "resolving targets")):
            try:
                items, _, has_targets, _, _ = _resolve_sync_inputs(
                    CommandMode.DELETE,
                    expected_kind=spec.kind,
                    target_values=target_values,
                    origin_values=None,
                    dry_run=dry_run,
                    names=None,
                    manifest=manifest,
                    name_filter=name_filter,
                    list_items_fn=_list_items_fn_for_kind(spec.kind, client),
                    kind_label=_KIND_EXPAND_LABELS[spec.kind],
                )
            except (ParseError, ManifestError) as exc:
                _exit_error(str(exc))
            except FabricApiError as exc:
                _exit_error(str(exc), code=EXIT_API)

            if not has_targets or not items:
                _exit_error(_MISSING_TARGETS_MESSAGE)
            targets = [_resolve_job_target(spec, client, item.target) for item in items]

        if dry_run:
            for job_target in targets:
                typer.secho(
                    f"[dry-run] would {spec.verb} {spec.label} {job_target.ref} "
                    f"in {job_target.workspace}",
                    fg=FG_OK,
                )
            raise typer.Exit(code=EXIT_OK)

        from fabric_tools.confirm import ConfirmationAborted, confirm_item_jobs

        try:
            confirm_item_jobs(
                [(t.workspace, t.name, t.target.item_id or "") for t in targets],
                label=spec.label,
                verb=spec.verb,
                silent=silent,
            )
        except (ConfirmationAborted, typer.Abort) as exc:
            _exit_user_abort(exc)

        failed = _execute_jobs(spec, client, targets, no_wait=no_wait)
        raise typer.Exit(code=EXIT_API if failed else EXIT_OK)
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def _resolve_job_target(
    spec: ItemJobSpec,
    client: FabricClient,
    target: Target | None,
) -> _JobTarget:
    from fabric_tools.client import FabricApiError
    from fabric_tools.confirm import resolve_workspace_name

    if target is None or target.item_id is None:
        _exit_error(
            f"{spec.noun} {spec.verb} requires concrete targets "
            "(workspaceId:itemId or workspaceId:*)."
        )
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)
    expected_type = _KIND_EXPAND_LABELS[spec.kind]
    item_type = data.get("type")
    if item_type and item_type != expected_type:
        _exit_error(
            f"Target {target.item_id} type is {item_type!r}; expected {expected_type}."
        )
    name = data.get("displayName") or data.get("name") or target.item_id
    return _JobTarget(
        target=target,
        name=str(name),
        workspace=resolve_workspace_name(client, target.workspace_id),
    )


def _execute_jobs(
    spec: ItemJobSpec,
    client: FabricClient,
    targets: list[_JobTarget],
    *,
    no_wait: bool,
) -> bool:
    """Start each job in order (and wait unless *no_wait*); return True on any failure."""
    from fabric_tools.client import FabricApiError
    from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient
    from fabric_tools.status import busy, progress_message, status_detail
    from fabric_tools.status import update as status_update

    powerbi: PowerBiClient | None = None
    if spec.backend == "powerbi":
        with busy(status_detail("auth", "authenticating")):
            powerbi = PowerBiClient()
            _authenticate_client(powerbi)

    if not no_wait:
        print_info_panel(
            f"Waiting for each {spec.label} {spec.verb} to finish. "
            "Skip waiting with --no-wait / -w."
        )

    total = len(targets)
    failed = False
    try:
        for index, job_target in enumerate(targets, start=1):

            def line(
                action: str, detail: str | None = None, *, _t=job_target, _i=index
            ):
                text = status_detail(spec.noun, action, _t.name, detail=detail)
                return progress_message(_i, total, text) if total > 1 else text

            started_id: str | None = None
            try:
                with busy(line(f"starting {spec.verb}")):
                    if powerbi is not None:
                        refresh = powerbi.refresh_dataset(
                            job_target.target.workspace_id,
                            job_target.target.item_id or "",
                        )
                        started_id = refresh.refresh_id or refresh.request_id
                    else:
                        job = client.run_on_demand_item_job(
                            job_target.target.workspace_id,
                            job_target.target.item_id or "",
                            spec.job_type or "",
                            execution_data=spec.execution_data,
                        )
                        started_id = job.job_instance_id or job.location

                    if no_wait:
                        typer.secho(
                            f"{spec.verb} started {job_target.ref} in "
                            f"{job_target.workspace} · job {started_id or '(unknown)'}",
                            fg=FG_OK,
                        )
                        continue

                    status_update(line(spec.progressive))
                    if powerbi is not None:
                        powerbi.wait_for_dataset_refresh(refresh)
                    else:
                        client.wait_for_item_job(
                            job,
                            on_poll=_progress_hook(
                                spec,
                                client,
                                job_target.target,
                                job,
                                lambda detail: status_update(
                                    line(spec.progressive, detail)
                                ),
                            ),
                        )
                typer.secho(
                    f"{spec.verb} completed {job_target.ref} in {job_target.workspace}",
                    fg=FG_OK,
                )
            except (FabricApiError, PowerBiApiError) as exc:
                print_error_panel(
                    f"{spec.verb} failed {job_target.ref} in {job_target.workspace}: "
                    f"{exc}"
                )
                failed = True
            except KeyboardInterrupt:
                if started_id is None:
                    _exit_warn(CONFIRM_ABORT_MESSAGE)
                _exit_warn(
                    f"Stopped waiting. The {spec.label} {spec.verb} continues in the "
                    f"service: {job_target.ref} · job {started_id}"
                )
    finally:
        if powerbi is not None:
            powerbi.close()
    return failed


def _progress_hook(
    spec: ItemJobSpec,
    client: FabricClient,
    target: Target,
    job: ItemJobStart,
    report: Callable[[str], None],
) -> Callable[[dict[str, Any]], None] | None:
    """Wrap ``spec.progress`` so progress lookups never fail the job wait."""
    if spec.progress is None:
        return None
    try:
        detail_for = spec.progress(client, target, job)
    except Exception:  # noqa: BLE001
        return None

    def on_poll(payload: dict[str, Any]) -> None:
        try:
            detail = detail_for(payload)
        except Exception:  # noqa: BLE001
            return
        if detail:
            report(detail)

    return on_poll
