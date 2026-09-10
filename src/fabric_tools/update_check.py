"""Check GitHub Releases for a newer fabric-tools version."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from fabric_tools import __version__

GITHUB_OWNER = "filcuk"
GITHUB_REPO = "fabric-tools"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
RELEASE_EXE_NAME = "fabric-tools.exe"
DEFAULT_TIMEOUT_S = 5.0
DISABLE_UPDATE_CHECK_ENV = "FABRIC_TOOLS_DISABLE_UPDATE_CHECK"
CACHE_DIR_NAME = "cache"
CACHE_FILE_NAME = "update-check.json"


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
    asset_url: str | None = None


_bg_lock = threading.Lock()
_bg_started = False
_bg_thread: threading.Thread | None = None
_bg_result: UpdateCheckResult | None = None
_bg_notice_from_cache: str | None = None


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


def _exe_asset_url(payload: dict[str, Any]) -> str | None:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None
    for item in assets:
        if not isinstance(item, dict):
            continue
        if item.get("name") != RELEASE_EXE_NAME:
            continue
        url = item.get("browser_download_url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _parse_release(
    payload: dict[str, Any],
) -> tuple[str, str, str | None, bool, str | None]:
    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name.strip():
        raise UpdateCheckError("GitHub release response missing tag_name")
    latest = normalize_version(tag_name)
    if not latest:
        raise UpdateCheckError(f"empty version in tag_name: {tag_name!r}")
    html_url = payload.get("html_url")
    release_url = html_url if isinstance(html_url, str) and html_url else None
    prerelease = bool(payload.get("prerelease"))
    return tag_name.strip(), latest, release_url, prerelease, _exe_asset_url(payload)


def _select_newest_release(
    releases: list[Any],
) -> tuple[str, str, str | None, bool, str | None]:
    """Pick the highest semver among non-draft releases (includes pre-releases)."""
    candidates: list[
        tuple[tuple[int, ...], tuple[str, str, str | None, bool, str | None]]
    ] = []
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
) -> tuple[str, str, str | None, bool, str | None]:
    """Fetch the newest GitHub release (incl. pre-releases).

    Uses the releases list rather than ``/releases/latest``, which ignores
    pre-releases and returns 404 when only pre-releases exist.

    Returns ``(tag_name, version, html_url, prerelease, asset_url)``.
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
    tag_name, latest, release_url, prerelease, asset_url = fetch_latest_release(
        client=client, timeout=timeout
    )
    return UpdateCheckResult(
        current=installed,
        latest=latest,
        update_available=version_is_newer(latest, installed),
        release_url=release_url,
        tag_name=tag_name,
        prerelease=prerelease,
        asset_url=asset_url,
    )


