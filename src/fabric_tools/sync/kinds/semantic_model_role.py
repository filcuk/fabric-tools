"""Orchestration for semantic-model RLS role members sync commands."""

from __future__ import annotations

import typer

from fabric_tools.auth import AuthError
from fabric_tools.colours import FG_OK, print_error_panel
from fabric_tools.exit_codes import EXIT_API, EXIT_OK
from fabric_tools.manifest import (
    KIND_SEMANTIC_MODEL,
    ManifestError,
)
from fabric_tools.parsing import CommandMode, ParseError
from fabric_tools.sync.common import (
    _KIND_EXPAND_LABELS,
    _authenticate_client,
    _cli_needs_wildcard_expand,
    _enforce_readonly_mutation,
    _exit_error,
    _exit_warn,
    _fail_auth,
    _list_items_fn_for_kind,
    _resolve_semantic_model_inputs,
)


def run_semantic_model_role_command(
    action: str,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    role_name: str | None = None,
    member_name: str | None = None,
) -> None:
    """List or mutate semantic-model RLS role members via XMLA (SqlServer module)."""
    import json
    import sys

    from fabric_tools.auth import POWER_BI_SCOPE, create_credential, get_access_token
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_semantic_model_role_member_changes,
        resolve_workspace_name,
        semantic_model_display_name,
    )
    from fabric_tools.status import busy, status_detail
    from fabric_tools.status import update as status_update
    from fabric_tools.xmla_roles import (
        XmlaRolesError,
        XmlaRolesResult,
        ensure_sqlserver_module,
        invoke_xmla_roles,
        stage_action,
    )

    if action in {"member_add", "member_remove"}:
        _enforce_readonly_mutation(
            "semantic-model role member change",
            dry_run=dry_run,
        )
        if not role_name or not member_name:
            _exit_error("--role and --member are required for member add/remove.")

    if sys.platform != "win32":
        _exit_error("semantic-model role commands require Windows PowerShell.")

    # Check the SqlServer module once, before auth/confirm and outside any spinner,
    # so the Install-Module prompt is visible (a prompt under a live spinner is
    # erased and looks like a hang).
    if not dry_run:
        try:
            ensure_sqlserver_module(offer_install=not silent, silent=silent)
        except XmlaRolesError as exc:
            _exit_error(str(exc), code=EXIT_API)

    expand_client: FabricClient | None = None
    try:
        needs_expand = _cli_needs_wildcard_expand(
            origin_values=None,
            target_values=target_values,
            mode=CommandMode.DELETE,
            name_filter=name_filter,
        )
        if needs_expand:
            with busy(status_detail("auth", "authenticating")):
                expand_client = FabricClient()
                _authenticate_client(expand_client)
            list_fn = _list_items_fn_for_kind(KIND_SEMANTIC_MODEL, expand_client)
            with busy(status_detail("semantic-model", "expanding selectors")):
                items, _, has_targets, _, _ = _resolve_semantic_model_inputs(
                    CommandMode.DELETE,
                    target_values=target_values,
                    origin_values=None,
                    dry_run=dry_run,
                    names=None,
                    manifest=None,
                    name_filter=name_filter,
                    list_items_fn=list_fn,
                    kind_label=_KIND_EXPAND_LABELS[KIND_SEMANTIC_MODEL],
                )
        else:
            items, _, has_targets, _, _ = _resolve_semantic_model_inputs(
                CommandMode.DELETE,
                target_values=target_values,
                origin_values=None,
                dry_run=dry_run,
                names=None,
                manifest=None,
                name_filter=name_filter,
            )
    except (ParseError, ManifestError) as exc:
        _exit_error(str(exc))

    if not has_targets or not items:
        _exit_error("Provide --target / -t with workspace:artifact or workspaceId:*.")

    for item in items:
        if item.target is None or item.target.item_id is None:
            _exit_error(
                "semantic-model role requires concrete model targets "
                "(workspaceId:itemId or workspaceId:*)."
            )

    client = expand_client
    if client is None:
        with busy(status_detail("auth", "authenticating")):
            client = FabricClient()
            _authenticate_client(client)

    try:
        confirm_rows: list[tuple[str, str, str, str, str]] = []
        # (workspace_name, model_name, model_id, ws_label, workspace_type)
        resolved: list[tuple[str, str, str, str, str | None]] = []
        with busy(status_detail("semantic-model", "resolving models")):
            for item in items:
                assert item.target is not None and item.target.item_id is not None
                try:
                    workspace = client.get_workspace(item.target.workspace_id)
                    model_item = client.get_item(
                        item.target.workspace_id, item.target.item_id
                    )
                except FabricApiError as exc:
                    _exit_error(str(exc), code=EXIT_API)
                ws_name = workspace.get("displayName") or workspace.get("name")
                model_name = model_item.get("displayName") or model_item.get("name")
                if not isinstance(ws_name, str) or not ws_name.strip():
                    _exit_error(
                        f"Workspace {item.target.workspace_id} has no displayName "
                        "for XMLA."
                    )
                if not isinstance(model_name, str) or not model_name.strip():
                    _exit_error(
                        f"Semantic model {item.target.item_id} has no displayName "
                        "for XMLA."
                    )
                item_type = model_item.get("type")
                if item_type and item_type != "SemanticModel":
                    _exit_error(
                        f"Target {item.target.item_id} type is {item_type!r}; "
                        "expected SemanticModel."
                    )
                ws_label = resolve_workspace_name(client, item.target.workspace_id)
                model_label = semantic_model_display_name(client, item.target)
                ws_type = workspace.get("type")
                ws_type_str = ws_type if isinstance(ws_type, str) else None
                try:
                    from fabric_tools.xmla_roles import ensure_workspace_supports_xmla

                    ensure_workspace_supports_xmla(workspace)
                except XmlaRolesError as exc:
                    _exit_error(str(exc), code=EXIT_API)
                resolved.append(
                    (
                        ws_name.strip(),
                        model_name.strip(),
                        item.target.item_id,
                        ws_label,
                        ws_type_str,
                    )
                )
                if action in {"member_add", "member_remove"}:
                    assert role_name is not None and member_name is not None
                    confirm_rows.append(
                        (
                            ws_label,
                            model_label,
                            item.target.item_id,
                            role_name,
                            member_name,
                        )
                    )

        if dry_run:
            for _ws_name, model_name, model_id, ws_label, _ws_type in resolved:
                if action == "list":
                    typer.secho(
                        f"[dry-run] would list roles on semantic model "
                        f'"{model_name}" ({model_id}) in {ws_label}',
                        fg=FG_OK,
                    )
                else:
                    verb = "add" if action == "member_add" else "remove"
                    prep = "to" if action == "member_add" else "from"
                    typer.secho(
                        f'[dry-run] would {verb} member "{member_name}" {prep} '
                        f'role "{role_name}" on semantic model "{model_name}" '
                        f"({model_id}) in {ws_label}",
                        fg=FG_OK,
                    )
            raise typer.Exit(code=EXIT_OK)

        if action in {"member_add", "member_remove"}:
            member_action = "add" if action == "member_add" else "remove"
            try:
                confirm_semantic_model_role_member_changes(
                    confirm_rows,
                    action=member_action,
                    silent=silent,
                )
            except ConfirmationAborted as exc:
                _exit_warn(str(exc))

        try:
            with busy(status_detail("semantic-model", "acquiring token")):
                token = get_access_token(
                    create_credential(), scope=POWER_BI_SCOPE
                ).token

                outcomes: list[
                    tuple[str, str, str, XmlaRolesResult | XmlaRolesError]
                ] = []
                for ws_name, model_name, model_id, ws_label, ws_type in resolved:
                    status_update(
                        status_detail(
                            "semantic-model",
                            "connecting via XMLA",
                            model_name,
                        )
                    )

                    def _on_progress(stage: str, *, _name: str = model_name) -> None:
                        status_update(
                            status_detail(
                                "semantic-model",
                                stage_action(stage),
                                _name,
                            )
                        )

                    try:
                        result = invoke_xmla_roles(
                            action=action,  # type: ignore[arg-type]
                            workspace_name=ws_name,
                            database_name=model_name,
                            access_token=token,
                            role_name=role_name,
                            member_name=member_name,
                            workspace_type=ws_type,
                            offer_install=False,
                            silent=silent,
                            on_progress=_on_progress,
                            check_module=False,
                        )
                        outcomes.append((model_name, model_id, ws_label, result))
                    except XmlaRolesError as exc:
                        outcomes.append((model_name, model_id, ws_label, exc))
        except AuthError as exc:
            _fail_auth(exc)
        except XmlaRolesError as exc:
            if exc.code == "cancelled":
                _exit_warn(str(exc) or "Cancelled.")
            stage = f" (stage={exc.stage})" if exc.stage else ""
            detail = f"\n{exc.detail}" if exc.detail else ""
            code = f" [{exc.code}]" if exc.code else ""
            _exit_error(f"{exc}{stage}{code}{detail}", code=EXIT_API)
        except KeyboardInterrupt:
            _exit_warn("Cancelled.")

        failed = False
        for model_name, model_id, ws_label, outcome in outcomes:
            if isinstance(outcome, XmlaRolesError):
                if outcome.code == "cancelled":
                    _exit_warn(str(outcome) or "Cancelled.")
                stage = f" (stage={outcome.stage})" if outcome.stage else ""
                detail = f"\n{outcome.detail}" if outcome.detail else ""
                code = f" [{outcome.code}]" if outcome.code else ""
                print_error_panel(
                    (
                        f"{model_name} ({model_id}) in {ws_label}: "
                        f"{outcome}{stage}{code}{detail}"
                    ).strip()
                    or "XMLA role operation failed."
                )
                failed = True
                continue

            header = f"{model_name} ({model_id}) in {ws_label}: {outcome.message}"
            typer.secho(header, fg=FG_OK)
            if outcome.roles:
                typer.echo(json.dumps({"roles": outcome.roles}, indent=2))

        raise typer.Exit(code=EXIT_API if failed else EXIT_OK)
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()
