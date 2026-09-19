"""Orchestration for semantic model sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_SEMANTIC_MODEL
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _exit_error,
    _resolve_semantic_model_deploy_names,
    _resolve_semantic_model_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_semantic_model_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    independent: bool = False,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for semantic-model CLI commands and the interactive wizard."""
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_semantic_model,
        confirm_deploy_actions_semantic_model,
        confirm_download_overwrites_semantic_model,
        resolve_semantic_model_download_files,
    )
    from fabric_tools.semantic_model.compare import (
        run_compare_batch as run_sm_compare,
    )
    from fabric_tools.semantic_model.ops import run_delete_batch as run_sm_delete
    from fabric_tools.semantic_model.ops import run_deploy_batch as run_sm_deploy
    from fabric_tools.semantic_model.ops import run_download_batch as run_sm_download
    from fabric_tools.validate import run_dry_run_semantic_model

    def validate_flags(req: SyncRequest) -> None:
        if independent and req.mode is not CommandMode.DEPLOY:
            _exit_error(
                "--independent / -i is only valid on semantic-model deploy "
                "(delete always follows service cascade)."
            )

    def after_resolve(req: SyncRequest) -> None:
        if req.mode is CommandMode.DEPLOY and any(
            item.file is not None and item.file.suffix.lower() == ".pbix"
            for item in req.items
        ):
            _exit_error(
                "semantic-model deploy from .pbix is not supported yet "
                "(folder *.SemanticModel only; PBIX skipReport via --independent "
                "comes with report support)."
            )
        # Folder/origin deploy is already model-only; --independent is reserved for
        # thick .pbix (skipReport) once PBIX import is wired.
        _ = independent

    spec = KindSpec(
        kind=KIND_SEMANTIC_MODEL,
        status_label="semantic-model",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_semantic_model_inputs),
        resolve_deploy_names=_resolve_semantic_model_deploy_names,
        run_dry_run=run_dry_run_semantic_model,
        resolve_download_files=resolve_semantic_model_download_files,
        confirm_download=confirm_download_overwrites_semantic_model,
        confirm_deploy=confirm_deploy_actions_semantic_model,
        confirm_delete=confirm_delete_semantic_model,
        run_download=run_sm_download,
        run_deploy=run_sm_deploy,
        run_compare=run_sm_compare,
        run_delete=run_sm_delete,
        validate_flags=validate_flags,
        after_resolve=after_resolve,
    )
    run_sync_command(
        spec,
        SyncRequest(
            mode=mode,
            target_values=target_values,
            silent=silent,
            dry_run=dry_run,
            name_filter=name_filter,
            origin_values=origin_values,
            names=names,
            manifest=manifest,
            on_success=on_success,
        ),
    )
