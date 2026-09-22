"""Tests for GitHub release update checking."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.update_check import (
    DISABLE_UPDATE_CHECK_ENV,
    UpdateCheckError,
    UpdateCheckResult,
    check_for_update,
    checked_today,
    consume_update_notice,
    download_release_asset,
    format_update_notice,
    load_update_cache,
    normalize_version,
    parse_version_tuple,
    reset_background_update_check,
    save_update_cache,
    start_background_update_check,
    version_is_newer,
)


def test_normalize_version_strips_v() -> None:
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("V0.2.0") == "0.2.0"
    assert normalize_version("0.2.0") == "0.2.0"


def test_compact_windows_version_trims_fourth_zero() -> None:
    from fabric_tools.update_check import compact_windows_version

    assert compact_windows_version("0.3.0.0") == "0.3.0"
    assert compact_windows_version("v1.2.3.0") == "1.2.3"
    assert compact_windows_version("1.2.3.4") == "1.2.3.4"
    assert compact_windows_version("0.3.0") == "0.3.0"


def test_parse_and_compare_versions() -> None:
    assert parse_version_tuple("0.2.0") == (0, 2, 0)
    assert parse_version_tuple("v0.10.1") == (0, 10, 1)
    assert version_is_newer("0.3.0", "0.2.0")
    assert version_is_newer("0.10.0", "0.9.0")
    assert not version_is_newer("0.2.0", "0.2.0")
    assert not version_is_newer("0.1.9", "0.2.0")


def test_hotfix_outranks_base_and_skips_prerelease() -> None:
    from fabric_tools.update_check import is_semver_prerelease, version_sort_key

    assert is_semver_prerelease("1.0.0-pre.1")
    assert is_semver_prerelease("1.0.0-rc.1")
    assert not is_semver_prerelease("1.0.0")
    assert not is_semver_prerelease("1.0.0-hotfix.1")

    assert version_is_newer("1.0.0-hotfix.1", "1.0.0")
    assert version_is_newer("1.0.0-hotfix.2", "1.0.0-hotfix.1")
    assert version_is_newer("1.0.1", "1.0.0-hotfix.9")
    assert version_is_newer("1.0.0", "1.0.0-pre.1")
    assert not version_is_newer("1.0.0", "1.0.0-hotfix.1")
    assert version_sort_key("1.0.0-hotfix.1") > version_sort_key("1.0.0")
    assert version_sort_key("1.0.0") > version_sort_key("1.0.0-pre.1")


def test_parse_version_rejects_garbage() -> None:
    with pytest.raises(UpdateCheckError):
        parse_version_tuple("not-a-version")


def test_check_for_update_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/releases")
        assert not request.url.path.endswith("/releases/latest")
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v0.3.0",
                    "html_url": "https://github.com/filcuk/fabric-tools/releases/tag/v0.3.0",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": "fabric-tools.exe",
                            "browser_download_url": (
                                "https://github.com/filcuk/fabric-tools/releases/"
                                "download/v0.3.0/fabric-tools.exe"
                            ),
                        }
                    ],
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = check_for_update(current="0.2.0", client=client)

    assert result.update_available is True
    assert result.current == "0.2.0"
    assert result.latest == "0.3.0"
    assert result.tag_name == "v0.3.0"
    assert result.release_url is not None
    assert result.prerelease is False
    assert result.asset_url is not None
    assert result.asset_url.endswith("fabric-tools.exe")


def test_check_for_update_skips_semver_prerelease() -> None:
    """Semver pre-releases (``-pre``, ``-rc``, …) must not drive auto-update."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v1.0.0-pre.1",
                    "html_url": "https://github.com/filcuk/fabric-tools/releases/tag/v1.0.0-pre.1",
                    "draft": False,
                    "prerelease": True,
                },
                {
                    "tag_name": "v0.2.0",
                    "html_url": "https://github.com/filcuk/fabric-tools/releases/tag/v0.2.0",
                    "draft": False,
                    "prerelease": False,
                },
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_for_update(current="0.2.0", client=client)

    assert result.latest == "0.2.0"
    assert result.update_available is False


def test_check_for_update_only_prerelease_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v1.0.0-rc.1",
                    "html_url": "https://example/v1.0.0-rc.1",
                    "draft": False,
                    "prerelease": True,
                }
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateCheckError, match="no GitHub releases"):
            check_for_update(current="0.2.0", client=client)


def test_check_for_update_includes_hotfix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v1.0.0-pre.1",
                    "html_url": "https://example/v1.0.0-pre.1",
                    "draft": False,
                    "prerelease": True,
                },
                {
                    "tag_name": "v1.0.0-hotfix.1",
                    "html_url": "https://example/v1.0.0-hotfix.1",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": "fabric-tools.exe",
                            "browser_download_url": (
                                "https://example/v1.0.0-hotfix.1/fabric-tools.exe"
                            ),
                        }
                    ],
                },
                {
                    "tag_name": "v1.0.0",
                    "html_url": "https://example/v1.0.0",
                    "draft": False,
                    "prerelease": False,
                },
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_for_update(current="1.0.0", client=client)

    assert result.latest == "1.0.0-hotfix.1"
    assert result.tag_name == "v1.0.0-hotfix.1"
    assert result.update_available is True
    assert result.asset_url is not None


