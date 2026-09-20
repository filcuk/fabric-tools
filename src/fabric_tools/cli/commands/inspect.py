"""Typer commands: inspect."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    HELP_CONTEXT,
    help_metavar,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK
from fabric_tools.sync.common import (
    _authenticate_client,
    _exit_error,
)

inspect_app = typer.Typer(
    name="inspect",
    help="List and inspect Fabric workspaces and items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)
inspect_workspace_app = typer.Typer(
    name="workspace",
    help="List or get Fabric workspaces.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)
inspect_item_app = typer.Typer(
    name="item",
    help="List or get Fabric items in a workspace.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)
inspect_app.add_typer(
    inspect_workspace_app,
    name="workspace",
    short_help="list | get -t <workspaceId>",
)
inspect_app.add_typer(
    inspect_item_app,
    name="item",
    short_help="list -t <workspaceId> | get -t <workspaceId:itemId>",
)


@inspect_workspace_app.command(
    "list",
    short_help="[-f <FILTER>] [-a <TYPE>]  List accessible Fabric workspaces.",
)
def inspect_workspace_list(
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Case-insensitive substring filter on workspace display name.",
    ),
    item_type: str | None = typer.Option(
        None,
        "--artifact",
        "-a",
        help="Workspace type filter (Personal, Workspace, AdminWorkspace).",
    ),
) -> None:
    """List accessible Fabric workspaces (aligned table)."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        list_workspaces,
        print_workspace_table,
    )
    from fabric_tools.status import busy, status_detail

    try:
        with busy(status_detail("inspect", "listing workspaces")):
            client = FabricClient()
            _authenticate_client(client)
            rows = list_workspaces(
                client,
                name_filter=name_filter,
                type_filter=item_type,
            )
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    if not rows:
        typer.echo("No workspaces matched.")
    else:
        print_workspace_table(rows)
    raise typer.Exit(code=EXIT_OK)


@inspect_workspace_app.command(
    "get",
    short_help="-t <workspaceId>  Show detailed information for one workspace.",
)
def inspect_workspace_get(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help="Workspace GUID.",
    ),
) -> None:
    """Show detailed information for one Fabric workspace."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        get_workspace_detail,
        parse_workspace_get_target,
        print_workspace_detail,
    )
    from fabric_tools.status import busy, status_detail

    try:
        parsed = parse_workspace_get_target(target)
        with busy(status_detail("inspect", "getting workspace")):
            client = FabricClient()
            _authenticate_client(client)
            row = get_workspace_detail(client, parsed)
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    print_workspace_detail(row)
    raise typer.Exit(code=EXIT_OK)


@inspect_item_app.command(
    "list",
    short_help="-t <workspaceId> [-f <FILTER>] [-a <TYPE>]  List items in a workspace.",
)
def inspect_item_list(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help="Workspace GUID whose items to list.",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Case-insensitive substring filter on item display name.",
    ),
    item_type: str | None = typer.Option(
        None,
        "--artifact",
        "-a",
        help="Fabric item type filter (Notebook, Dataflow, Report, …).",
    ),
) -> None:
    """List Fabric items in a workspace (aligned table)."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        list_items,
        parse_item_list_target,
        print_item_table,
    )
    from fabric_tools.status import busy, status_detail

    try:
        parsed = parse_item_list_target(target)
        with busy(status_detail("inspect", "listing items")):
            client = FabricClient()
            _authenticate_client(client)
            rows = list_items(
                client,
                parsed,
                name_filter=name_filter,
                type_filter=item_type,
            )
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    if not rows:
        typer.echo("No items matched.")
    else:
        print_item_table(rows)
    raise typer.Exit(code=EXIT_OK)


@inspect_item_app.command(
    "get",
    short_help="-t <workspaceId:itemId>  Show detailed information for one item.",
)
def inspect_item_get(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help=f"Workspace and item as {help_metavar('workspaceId:itemId')}.",
    ),
) -> None:
    """Show detailed information for one Fabric item."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        get_item_detail,
        parse_item_get_target,
        print_item_detail,
    )
    from fabric_tools.status import busy, status_detail

    try:
        parsed = parse_item_get_target(target)
        with busy(status_detail("inspect", "getting item")):
            client = FabricClient()
            _authenticate_client(client)
            row = get_item_detail(client, parsed)
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    print_item_detail(row)
    raise typer.Exit(code=EXIT_OK)
