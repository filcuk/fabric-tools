"""Typer commands: debug."""

from __future__ import annotations

import typer

from fabric_tools.auth import AuthError
from fabric_tools.cli.options import (
    HELP_CONTEXT,
    help_metavar,
)
from fabric_tools.colours import (
    print_warn_panel,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK
from fabric_tools.sync.common import (
    _authenticate_client,
    _exit_error,
    _fail_auth,
)

debug_app = typer.Typer(
    name="debug",
    help="Internal debug helpers.",
    no_args_is_help=True,
    hidden=True,
    context_settings=HELP_CONTEXT,
)


@debug_app.command("color", help="Print the CLI colour palette swatch.")
def debug_color_cmd() -> None:
    """Show each palette colour with its usage role (see DESIGN.md)."""
    from fabric_tools.colours import print_color_swatch

    print_color_swatch()
    raise typer.Exit(code=EXIT_OK)


@debug_app.command("banner", help="Print an example of each CLI banner panel.")
def debug_banner_cmd() -> None:
    """Show Error, Warning, Info, and Success panels (see DESIGN.md)."""
    from fabric_tools.colours import print_panel_swatch

    print_panel_swatch()
    raise typer.Exit(code=EXIT_OK)


@debug_app.command("spinner", help="Run an example activity spinner.")
def debug_spinner_cmd() -> None:
    """Show a three-step busy spinner with a percent suffix (see DESIGN.md)."""
    from fabric_tools.status import run_spinner_swatch

    run_spinner_swatch()
    raise typer.Exit(code=EXIT_OK)


xmla_roles_app = typer.Typer(
    name="xmla-roles",
    help=(
        "Spike: list/add/remove semantic-model role members via PowerShell "
        "SqlServer (TOM/XMLA)."
    ),
    no_args_is_help=True,
    hidden=True,
    context_settings=HELP_CONTEXT,
)
debug_app.add_typer(xmla_roles_app, name="xmla-roles")


def _debug_resolve_model_names(target: str) -> tuple[str, str, str, str | None]:
    """Return (workspace_display_name, model_display_name, access_token, workspace_type)."""
    from fabric_tools.auth import POWER_BI_SCOPE, create_credential, get_access_token
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import InspectError, parse_item_get_target
    from fabric_tools.status import busy, status_detail

    try:
        parsed = parse_item_get_target(target)
    except InspectError as exc:
        _exit_error(str(exc))
    assert parsed.item_id is not None
    try:
        with busy(status_detail("auth", "authenticating")):
            client = FabricClient()
            _authenticate_client(client)
            token = get_access_token(create_credential(), scope=POWER_BI_SCOPE).token
        with busy(status_detail("semantic-model", "resolving model")):
            workspace = client.get_workspace(parsed.workspace_id)
            item = client.get_item(parsed.workspace_id, parsed.item_id)
    except AuthError as exc:
        _fail_auth(exc)
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    ws_name = workspace.get("displayName") or workspace.get("name")
    model_name = item.get("displayName") or item.get("name")
    if not isinstance(ws_name, str) or not ws_name.strip():
        _exit_error("Workspace has no displayName for XMLA connection.")
    if not isinstance(model_name, str) or not model_name.strip():
        _exit_error("Semantic model has no displayName for XMLA database name.")
    item_type = item.get("type")
    if item_type and item_type != "SemanticModel":
        _exit_error(f"Target type is {item_type!r}; expected SemanticModel.")
    ws_type = workspace.get("type")
    ws_type_str = ws_type if isinstance(ws_type, str) else None
    from fabric_tools.xmla_roles import (
        XmlaRolesError,
        ensure_workspace_supports_xmla,
    )

    try:
        ensure_workspace_supports_xmla(workspace)
    except XmlaRolesError as exc:
        _exit_error(str(exc), code=EXIT_API)
    return ws_name.strip(), model_name.strip(), token, ws_type_str


def _debug_xmla_invoke(
    *,
    target: str,
    action: str,
    role: str | None = None,
    member: str | None = None,
    silent: bool = False,
) -> None:
    from fabric_tools.status import busy, status_detail
    from fabric_tools.status import update as status_update
    from fabric_tools.xmla_roles import (
        XmlaRolesError,
        ensure_sqlserver_module,
        invoke_xmla_roles,
        stage_action,
    )

    try:
        # Module check first, outside any spinner, so the install prompt is visible.
        ensure_sqlserver_module(offer_install=not silent, silent=silent)
        workspace_name, database_name, token, ws_type = _debug_resolve_model_names(
            target
        )
        with busy(status_detail("semantic-model", "running role operation")):

            def _on_progress(stage: str) -> None:
                status_update(
                    status_detail(
                        "semantic-model",
                        stage_action(stage),
                        database_name,
                    )
                )

            result = invoke_xmla_roles(
                action=action,  # type: ignore[arg-type]
                workspace_name=workspace_name,
                database_name=database_name,
                access_token=token,
                role_name=role,
                member_name=member,
                workspace_type=ws_type,
                offer_install=False,
                silent=silent,
                on_progress=_on_progress,
                check_module=False,
            )
    except XmlaRolesError as exc:
        stage = f" (stage={exc.stage})" if exc.stage else ""
        detail = f"\n{exc.detail}" if exc.detail else ""
        code = f" [{exc.code}]" if exc.code else ""
        _exit_error(f"{exc}{stage}{code}{detail}", code=EXIT_API)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)

    typer.echo(result.message)
    if result.roles:
        import json

        typer.echo(json.dumps({"roles": result.roles}, indent=2))
    raise typer.Exit(code=EXIT_OK)


