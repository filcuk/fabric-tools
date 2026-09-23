"""Tests for the shared run / refresh runner (``fabric_tools.sync.item_job``)."""

from __future__ import annotations

from typing import Any

import pytest
import typer

from fabric_tools.client import FabricApiError, ItemJobStart
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import KIND_PIPELINE, KIND_SEMANTIC_MODEL
from fabric_tools.powerbi_client import DatasetRefreshStart
from fabric_tools.sync.item_job import ItemJobSpec, run_item_job_command

WS = "11111111-1111-1111-1111-111111111111"
ITEM_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ITEM_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

PIPELINE_SPEC = ItemJobSpec(
    kind=KIND_PIPELINE,
    noun="pipeline",
    label="pipeline",
    verb="run",
    progressive="running",
    job_type="Pipeline",
)
MODEL_SPEC = ItemJobSpec(
    kind=KIND_SEMANTIC_MODEL,
    noun="semantic-model",
    label="semantic model",
    verb="refresh",
    progressive="refreshing",
    backend="powerbi",
)

_NAMES = {ITEM_A: "Load Sales", ITEM_B: "Load Stock"}


class FakeFabric:
    instances: list[FakeFabric] = []
    item_type = "DataPipeline"
    fail_wait_for: set[str] = set()
    poll_payloads: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.started: list[tuple[str, str, str, Any]] = []
        self.waited: list[str] = []
        self.closed = False
        FakeFabric.instances.append(self)

    def ensure_authenticated(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "Dev"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {"id": item_id, "displayName": _NAMES[item_id], "type": self.item_type}

    def list_items(self, workspace_id: str, *, type: str | None = None) -> list:
        return [
            {"id": item_id, "displayName": name, "type": type}
            for item_id, name in _NAMES.items()
        ]

    def run_on_demand_item_job(
        self,
        workspace_id: str,
        item_id: str,
        job_type: str,
        *,
        execution_data: dict[str, Any] | None = None,
    ) -> ItemJobStart:
        self.started.append((workspace_id, item_id, job_type, execution_data))
        return ItemJobStart(
            workspace_id=workspace_id,
            item_id=item_id,
            job_type=job_type,
            job_instance_id=f"job-{item_id[:4]}",
            location=None,
            retry_after=1,
        )

    def wait_for_item_job(self, job: ItemJobStart, *, on_poll=None) -> dict:
        self.waited.append(job.item_id)
        if on_poll is not None:
            for payload in FakeFabric.poll_payloads:
                on_poll(payload)
        if job.item_id in FakeFabric.fail_wait_for:
            raise FabricApiError("Copy1 failed", error_code="ActivityFailed")
        return {"status": "Completed"}


class FakePowerBi:
    instances: list[FakePowerBi] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.refreshed: list[str] = []
        self.waited: list[str] = []
        FakePowerBi.instances.append(self)

    def ensure_authenticated(self) -> None:
        pass

    def close(self) -> None:
        pass

    def refresh_dataset(self, group_id: str, dataset_id: str) -> DatasetRefreshStart:
        self.refreshed.append(dataset_id)
        return DatasetRefreshStart(
            group_id=group_id,
            dataset_id=dataset_id,
            request_id="req-1",
            refresh_id="rf-1",
            location=None,
        )

    def wait_for_dataset_refresh(self, refresh: DatasetRefreshStart) -> dict:
        self.waited.append(refresh.dataset_id)
        return {"status": "Completed"}


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeFabric.instances = []
    FakeFabric.item_type = "DataPipeline"
    FakeFabric.fail_wait_for = set()
    FakeFabric.poll_payloads = []
    FakePowerBi.instances = []
    monkeypatch.setattr("fabric_tools.client.FabricClient", FakeFabric)
    monkeypatch.setattr("fabric_tools.powerbi_client.PowerBiClient", FakePowerBi)
    monkeypatch.delenv("FABRIC_TOOLS_READONLY", raising=False)
    monkeypatch.setenv("FABRIC_TOOLS_GUID_LENGTH", "7")


def _plain(text: str) -> str:
    """Collapse Rich panel borders and wrapping into one line of prose."""
    lines = [line.strip().strip("│┌┐└┘─").strip() for line in text.splitlines()]
    return " ".join(line for line in lines if line)


def _run(spec: ItemJobSpec = PIPELINE_SPEC, **kwargs: Any) -> int:
    kwargs.setdefault("target_values", [f"{WS}:{ITEM_A}"])
    kwargs.setdefault("silent", True)
    with pytest.raises(typer.Exit) as exc_info:
        run_item_job_command(spec, **kwargs)
    return exc_info.value.exit_code


def test_dry_run_lists_targets_without_starting(capsys) -> None:
    code = _run(dry_run=True)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "[dry-run] would run pipeline Load Sales (aaaaaaa) in Dev (1111111)" in out
    assert FakeFabric.instances[0].started == []


def test_readonly_blocks_execute(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("FABRIC_TOOLS_READONLY", "1")

    code = _run()

    assert code == EXIT_USER
    assert "pipeline run" in capsys.readouterr().err
    assert FakeFabric.instances == []


def test_readonly_allows_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FABRIC_TOOLS_READONLY", "1")

    assert _run(dry_run=True) == EXIT_OK


def test_missing_targets_errors(capsys) -> None:
    code = _run(target_values=None)

    assert code == EXIT_USER
    assert "--target / -t" in _plain(capsys.readouterr().err)
    assert FakeFabric.instances == []


def test_wrong_item_type_errors(capsys) -> None:
    FakeFabric.item_type = "Notebook"

    code = _run()

    assert code == EXIT_USER
    assert "expected DataPipeline" in _plain(capsys.readouterr().err)


def test_waits_by_default_with_info_panel(capsys) -> None:
    code = _run()

    assert code == EXIT_OK
    captured = capsys.readouterr()
    err = _plain(captured.err)
    assert "Info" in err
    assert "Skip waiting with --no-wait / -w." in err
    assert "run completed Load Sales (aaaaaaa) in Dev (1111111)" in captured.out
    client = FakeFabric.instances[0]
    assert client.started == [(WS, ITEM_A, "Pipeline", None)]
    assert client.waited == [ITEM_A]
    assert client.closed


def test_no_wait_prints_job_id_without_info_panel(capsys) -> None:
    code = _run(no_wait=True)

    assert code == EXIT_OK
    captured = capsys.readouterr()
    assert "Info" not in captured.err
    assert (
        "run started Load Sales (aaaaaaa) in Dev (1111111) · job job-aaaa"
        in captured.out
    )
    assert FakeFabric.instances[0].waited == []


def test_wildcard_runs_every_match_and_reports_failures(capsys) -> None:
    FakeFabric.fail_wait_for = {ITEM_A}

    code = _run(target_values=[f"{WS}:*"], name_filter="load")

    assert code == EXIT_API
    captured = capsys.readouterr()
    assert "run failed Load Sales (aaaaaaa) in Dev (1111111): Copy1 failed" in (
        _plain(captured.err)
    )
    assert "run completed Load Stock (bbbbbbb) in Dev (1111111)" in captured.out
    assert FakeFabric.instances[0].waited == [ITEM_A, ITEM_B]


def test_confirm_names_every_target(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_prompt(message: str, **_kwargs: Any) -> bool:
        prompts.append(message)
        return False

    monkeypatch.setattr("fabric_tools.confirm.prompt_confirm", fake_prompt)

    code = _run(target_values=[f"{WS}:{ITEM_A},{ITEM_B}"], silent=False)

    assert code == EXIT_USER
    assert "About to run pipeline(s):" in prompts[0]
    assert "pipeline Load Sales (aaaaaaa) in Dev (1111111)" in prompts[0]
    assert "pipeline Load Stock (bbbbbbb) in Dev (1111111)" in prompts[0]
    assert FakeFabric.instances[0].started == []


def test_progress_hook_updates_spinner(monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []
    monkeypatch.setattr("fabric_tools.status.update", lines.append)
    FakeFabric.poll_payloads = [{"status": "InProgress"}, {"status": "Broken"}]

    def progress(client, target, job):
        def detail(payload: dict[str, Any]) -> str | None:
            if payload["status"] == "Broken":
                raise RuntimeError("activity lookup failed")
            return "2/5 Copy1"

        return detail

    spec = ItemJobSpec(
        kind=KIND_PIPELINE,
        noun="pipeline",
        label="pipeline",
        verb="run",
        progressive="running",
        job_type="Pipeline",
        progress=progress,
    )

    assert _run(spec) == EXIT_OK
    assert "pipeline: running (Load Sales) · 2/5 Copy1…" in lines


def test_semantic_model_refresh_uses_powerbi(capsys) -> None:
    FakeFabric.item_type = "SemanticModel"

    code = _run(MODEL_SPEC)

    assert code == EXIT_OK
    assert "refresh completed Load Sales (aaaaaaa) in Dev (1111111)" in (
        capsys.readouterr().out
    )
    assert FakeFabric.instances[0].started == []
    assert FakePowerBi.instances[0].refreshed == [ITEM_A]
    assert FakePowerBi.instances[0].waited == [ITEM_A]


def test_semantic_model_refresh_no_wait_prints_refresh_id(capsys) -> None:
    FakeFabric.item_type = "SemanticModel"

    code = _run(MODEL_SPEC, no_wait=True)

    assert code == EXIT_OK
    assert "refresh started Load Sales (aaaaaaa) in Dev (1111111) · job rf-1" in (
        capsys.readouterr().out
    )
    assert FakePowerBi.instances[0].waited == []
