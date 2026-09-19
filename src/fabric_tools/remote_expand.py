"""Expand ``workspaceId:*`` remote selectors into concrete item targets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fabric_tools.parsing import ClassifiedEndpoints, ParseError, Target

ListItemsFn = Callable[[str], Sequence[dict[str, Any]]]


class ExpandError(ValueError):
    """Wildcard expansion failed (API or zero matches)."""


def target_is_wildcard(target: Target) -> bool:
    """True when *target* is a ``workspaceId:*`` selector."""
    return target.wildcard


def any_wildcard(targets: Sequence[Target]) -> bool:
    """True when any target in *targets* is a wildcard selector."""
    return any(t.wildcard for t in targets)


def classified_has_wildcard(classified: ClassifiedEndpoints) -> bool:
    """True when origin or target remotes include ``workspaceId:*``."""
    return any_wildcard(classified.origin_remotes) or any_wildcard(
        classified.target_remotes
    )


def validate_filter_usage(
    name_filter: str | None,
    *,
    has_wildcard: bool,
) -> None:
    """``--filter`` is only valid when at least one remote uses ``workspaceId:*``."""
    if name_filter is None or name_filter == "":
        return
    if not has_wildcard:
        raise ParseError(
            "--filter / -f is only valid with workspaceId:* "
            "(at least one --origin or --target remote must use *)"
        )


def expand_targets(
    targets: Sequence[Target],
    *,
    list_items: ListItemsFn,
    name_filter: str | None,
    kind_label: str,
) -> list[Target]:
    """Replace each ``workspaceId:*`` with concrete item targets for *kind_label*.

    Concrete selectors are kept as-is (not filtered). Zero matches for a wildcard
    raise :class:`ExpandError`.
    """
    expanded: list[Target] = []
    for target in targets:
        if not target.wildcard:
            expanded.append(target)
            continue
        try:
            rows = list(list_items(target.workspace_id))
        except Exception as exc:  # noqa: BLE001 - surface list failures as ExpandError
            raise ExpandError(
                f"failed to list {kind_label} items in workspace "
                f"{target.workspace_id}: {exc}"
            ) from exc
        rows = filter_rows_by_name(rows, name_filter)
        if not rows:
            needle = name_filter.strip() if name_filter else None
            detail = f" matching filter {needle!r}" if needle else ""
            raise ExpandError(
                f"no {kind_label} items{detail} in workspace {target.workspace_id}"
            )
        for row in rows:
            item_id = row_item_id(row)
            if not item_id:
                raise ExpandError(
                    f"list {kind_label} in workspace {target.workspace_id} "
                    "returned an item without id"
                )
            expanded.append(Target(workspace_id=target.workspace_id, item_id=item_id))
    return expanded


def expand_classified(
    classified: ClassifiedEndpoints,
    *,
    list_items: ListItemsFn,
    name_filter: str | None,
    kind_label: str,
) -> ClassifiedEndpoints:
    """Expand wildcards on both origin and target remote sides (same *name_filter*)."""
    return ClassifiedEndpoints(
        origin_remotes=expand_targets(
            classified.origin_remotes,
            list_items=list_items,
            name_filter=name_filter,
            kind_label=kind_label,
        ),
        origin_paths=list(classified.origin_paths),
        target_remotes=expand_targets(
            classified.target_remotes,
            list_items=list_items,
            name_filter=name_filter,
            kind_label=kind_label,
        ),
        target_paths=list(classified.target_paths),
    )


def filter_rows_by_name(
    rows: Sequence[dict[str, Any]],
    name_filter: str | None,
) -> list[dict[str, Any]]:
    """Keep rows whose display name contains *name_filter* (case-insensitive).

    Prefers Fabric ``displayName``, then Power BI ``name``.
    """
    if name_filter is None or name_filter == "":
        return list(rows)
    needle = name_filter.casefold()
    return [row for row in rows if needle in row_display_name(row).casefold()]


def row_display_name(row: dict[str, Any]) -> str:
    """Best-effort display name from a Fabric or Power BI list row."""
    return str(row.get("displayName") or row.get("name") or "")


def row_item_id(row: dict[str, Any]) -> str | None:
    """Best-effort item id from a Fabric or Power BI list row."""
    raw = row.get("id") if row.get("id") not in (None, "") else row.get("objectId")
    if raw is None or raw == "":
        return None
    return str(raw)
