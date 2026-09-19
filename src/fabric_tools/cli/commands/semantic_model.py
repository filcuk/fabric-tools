"""Typer commands: semantic_model."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    FILTER_HELP,
    HELP_CONTEXT,
    MANIFEST_HELP,
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


@semantic_model_app.command("download")
def semantic_model_download(
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Remote workspace:artifact to download. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(optional) Local destination path. "
        "Defaults to remote display name with the kind extension in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One path may broadcast to all origins.",
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=MANIFEST_HELP,
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or local folders only; do not download.",
    ),
) -> None:
    """Download semantic model definition(s) to local *.SemanticModel folders."""
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Local path or remote workspace:artifact source.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional) Display name for create. Defaults from folder stem. "
        "One name may broadcast.",
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=MANIFEST_HELP,
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or sources only; do not deploy.",
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Model-only when the source also packages a report "
        "(e.g. thick .pbix → skipReport). No-op for *.SemanticModel folders. "
        "Not available on delete (service cascade cannot be opted out).",
    ),
) -> None:
    """Create or overwrite semantic model(s) from a local folder or Fabric origin."""
    run_semantic_model_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        names=name,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
        independent=independent,
    )


@semantic_model_app.command("compare")
def semantic_model_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Local path or remote workspace:artifact source.",
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=MANIFEST_HELP,
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or sources only; do not compare.",
    ),
) -> None:
    """Compare target semantic model to a local folder or Fabric origin."""
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=MANIFEST_HELP,
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets only; do not delete.",
    ),
) -> None:
    """Soft-delete semantic model(s); the service also removes dependent reports."""
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
    target: list[str] = typer.Option(
        ...,
        "--target",
        "-t",
        help="workspace:artifact or workspaceId:*. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Do not offer SqlServer Install-Module; fail with the hint.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Resolve targets only; do not call XMLA.",
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
    target: list[str] = typer.Option(
        ...,
        "--target",
        "-t",
        help="workspace:artifact or workspaceId:*. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    role: str = typer.Option(
        ...,
        "--role",
        "-r",
        help="Model role name.",
    ),
    member: str = typer.Option(
        ...,
        "--member",
        help="Member UPN or Entra group display name (AzureAD).",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation; do not offer SqlServer Install-Module.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Resolve targets and confirm plan only; do not mutate.",
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
    target: list[str] = typer.Option(
        ...,
        "--target",
        "-t",
        help="workspace:artifact or workspaceId:*. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    role: str = typer.Option(
        ...,
        "--role",
        "-r",
        help="Model role name.",
    ),
    member: str = typer.Option(
        ...,
        "--member",
        help="Member UPN or Entra group display name (AzureAD).",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation; do not offer SqlServer Install-Module.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Resolve targets and confirm plan only; do not mutate.",
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
