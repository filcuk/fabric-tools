"""Run / refresh facades: notebook run, pipeline run, dataflow refresh, model refresh."""

from __future__ import annotations

from typing import Any

from fabric_tools.manifest import (
    KIND_DATAFLOW,
    KIND_NOTEBOOK,
    KIND_PIPELINE,
    KIND_SEMANTIC_MODEL,
)
from fabric_tools.pipeline.progress import pipeline_progress
from fabric_tools.sync.item_job import ItemJobSpec, run_item_job_command

NOTEBOOK_RUN = ItemJobSpec(
    kind=KIND_NOTEBOOK,
    noun="notebook",
    label="notebook",
    verb="run",
    progressive="running",
    job_type="RunNotebook",
)
PIPELINE_RUN = ItemJobSpec(
    kind=KIND_PIPELINE,
    noun="pipeline",
    label="pipeline",
    verb="run",
    progressive="running",
    job_type="Pipeline",
    progress=pipeline_progress,
)
# ApplyChangesIfNeeded: refresh the latest saved definition, not the last
# published one (deploy leaves Gen2 definitions unpublished unless --publish).
DATAFLOW_REFRESH = ItemJobSpec(
    kind=KIND_DATAFLOW,
    noun="dataflow",
    label="dataflow",
    verb="refresh",
    progressive="refreshing",
    job_type="Refresh",
    execution_data={"executeOption": "ApplyChangesIfNeeded"},
)
SEMANTIC_MODEL_REFRESH = ItemJobSpec(
    kind=KIND_SEMANTIC_MODEL,
    noun="semantic-model",
    label="semantic model",
    verb="refresh",
    progressive="refreshing",
    backend="powerbi",
)


def run_notebook_run_command(**kwargs: Any) -> None:
    """Run notebook(s) on demand via the Fabric Job Scheduler."""
    run_item_job_command(NOTEBOOK_RUN, **kwargs)


def run_pipeline_run_command(**kwargs: Any) -> None:
    """Run DataPipeline(s) on demand via the Fabric Job Scheduler."""
    run_item_job_command(PIPELINE_RUN, **kwargs)


def run_dataflow_refresh_command(**kwargs: Any) -> None:
    """Refresh Dataflow Gen2 item(s) via the Fabric Job Scheduler."""
    run_item_job_command(DATAFLOW_REFRESH, **kwargs)


def run_semantic_model_refresh_command(**kwargs: Any) -> None:
    """Refresh semantic model(s) via the Power BI refresh API."""
    run_item_job_command(SEMANTIC_MODEL_REFRESH, **kwargs)
