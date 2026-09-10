"""Check GitHub Releases for a newer fabric-tools version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from fabric_tools import __version__

GITHUB_OWNER = "filcuk"
GITHUB_REPO = "fabric-tools"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
DEFAULT_TIMEOUT_S = 5.0


class UpdateCheckError(Exception):
    """Failed to query or parse GitHub Releases."""


@dataclass(frozen=True)
class UpdateCheckResult:
    """Outcome of comparing the installed version to the latest GitHub release."""

    current: str
    latest: str
    update_available: bool
    release_url: str | None
    tag_name: str
    prerelease: bool = False


def normalize_version(value: str) -> str:
    """Strip a leading ``v`` / ``V`` from a version or tag string."""
    text = value.strip()
    if text[:1] in {"v", "V"}:
        return text[1:]
    return text


def parse_version_tuple(value: str) -> tuple[int, ...]:
    """Parse a dotted version into an int tuple for comparison (ignores pre-release suffixes)."""
    core = normalize_version(value).split("+", 1)[0].split("-", 1)[0]
    if not core:
        raise UpdateCheckError(f"invalid version: {value!r}")
    parts: list[int] = []
    for segment in core.split("."):
        digits = ""
        for char in segment:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            raise UpdateCheckError(f"invalid version: {value!r}")
        parts.append(int(digits))
    return tuple(parts)


def version_is_newer(latest: str, current: str) -> bool:
    """Return True if ``latest`` is strictly newer than ``current``."""
    return parse_version_tuple(latest) > parse_version_tuple(current)


def _parse_release(payload: dict[str, Any]) -> tuple[str, str, str | None, bool]:
    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name.strip():
        raise UpdateCheckError("GitHub release response missing tag_name")
    latest = normalize_version(tag_name)
    if not latest:
        raise UpdateCheckError(f"empty version in tag_name: {tag_name!r}")
    html_url = payload.get("html_url")
    release_url = html_url if isinstance(html_url, str) and html_url else None
    prerelease = bool(payload.get("prerelease"))
    return tag_name.strip(), latest, release_url, prerelease


def _select_newest_release(
    releases: list[Any],
) -> tuple[str, str, str | None, bool]:
    """Pick the highest semver among non-draft releases (includes pre-releases)."""
    candidates: list[tuple[tuple[int, ...], tuple[str, str, str | None, bool]]] = []
    for item in releases:
        if not isinstance(item, dict):
            continue
        if item.get("draft"):
            continue
        try:
            parsed = _parse_release(item)
        except UpdateCheckError:
            continue
        candidates.append((parse_version_tuple(parsed[1]), parsed))

    if not candidates:
        raise UpdateCheckError(
            f"no GitHub releases found for {GITHUB_OWNER}/{GITHUB_REPO}"
        )

    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1]


def fetch_latest_release(
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> tuple[str, str, str | None, bool]:
    """Fetch the newest GitHub release (incl. pre-releases).

    Uses the releases list rather than ``/releases/latest``, which ignores
    pre-releases and returns 404 when only pre-releases exist.

    Returns ``(tag_name, version, html_url, prerelease)``.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"fabric-tools/{__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    owns_client = client is None
    http = client or httpx.Client(
        timeout=timeout, headers=headers, follow_redirects=True
    )
    try:
        response = http.get(RELEASES_URL, params={"per_page": 30})
        if response.status_code == 404:
            raise UpdateCheckError(
                f"no GitHub releases found for {GITHUB_OWNER}/{GITHUB_REPO}"
            )
        if response.status_code >= 400:
            raise UpdateCheckError(
                f"GitHub API error HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpdateCheckError("GitHub release response was not JSON") from exc
        if not isinstance(payload, list):
            raise UpdateCheckError("unexpected GitHub release response shape")
        return _select_newest_release(payload)
    except httpx.HTTPError as exc:
        raise UpdateCheckError(f"failed to reach GitHub: {exc}") from exc
    finally:
        if owns_client:
            http.close()


def check_for_update(
    *,
    current: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> UpdateCheckResult:
    """Compare the installed version to the latest GitHub release."""
    installed = normalize_version(current if current is not None else __version__)
    tag_name, latest, release_url, prerelease = fetch_latest_release(
        client=client, timeout=timeout
    )
    return UpdateCheckResult(
        current=installed,
        latest=latest,
        update_available=version_is_newer(latest, installed),
        release_url=release_url,
        tag_name=tag_name,
        prerelease=prerelease,
    )