def test_check_for_update_picks_newest_among_mixed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v0.1.0",
                    "html_url": "https://example/v0.1.0",
                    "draft": False,
                    "prerelease": True,
                },
                {
                    "tag_name": "v0.2.0",
                    "html_url": "https://example/v0.2.0",
                    "draft": False,
                    "prerelease": False,
                },
                {
                    "tag_name": "v0.3.0",
                    "html_url": "https://example/v0.3.0",
                    "draft": True,
                    "prerelease": False,
                },
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_for_update(current="0.1.0", client=client)

    assert result.latest == "0.2.0"
    assert result.prerelease is False


def test_check_for_update_skips_non_semver_latest_alias() -> None:
    """Distribution alias tag ``latest`` must not abort the update check."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v0.5.1",
                    "html_url": "https://example/v0.5.1",
                    "draft": False,
                    "prerelease": True,
                },
                {
                    "tag_name": "latest",
                    "html_url": "https://example/latest",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": "fabric-tools.exe",
                            "browser_download_url": (
                                "https://example/latest/fabric-tools.exe"
                            ),
                        }
                    ],
                },
                {
                    "tag_name": "v0.5.0",
                    "html_url": "https://example/v0.5.0",
                    "draft": False,
                    "prerelease": True,
                },
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_for_update(current="0.5.1", client=client)

    assert result.latest == "0.5.1"
    assert result.tag_name == "v0.5.1"
    assert result.update_available is False


def test_check_for_update_up_to_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v0.2.0",
                    "html_url": "https://example",
                    "draft": False,
                    "prerelease": False,
                }
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_for_update(current="0.2.0", client=client)

    assert result.update_available is False


def test_check_for_update_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateCheckError, match="HTTP 500"):
            check_for_update(current="0.2.0", client=client)


def test_check_for_update_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateCheckError, match="no GitHub releases"):
            check_for_update(current="0.2.0", client=client)


def test_check_for_update_no_releases() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateCheckError, match="no GitHub releases"):
            check_for_update(current="0.2.0", client=client)


def test_download_release_asset(tmp_path: Path) -> None:
    dest = tmp_path / "fabric-tools.exe"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, content=b"exe-bytes")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = download_release_asset(
            "https://example/fabric-tools.exe", dest, client=client
        )

    assert path == dest
    assert dest.read_bytes() == b"exe-bytes"
    assert not dest.with_name(dest.name + ".partial").exists()


def test_format_update_notice() -> None:
    result = UpdateCheckResult(
        current="0.2.0",
        latest="0.3.0",
        update_available=True,
        release_url="https://example/release",
        tag_name="v0.3.0",
        prerelease=True,
    )
    notice = format_update_notice(result)
    assert notice is not None
    assert "setup update" in notice
    assert "--check" not in notice.split("Run:")[1].splitlines()[0]
    assert "https://example/release" in notice
    assert "breaking CLI changes" in notice

    stable = format_update_notice(
        UpdateCheckResult(
            current="0.2.0",
            latest="1.0.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v1.0.0",
            prerelease=False,
        ),
    )
    assert stable is not None
    assert "breaking CLI changes" not in stable

    assert (
        format_update_notice(
            UpdateCheckResult(
                current="0.2.0",
                latest="0.2.0",
                update_available=False,
                release_url=None,
                tag_name="v0.2.0",
            ),
        )
        is None
    )


def test_same_day_cache_skips_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DISABLE_UPDATE_CHECK_ENV, raising=False)
    cache = tmp_path / "update-check.json"
    today = date(2026, 9, 10)
    save_update_cache(
        UpdateCheckResult(
            current="0.2.0",
            latest="0.2.0",
            update_available=False,
            release_url=None,
            tag_name="v0.2.0",
        ),
        path=cache,
        checked_on=today.isoformat(),
    )
    assert checked_today(path=cache, today=today)

    calls = {"n": 0}

    def boom(**kwargs: object) -> UpdateCheckResult:
        calls["n"] += 1
        raise AssertionError("network should not be used")

    reset_background_update_check()
    start_background_update_check(cache_path=cache, today=today, check=boom)
    assert calls["n"] == 0
    assert consume_update_notice(cache_path=cache, today=today) is None


def test_same_day_cache_shows_notice_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DISABLE_UPDATE_CHECK_ENV, raising=False)
    cache = tmp_path / "update-check.json"
    today = date(2026, 9, 10)
    save_update_cache(
        UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v0.3.0",
        ),
        path=cache,
        checked_on=today.isoformat(),
    )

    def boom(**kwargs: object) -> UpdateCheckResult:
        raise AssertionError("network should not be used")

    reset_background_update_check()
    start_background_update_check(cache_path=cache, today=today, check=boom)
    notice = consume_update_notice(cache_path=cache, today=today)
    assert notice is not None
    assert "0.3.0" in notice
    assert "setup update" in notice


def test_next_day_allows_new_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DISABLE_UPDATE_CHECK_ENV, raising=False)
    cache = tmp_path / "update-check.json"
    yesterday = date(2026, 9, 9)
    today = yesterday + timedelta(days=1)
    save_update_cache(
        UpdateCheckResult(
            current="0.2.0",
            latest="0.2.0",
            update_available=False,
            release_url=None,
            tag_name="v0.2.0",
        ),
        path=cache,
        checked_on=yesterday.isoformat(),
    )
    assert not checked_today(path=cache, today=today)

    calls = {"n": 0}

    def fake_check(**kwargs: object) -> UpdateCheckResult:
        calls["n"] += 1
        return UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v0.3.0",
        )

    reset_background_update_check()
    start_background_update_check(cache_path=cache, today=today, check=fake_check)
    import fabric_tools.update_check as uc

    assert uc._bg_thread is not None
    uc._bg_thread.join(timeout=2.0)
    notice = consume_update_notice(cache_path=cache, today=today)
    assert calls["n"] == 1
    assert notice is not None
    assert checked_today(path=cache, today=today)
    payload = load_update_cache(path=cache)
    assert payload is not None
    assert payload["latest"] == "0.3.0"


def test_failed_background_check_does_not_stamp_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DISABLE_UPDATE_CHECK_ENV, raising=False)
    cache = tmp_path / "update-check.json"
    today = date(2026, 9, 10)

    def boom(**kwargs: object) -> UpdateCheckResult:
        raise UpdateCheckError("failed to reach GitHub")

    reset_background_update_check()
    start_background_update_check(cache_path=cache, today=today, check=boom)
    import fabric_tools.update_check as uc

    assert uc._bg_thread is not None
    uc._bg_thread.join(timeout=2.0)
    assert consume_update_notice(cache_path=cache, today=today) is None
    assert not checked_today(path=cache, today=today)
    assert load_update_cache(path=cache) is None


def test_cli_setup_update_without_check_uses_install_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fabric_tools.path_setup.perform_setup_update",
        lambda silent=False: {
            "up_to_date": False,
            "exe_path": r"C:\Temp\fabric-tools.exe",
            "scheduled": True,
        },
    )
    result = CliRunner().invoke(app, ["setup", "update", "--silent"])
    assert result.exit_code == EXIT_OK
    assert "scheduled" in result.stdout.lower()


def test_cli_setup_update_check_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: UpdateCheckResult(
            current="0.2.0",
            latest="0.2.0",
            update_available=False,
            release_url="https://example/release",
            tag_name="v0.2.0",
        ),
    )
    result = CliRunner().invoke(app, ["setup", "update", "--check"])
    assert result.exit_code == EXIT_OK
    assert "up to date" in result.stdout.lower()


def test_cli_setup_update_check_newer_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://github.com/filcuk/fabric-tools/releases/tag/v0.3.0",
            tag_name="v0.3.0",
            prerelease=True,
        ),
    )
    result = CliRunner().invoke(app, ["setup", "update", "-c"])
    assert result.exit_code == EXIT_USER
    assert "newer release" in result.stdout.lower()
    assert "[pre-release]" in result.stdout
    assert "https://github.com/filcuk/fabric-tools/releases/tag/v0.3.0" in result.stdout


def test_cli_setup_update_check_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: (_ for _ in ()).throw(UpdateCheckError("failed to reach GitHub")),
    )
    result = CliRunner().invoke(app, ["setup", "update", "--check"])
    assert result.exit_code == EXIT_API
    assert "failed to reach GitHub" in result.output


def test_cli_background_notice_from_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(DISABLE_UPDATE_CHECK_ENV, raising=False)
    cache = tmp_path / "update-check.json"
    save_update_cache(
        UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v0.3.0",
        ),
        path=cache,
        checked_on=date.today().isoformat(),
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.default_update_cache_path",
        lambda: cache,
    )
    reset_background_update_check()

    result = CliRunner().invoke(app, ["manifest", "list"])
    assert result.exit_code == EXIT_OK
    assert "Update available" in result.output
    assert "0.3.0" in result.output


def test_cli_setup_update_check_skips_background_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(DISABLE_UPDATE_CHECK_ENV, raising=False)
    cache = tmp_path / "update-check.json"
    save_update_cache(
        UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v0.3.0",
        ),
        path=cache,
        checked_on=date.today().isoformat(),
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.default_update_cache_path",
        lambda: cache,
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: UpdateCheckResult(
            current="0.2.0",
            latest="0.2.0",
            update_available=False,
            release_url=None,
            tag_name="v0.2.0",
        ),
    )
    reset_background_update_check()

    result = CliRunner().invoke(app, ["setup", "update", "--check"])
    assert result.exit_code == EXIT_OK
    assert "Update available" not in result.output
    assert "up to date" in result.stdout.lower()