@xmla_roles_app.command("list", help="List roles and members for one semantic model.")
def debug_xmla_roles_list(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help=f"{help_metavar('workspaceId:itemId')} of a SemanticModel.",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="Do not offer SqlServer Install-Module; fail with the install hint.",
    ),
) -> None:
    """Spike: XMLA role list via SqlServer PowerShell module."""
    _debug_xmla_invoke(target=target, action="list", silent=silent)


@xmla_roles_app.command("member-add", help="Add a UPN/group to a model role.")
def debug_xmla_roles_member_add(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help=f"{help_metavar('workspaceId:itemId')} of a SemanticModel.",
    ),
    role: str = typer.Option(..., "--role", help="Model role name."),
    member: str = typer.Option(
        ...,
        "--member",
        help="Member UPN or group name (AzureAD).",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="Do not offer SqlServer Install-Module; fail with the install hint.",
    ),
) -> None:
    """Spike: XMLA role member add via SqlServer PowerShell module."""
    _debug_xmla_invoke(
        target=target,
        action="member_add",
        role=role,
        member=member,
        silent=silent,
    )


@xmla_roles_app.command("member-remove", help="Remove a UPN/group from a model role.")
def debug_xmla_roles_member_remove(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help=f"{help_metavar('workspaceId:itemId')} of a SemanticModel.",
    ),
    role: str = typer.Option(..., "--role", help="Model role name."),
    member: str = typer.Option(
        ...,
        "--member",
        help="Member UPN or group name (AzureAD).",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="Do not offer SqlServer Install-Module; fail with the install hint.",
    ),
) -> None:
    """Spike: XMLA role member remove via SqlServer PowerShell module."""
    _debug_xmla_invoke(
        target=target,
        action="member_remove",
        role=role,
        member=member,
        silent=silent,
    )


def _flush_update_notice(ctx: typer.Context) -> None:
    """Print a background update notice on stderr, if one is ready."""
    if ctx.meta.get("skip_bg_update"):
        return
    from fabric_tools.update_check import consume_update_notice

    notice = consume_update_notice()
    if notice:
        print_warn_panel(notice)


def _start_bg_update_check(ctx: typer.Context) -> None:
    """Register notice flush and start a once-per-day background check."""
    ctx.call_on_close(lambda: _flush_update_notice(ctx))
    if ctx.meta.get("skip_bg_update"):
        return
    from fabric_tools.update_check import start_background_update_check

    start_background_update_check()
