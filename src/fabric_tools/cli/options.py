"""Shared CLI help strings (Option factories added in a later phase)."""

from __future__ import annotations

MANIFEST_HELP = (
    "(optional) Deployment manifest stem or path (.ftdep). "
    "Alone: load targets/origins (and local paths). With a successful run or dry-run: write/update the manifest."
)
FILTER_HELP = (
    "(optional) Case-insensitive displayName substring; "
    "only valid with workspaceId:* on --origin or --target."
)
GUID_REMAP_HELP = (
    "(optional, deploy only) JSON file remapping source GUID → target GUID. "
    "Applied in memory to definition text before create/update "
    "(skips .platform). Repeatable or comma-separated; one file may broadcast "
    "to all targets, or pair 1:1 with targets."
)

HELP_CONTEXT = {"help_option_names": ["--help", "-h"]}
