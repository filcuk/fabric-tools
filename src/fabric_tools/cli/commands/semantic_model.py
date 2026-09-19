"""Typer commands: semantic_model."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    DRY_RUN_COMPARE_HELP,
    DRY_RUN_DELETE_HELP,
    DRY_RUN_DEPLOY_HELP,
    DRY_RUN_DOWNLOAD_HELP,
    FILTER_HELP,
    HELP_CONTEXT,
    MANIFEST_DELETE_HELP,
    ORIGIN_COMPARE_HELP,
    ORIGIN_DEPLOY_HELP,
    ORIGIN_DOWNLOAD_HELP,
    TARGET_COMPARE_HELP,
    TARGET_DELETE_HELP,
    TARGET_DEPLOY_HELP,
    TARGET_DOWNLOAD_HELP,
    dry_run_opt,
    filter_opt,
    manifest_opt,
    name_opt,
    origin_opt,
    silent_opt,
    target_opt,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import (
    run_semantic_model_command,
    run_semantic_model_role_command,
)

semantic_model_app = typer.Typer(
    name="semantic-model",
    help="Fabric semantic model items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)
semantic_model_role_app = typer.Typer(
    name="role",
    help="Manage semantic-model RLS role membership (XMLA / SqlServer module).",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)
semantic_model_app.add_typer(semantic_model_role_app, name="role")
semantic_model_role_member_app = typer.Typer(
    name="member",
    help="Add or remove members on a semantic-model RLS role.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)
semantic_model_role_app.add_typer(semantic_model_role_member_app, name="member")

_INDEPENDENT_SM_HELP = (
    "(optional) Model-only when the source also packages a report "
    "(reserved for thick .pbix skipReport; no-op for folders today)."
)
_ROLE_TARGET_HELP = (
    "workspace:artifact or workspaceId:*. "
    "Repeatable or comma-separated (spaces after commas OK)."
)


@semantic_model_app.command("download")
def semantic_model_download(
    origin: list[str] | None = origin_opt(help=ORIGIN_DOWNLOAD_HELP),
    target: list[str] | None = target_opt(help=TARGET_DOWNLOAD_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DOWNLOAD_HELP),
) -> None:
    """Download semantic model definition(s) from Fabric to local folders."""
    run_semantic_model_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@semantic_model_app.command("deploy")
def semantic_model_deploy(
    target: list[str] | None = target_opt(help=TARGET_DEPLOY_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_DEPLOY_HELP),
    name: list[str] | None = name_opt(),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DEPLOY_HELP),
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help=_INDEPENDENT_SM_HELP,
    ),
) -> None:
    """Deploy semantic model definition(s) (create or overwrite)."""
    run_semantic_model_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        manifest=manifest,
        independent=independent,
    )


@semantic_model_app.command("compare")
def semantic_model_compare(
    target: list[str] | None = target_opt(help=TARGET_COMPARE_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_COMPARE_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_COMPARE_HELP),
) -> None:
    """Compare local/remote semantic model definitions to remote targets."""
    run_semantic_model_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@semantic_model_app.command("delete")
def semantic_model_delete(
    target: list[str] | None = target_opt(help=TARGET_DELETE_HELP),
    manifest: str | None = manifest_opt(help=MANIFEST_DELETE_HELP),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DELETE_HELP),
) -> None:
    """Soft-delete semantic model(s); service cascades dependent reports."""
    run_semantic_model_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@semantic_model_role_app.command("list")
def semantic_model_role_list(
    target: list[str] = target_opt(help=_ROLE_TARGET_HELP, required=True),
    name_filter: str | None = filter_opt(help=FILTER_HELP),
    silent: bool = silent_opt(
        help="(optional) Do not offer SqlServer Install-Module; fail with the hint."
    ),
    dry_run: bool = dry_run_opt(
        help="(optional) Resolve targets only; do not call XMLA."
    ),
) -> None:
    """List RLS roles and members for semantic model(s) via XMLA."""
    run_semantic_model_role_command(
        "list",
        target_values=target,
        name_filter=name_filter,
        silent=silent,
        dry_run=dry_run,
    )


@semantic_model_role_member_app.command("add")
def semantic_model_role_member_add(
    target: list[str] = target_opt(help=_ROLE_TARGET_HELP, required=True),
    role: str = typer.Option(..., "--role", "-r", help="Model role name."),
    member: str = typer.Option(
        ...,
        "--member",
        help="Member UPN or Entra group display name (AzureAD).",
    ),
    name_filter: str | None = filter_opt(help=FILTER_HELP),
    silent: bool = silent_opt(
        help=("(optional) Skip confirmation; do not offer SqlServer Install-Module.")
    ),
    dry_run: bool = dry_run_opt(
        help="(optional) Resolve targets and confirm plan only; do not mutate."
    ),
) -> None:
    """Add a member to an RLS role on semantic model(s) via XMLA."""
    run_semantic_model_role_command(
        "member_add",
        target_values=target,
        name_filter=name_filter,
        silent=silent,
        dry_run=dry_run,
        role_name=role,
        member_name=member,
    )


@semantic_model_role_member_app.command("remove")
def semantic_model_role_member_remove(
    target: list[str] = target_opt(help=_ROLE_TARGET_HELP, required=True),
    role: str = typer.Option(..., "--role", "-r", help="Model role name."),
    member: str = typer.Option(
        ...,
        "--member",
        help="Member UPN or Entra group display name (AzureAD).",
    ),
    name_filter: str | None = filter_opt(help=FILTER_HELP),
    silent: bool = silent_opt(
        help=("(optional) Skip confirmation; do not offer SqlServer Install-Module.")
    ),
    dry_run: bool = dry_run_opt(
        help="(optional) Resolve targets and confirm plan only; do not mutate."
    ),
) -> None:
    """Remove a member from an RLS role on semantic model(s) via XMLA."""
    run_semantic_model_role_command(
        "member_remove",
        target_values=target,
        name_filter=name_filter,
        silent=silent,
        dry_run=dry_run,
        role_name=role,
        member_name=member,
    )
