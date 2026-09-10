"""Tests for GitHub release update checking."""

from __future__ import annotations

import httpx
import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.update_check import (
    UpdateCheckError,
    check_for_update,
    normalize_version,
    parse_version_tuple,
    version_is_newer,
)


def test_normalize_version_strips_v() -> None:
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("V0.2.0") == "0.2.0"
    assert normalize_version("0.2.0") == "0.2.0"


def test_parse_and_compare_versions() -> None:
    assert parse_version_tuple("0.2.0") == (0, 2, 0)
    assert parse_version_tuple("v0.10.1") == (0, 10, 1)
    assert version_is_newer("0.3.0", "0.2.0")
    assert version_is_newer("0.10.0", "0.9.0")
    assert not version_is_newer("0.2.0", "0.2.0")
    assert not version_is_newer("0.1.9", "0.2.0")


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


def test_check_for_update_includes_prerelease() -> None:
    """``/releases/latest`` ignores pre-releases; the list endpoint must still find them."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v0.1.0",
                    "html_url": "https://github.com/filcuk/fabric-tools/releases/tag/v0.1.0",
                    "draft": False,
                    "prerelease": True,
                }
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_for_update(current="0.2.0", client=client)

    assert result.latest == "0.1.0"
    assert result.prerelease is True
    assert result.update_available is False


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
    from fabric_tools.update_check import UpdateCheckResult

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
    from fabric_tools.update_check import UpdateCheckResult

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
