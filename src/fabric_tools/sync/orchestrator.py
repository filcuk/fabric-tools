"""Shared sync orchestration loop driven by per-kind ``KindSpec``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import typer

from fabric_tools.auth import AuthError
from fabric_tools.colours import FG_ID, FG_OK, print_error_panel
from fabric_tools.confirm import ConfirmationAborted
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.guid_map import guid_map_confirm_line
from fabric_tools.manifest import ManifestError
from fabric_tools.parsing import CommandMode, ParseError, WorkItem
from fabric_tools.status import busy, status_detail
from fabric_tools.sync.common import (
    _KIND_EXPAND_LABELS,
    _authenticate_client,
    _cli_needs_wildcard_expand,
    _enforce_readonly_command,
    _exit_error,
    _exit_from_compare_results,
    _exit_from_op_results,
    _exit_user_abort,
    _fail_auth,
    _list_items_fn_for_kind,
    _notify_success,
    _print_compare_results,
    _print_op_results,
    _resolve_deploy_guid_maps,
    _write_manifest_after_success,
)


@dataclass
class ResolvedBundle:
    """Normalized resolve-inputs result (optional extras for report join, cells, …)."""

    items: list[WorkItem]
    resolved_names: list[str | None] | list[str] | None
    has_targets: bool
    has_files: bool
    has_origins: bool
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncRequest:
    """One sync invocation (CLI / interactive / pack)."""

    mode: CommandMode
    target_values: list[str] | None
    silent: bool
    dry_run: bool
    name_filter: str | None = None
    origin_values: list[str] | None = None
    names: list[str | None] | list[str] | None = None
    manifest: str | None = None
    on_success: Callable[..., None] | None = None
    remap_values: list[str] | None = None
    guid_maps_override: list[dict[str, str] | None] | None = None
    # Runtime (filled by orchestrator)
    items: list[WorkItem] = field(default_factory=list)
    resolved_names: list[str | None] | list[str] | None = None
    has_targets: bool = False
    has_files: bool = False
    has_origins: bool = False
    display_names: list[str] | None = None
    guid_maps: list[dict[str, str] | None] | None = None
    map_line: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


ResolveInputsFn = Callable[..., ResolvedBundle]
ResolveDeployNamesFn = Callable[
    [list[WorkItem], list[str | None] | list[str] | None], list[str]
]
ClientFactory = Callable[[], Any]


@dataclass(frozen=True)
class KindSpec:
    """Per-kind hooks for the shared sync loop."""

    kind: str
    status_label: str
    make_client: ClientFactory
    resolve_inputs: ResolveInputsFn
    resolve_deploy_names: ResolveDeployNamesFn
    run_dry_run: Callable[..., list]
    resolve_download_files: Callable[..., list[WorkItem]]
    confirm_download: Callable[..., None]
    confirm_deploy: Callable[..., None]
    confirm_delete: Callable[..., None]
    run_download: Callable[..., list]
    run_deploy: Callable[..., list]
    run_compare: Callable[..., list]
    run_delete: Callable[..., list]
    supports_remap: bool = False
    parse_exceptions: tuple[type[BaseException], ...] = (ParseError, ManifestError)
    # Optional hooks
    validate_flags: Callable[[SyncRequest], None] | None = None
    after_resolve: Callable[[SyncRequest], None] | None = None
    dry_run_notes: Callable[[SyncRequest], None] | None = None
    dry_run_kwargs: Callable[[SyncRequest], dict[str, Any]] | None = None
    download_kwargs: Callable[[SyncRequest], dict[str, Any]] | None = None
    deploy_confirm_kwargs: Callable[[SyncRequest], dict[str, Any]] | None = None
    deploy_kwargs: Callable[[SyncRequest], dict[str, Any]] | None = None
    compare_kwargs: Callable[[SyncRequest], dict[str, Any]] | None = None
    delete_confirm_kwargs: Callable[[SyncRequest], dict[str, Any]] | None = None
    prepare_deploy: Callable[[SyncRequest, Any], None] | None = None
    manifest_kwargs: Callable[[SyncRequest], dict[str, Any]] | None = None
    echo_created: Callable[[Any], None] | None = None


def _default_echo_created(result: Any) -> None:
    if (
        result.ok
        and result.workspace_id
        and result.item_id
        and "created" in result.message
    ):
        typer.secho(
            f"GUID: {result.workspace_id}:{result.item_id}",
            fg=FG_ID,
        )


def _call_kwargs(
    hook: Callable[[SyncRequest], dict[str, Any]] | None, req: SyncRequest
) -> dict[str, Any]:
    return hook(req) if hook is not None else {}


def _apply_resolved(req: SyncRequest, bundle: ResolvedBundle) -> None:
    req.items = bundle.items
    req.resolved_names = bundle.resolved_names
    req.has_targets = bundle.has_targets
    req.has_files = bundle.has_files
    req.has_origins = bundle.has_origins
    req.extras = dict(bundle.extras)


def _resolve_with_expand(spec: KindSpec, req: SyncRequest) -> Any:
    """Resolve work items; return expand client if one was opened for wildcards."""
    expand_client = None
    needs_expand = _cli_needs_wildcard_expand(
        origin_values=req.origin_values,
        target_values=req.target_values,
        mode=req.mode,
        name_filter=req.name_filter,
    )
    if needs_expand:
        with busy(status_detail("auth", "authenticating")):
            expand_client = spec.make_client()
            _authenticate_client(expand_client)
        list_fn = _list_items_fn_for_kind(spec.kind, expand_client)
        with busy(status_detail(spec.status_label, "expanding selectors")):
            bundle = spec.resolve_inputs(
                req.mode,
                target_values=req.target_values,
                origin_values=req.origin_values,
                dry_run=req.dry_run,
                names=req.names,
                manifest=req.manifest,
                name_filter=req.name_filter,
                list_items_fn=list_fn,
                kind_label=_KIND_EXPAND_LABELS[spec.kind],
            )
    else:
        bundle = spec.resolve_inputs(
            req.mode,
            target_values=req.target_values,
            origin_values=req.origin_values,
            dry_run=req.dry_run,
            names=req.names,
            manifest=req.manifest,
            name_filter=req.name_filter,
        )
    _apply_resolved(req, bundle)
    return expand_client


def _setup_guid_maps(spec: KindSpec, req: SyncRequest) -> None:
    if not spec.supports_remap or req.mode is not CommandMode.DEPLOY:
        req.guid_maps = None
        req.map_line = None
        return

    if req.guid_maps_override is not None:
        req.guid_maps = list(req.guid_maps_override)
        req.map_line = (
            "Will apply GUID remap map(s) from pack orchestration."
            if any(req.guid_maps_override)
            else None
        )
        return

    guid_map_specs = _resolve_deploy_guid_maps(
        req.remap_values,
        n_targets=len(req.items),
        has_targets=req.has_targets,
        manifest=req.manifest,
        expected_kind=spec.kind,
    )
    req.guid_maps = [
        spec_.mapping if spec_ is not None else None for spec_ in guid_map_specs
    ]
    req.map_line = guid_map_confirm_line(guid_map_specs) if guid_map_specs else None


def _resolve_display_names(spec: KindSpec, req: SyncRequest) -> None:
    if req.mode is not CommandMode.DEPLOY:
        req.display_names = None
        return
    try:
        req.display_names = spec.resolve_deploy_names(req.items, req.resolved_names)
    except ParseError as exc:
        _exit_error(str(exc))


def _manifest_write(
    spec: KindSpec,
    req: SyncRequest,
    *,
    op_results: list | None = None,
    compare_results: list | None = None,
    display_names: list[str] | None = None,
) -> None:
    kwargs = _call_kwargs(spec.manifest_kwargs, req)
    _write_manifest_after_success(
        req.manifest,
        req.items,
        display_names=display_names,
        op_results=op_results,  # type: ignore[arg-type]
        compare_results=compare_results,  # type: ignore[arg-type]
        kind=spec.kind,
        **kwargs,
    )


def run_sync_command(spec: KindSpec, req: SyncRequest) -> None:
    """Run download/deploy/compare/delete (or dry-run) for one kind."""
    _enforce_readonly_command(req.mode, dry_run=req.dry_run)
    if spec.validate_flags is not None:
        spec.validate_flags(req)

    expand_client = None
    try:
        expand_client = _resolve_with_expand(spec, req)
        if spec.after_resolve is not None:
            spec.after_resolve(req)
    except spec.parse_exceptions as exc:
        _exit_error(str(exc))

    _setup_guid_maps(spec, req)

    if req.dry_run:
        _run_dry_run(spec, req, expand_client)
        return

    _resolve_display_names(spec, req)

    client = expand_client
    if client is None:
        with busy(status_detail("auth", "authenticating")):
            client = spec.make_client()
            _authenticate_client(client)
    try:
        if req.mode is CommandMode.DOWNLOAD:
            _run_download(spec, req, client)
        elif req.mode is CommandMode.DEPLOY:
            _run_deploy(spec, req, client)
        elif req.mode is CommandMode.COMPARE:
            _run_compare(spec, req, client)
        elif req.mode is CommandMode.DELETE:
            _run_delete(spec, req, client)
        else:
            _exit_error(f"Unknown mode: {req.mode}")
    except ConfirmationAborted as exc:
        _exit_user_abort(exc)
    except typer.Abort as exc:
        _exit_user_abort(exc)
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def _run_dry_run(spec: KindSpec, req: SyncRequest, expand_client: Any) -> None:
    client = expand_client
    try:
        if (req.has_targets or req.has_origins) and client is None:
            with busy(status_detail("auth", "authenticating")):
                client = spec.make_client()
                _authenticate_client(client)
        with busy(status_detail(spec.status_label, "checking")):
            results = spec.run_dry_run(
                req.mode,
                req.items,
                client=client,
                has_targets=req.has_targets,
                has_files=req.has_files,
                has_origins=req.has_origins,
                **_call_kwargs(spec.dry_run_kwargs, req),
            )
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
    finally:
        if client is not None:
            client.close()

    failed = False
    for result in results:
        if result.ok:
            typer.secho(result.message, fg=FG_OK)
        else:
            print_error_panel(result.message)
            failed = True

    if not failed and spec.dry_run_notes is not None:
        spec.dry_run_notes(req)

    if not failed and req.has_targets and (req.has_files or req.has_origins):
        _resolve_display_names(spec, req)
        _manifest_write(spec, req, display_names=req.display_names)
        _notify_success(
            req.on_success,
            req.items,
            display_names=req.display_names,
        )
    raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)


def _run_download(spec: KindSpec, req: SyncRequest, client: Any) -> None:
    req.items = spec.resolve_download_files(client, req.items)
    spec.confirm_download(client, req.items, silent=req.silent)
    # Start on ``checking`` so kinds that preflight (e.g. report join) never flash
    # a premature ``downloading`` line before the bind is known.
    with busy(status_detail(spec.status_label, "checking")):
        op_results = spec.run_download(
            client, req.items, **_call_kwargs(spec.download_kwargs, req)
        )
    _print_op_results(op_results)  # type: ignore[arg-type]
    _manifest_write(spec, req, op_results=op_results, display_names=None)
    _notify_success(
        req.on_success,
        req.items,
        display_names=None,
        op_results=op_results,  # type: ignore[arg-type]
    )
    _exit_from_op_results(op_results)  # type: ignore[arg-type]


def _run_deploy(spec: KindSpec, req: SyncRequest, client: Any) -> None:
    if spec.prepare_deploy is not None:
        spec.prepare_deploy(req, client)
    spec.confirm_deploy(
        client,
        req.items,
        silent=req.silent,
        display_names=req.display_names,
        **_call_kwargs(spec.deploy_confirm_kwargs, req),
    )
    with busy(status_detail(spec.status_label, "deploying")):
        op_results = spec.run_deploy(
            client,
            req.items,
            display_names=req.display_names,
            **_call_kwargs(spec.deploy_kwargs, req),
        )
    _print_op_results(op_results)  # type: ignore[arg-type]
    echo = spec.echo_created or _default_echo_created
    for result in op_results:
        echo(result)
    _manifest_write(spec, req, op_results=op_results, display_names=req.display_names)
    _notify_success(
        req.on_success,
        req.items,
        display_names=req.display_names,
        op_results=op_results,  # type: ignore[arg-type]
    )
    _exit_from_op_results(op_results)  # type: ignore[arg-type]


def _run_compare(spec: KindSpec, req: SyncRequest, client: Any) -> None:
    with busy(status_detail(spec.status_label, "checking")):
        compare_results = spec.run_compare(
            client, req.items, **_call_kwargs(spec.compare_kwargs, req)
        )
    _print_compare_results(compare_results)  # type: ignore[arg-type]
    _manifest_write(spec, req, compare_results=compare_results, display_names=None)
    _notify_success(
        req.on_success,
        req.items,
        display_names=None,
        compare_results=compare_results,  # type: ignore[arg-type]
    )
    _exit_from_compare_results(compare_results)  # type: ignore[arg-type]


def _run_delete(spec: KindSpec, req: SyncRequest, client: Any) -> None:
    spec.confirm_delete(
        client,
        req.items,
        silent=req.silent,
        **_call_kwargs(spec.delete_confirm_kwargs, req),
    )
    with busy(status_detail(spec.status_label, "deleting")):
        op_results = spec.run_delete(client, req.items)
    _print_op_results(op_results)  # type: ignore[arg-type]
    _notify_success(
        req.on_success,
        req.items,
        display_names=None,
        op_results=op_results,  # type: ignore[arg-type]
    )
    _exit_from_op_results(op_results)  # type: ignore[arg-type]


def wrap_five_tuple_resolve(resolve_fn: Callable[..., tuple]) -> ResolveInputsFn:
    """Adapt a classic 5-tuple ``_resolve_*_inputs`` to ``ResolvedBundle``."""

    def _wrapped(*args: Any, **kwargs: Any) -> ResolvedBundle:
        items, names, has_targets, has_files, has_origins = resolve_fn(*args, **kwargs)
        return ResolvedBundle(
            items=items,
            resolved_names=names,
            has_targets=has_targets,
            has_files=has_files,
            has_origins=has_origins,
        )

    return _wrapped


def remap_dry_run_notes(req: SyncRequest) -> None:
    """Shared dry-run remap status lines for remap-capable kinds."""
    if not (req.remap_values or req.map_line):
        return
    if req.map_line:
        typer.secho(f"remap ok: {req.map_line}", fg=FG_OK)
    else:
        typer.secho("remap ok: GUID remap file(s) valid", fg=FG_OK)


def require_remap_deploy_only(req: SyncRequest) -> None:
    if req.remap_values and req.mode is not CommandMode.DEPLOY:
        _exit_error("--remap / -r is only valid with deploy")