def default_update_cache_path() -> Path:
    """Path to the once-per-day update-check cache file."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data) / "fabric-tools"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        root = (
            Path(xdg) / "fabric-tools"
            if xdg
            else Path.home() / ".cache" / "fabric-tools"
        )
    return root / CACHE_DIR_NAME / CACHE_FILE_NAME


def load_update_cache(*, path: Path | None = None) -> dict[str, Any] | None:
    """Load the update-check cache, or ``None`` if missing/invalid."""
    cache_path = path or default_update_cache_path()
    try:
        raw = cache_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def save_update_cache(
    result: UpdateCheckResult,
    *,
    path: Path | None = None,
    checked_on: str | None = None,
) -> None:
    """Persist a successful check result stamped with a local calendar date."""
    cache_path = path or default_update_cache_path()
    payload = {
        "checked_on": checked_on or date.today().isoformat(),
        "current": result.current,
        "latest": result.latest,
        "update_available": result.update_available,
        "release_url": result.release_url,
        "tag_name": result.tag_name,
        "prerelease": result.prerelease,
        "asset_url": result.asset_url,
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Cache is best-effort; never fail the caller.
        return


def checked_today(
    *,
    path: Path | None = None,
    today: date | None = None,
) -> bool:
    """Return True if a successful check was already recorded for the local date."""
    payload = load_update_cache(path=path)
    if not payload:
        return False
    checked_on = payload.get("checked_on")
    if not isinstance(checked_on, str):
        return False
    return checked_on == (today or date.today()).isoformat()


def result_from_cache(payload: dict[str, Any]) -> UpdateCheckResult | None:
    """Rebuild an ``UpdateCheckResult`` from cache JSON, or ``None`` if incomplete."""
    current = payload.get("current")
    latest = payload.get("latest")
    tag_name = payload.get("tag_name")
    update_available = payload.get("update_available")
    if not isinstance(current, str) or not isinstance(latest, str):
        return None
    if not isinstance(tag_name, str) or not isinstance(update_available, bool):
        return None
    release_url = payload.get("release_url")
    asset_url = payload.get("asset_url")
    return UpdateCheckResult(
        current=current,
        latest=latest,
        update_available=update_available,
        release_url=release_url if isinstance(release_url, str) else None,
        tag_name=tag_name,
        prerelease=bool(payload.get("prerelease")),
        asset_url=asset_url if isinstance(asset_url, str) else None,
    )


def format_update_notice(result: UpdateCheckResult, *, frozen: bool) -> str | None:
    """Build a user-facing notice, or ``None`` when no update is available."""
    if not result.update_available:
        return None
    lines = [
        f"Update available: {result.latest} (you have {result.current}).",
    ]
    if frozen:
        lines.append("Run: fabric-tools setup update")
    else:
        lines.append("Run: fabric-tools setup update --check")
    if result.release_url:
        lines.append(result.release_url)
    return "\n".join(lines)


def _update_check_disabled() -> bool:
    value = os.environ.get(DISABLE_UPDATE_CHECK_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def reset_background_update_check() -> None:
    """Clear in-process background-check state (for tests)."""
    global _bg_started, _bg_thread, _bg_result, _bg_notice_from_cache
    with _bg_lock:
        _bg_started = False
        _bg_thread = None
        _bg_result = None
        _bg_notice_from_cache = None


def start_background_update_check(
    *,
    current: str | None = None,
    cache_path: Path | None = None,
    today: date | None = None,
    check: Callable[..., UpdateCheckResult] | None = None,
    frozen: bool | None = None,
) -> None:
    """Start at most one background GitHub check for this process.

    Skips the network when a successful check was already stored for today.
    Failures are swallowed; they do not stamp the day cache.
    """
    global _bg_started, _bg_thread, _bg_result, _bg_notice_from_cache

    if _update_check_disabled():
        return

    with _bg_lock:
        if _bg_started:
            return
        _bg_started = True
        _bg_thread = None
        _bg_result = None
        _bg_notice_from_cache = None

        if checked_today(path=cache_path, today=today):
            payload = load_update_cache(path=cache_path)
            if payload:
                cached = result_from_cache(payload)
                if cached is not None:
                    if frozen is None:
                        from fabric_tools.path_setup import is_frozen

                        frozen = is_frozen()
                    _bg_notice_from_cache = format_update_notice(cached, frozen=frozen)
            return

        check_fn = check or check_for_update

        def worker() -> None:
            global _bg_result
            try:
                result = check_fn(current=current)
            except Exception:
                return
            with _bg_lock:
                _bg_result = result

        thread = threading.Thread(
            target=worker,
            name="fabric-tools-update-check",
            daemon=True,
        )
        _bg_thread = thread
        thread.start()


def consume_update_notice(
    *,
    frozen: bool | None = None,
    cache_path: Path | None = None,
    today: date | None = None,
) -> str | None:
    """Return a notice if an update is available; never block on the network.

    Joins the background thread with timeout 0. On a completed successful check,
    writes today's cache stamp. Returns ``None`` when up to date, still running,
    disabled, or failed.
    """
    global _bg_notice_from_cache

    if _update_check_disabled():
        return None

    if frozen is None:
        from fabric_tools.path_setup import is_frozen

        frozen = is_frozen()

    with _bg_lock:
        cached_notice = _bg_notice_from_cache
        _bg_notice_from_cache = None
        thread = _bg_thread
        result = _bg_result

    if cached_notice is not None:
        return cached_notice

    if thread is not None:
        thread.join(timeout=0)

    with _bg_lock:
        result = _bg_result

    if result is None:
        return None

    save_update_cache(
        result,
        path=cache_path,
        checked_on=(today or date.today()).isoformat(),
    )
    return format_update_notice(result, frozen=frozen)
