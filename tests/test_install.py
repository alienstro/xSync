import pytest

from xsync_cli.core.install import (
    Install,
    InstallError,
    detect_install,
    uninstall_commands,
    update_commands,
)

UV_PREFIX = "/Users/x/.local/share/uv/tools/xsync-cli"
PIPX_PREFIX = "/Users/x/.local/pipx/venvs/xsync-cli"
EDITABLE = '{"url":"file:///Users/x/src/xSync","dir_info":{"editable":true}}'
DIRECTORY = '{"url":"file:///Users/x/src/xSync","dir_info":{}}'


def test_an_editable_uv_install_is_found():
    install = detect_install(EDITABLE, UV_PREFIX)
    assert install == Install("uv", "/Users/x/src/xSync", editable=True)


def test_an_index_install_has_no_source():
    install = detect_install(None, UV_PREFIX)
    assert install == Install("uv", None, editable=False)


def test_a_pipx_install_is_found():
    assert detect_install(DIRECTORY, PIPX_PREFIX).tool == "pipx"


def test_an_unknown_prefix_raises():
    with pytest.raises(InstallError, match="uv or pipx"):
        detect_install(None, "/usr/local")


def test_a_uv_index_install_updates_with_uv_tool_upgrade():
    install = Install("uv", None, editable=False)
    assert update_commands(install, has_git=False) == [
        ["uv", "tool", "upgrade", "xsync-cli"]
    ]


def test_a_git_checkout_pulls_then_reinstalls():
    install = Install("uv", "/src", editable=True)
    assert update_commands(install, has_git=True) == [
        ["git", "-C", "/src", "pull", "--ff-only"],
        ["uv", "tool", "install", "--force", "--reinstall", "--editable", "/src"],
    ]


def test_a_folder_without_git_only_reinstalls():
    install = Install("uv", "/src", editable=False)
    assert update_commands(install, has_git=False) == [
        ["uv", "tool", "install", "--force", "--reinstall", "/src"],
    ]


def test_a_pipx_checkout_reinstalls_with_pipx():
    install = Install("pipx", "/src", editable=True)
    assert update_commands(install, has_git=False) == [
        ["pipx", "install", "--force", "--editable", "/src"],
    ]


def test_a_pipx_index_install_upgrades_with_pipx():
    install = Install("pipx", None, editable=False)
    assert update_commands(install, has_git=False) == [
        ["pipx", "upgrade", "xsync-cli"]
    ]


def test_uninstall_uses_the_tool_that_installed_xsync():
    assert uninstall_commands(Install("uv", "/src", editable=True)) == [
        ["uv", "tool", "uninstall", "xsync-cli"]
    ]
    assert uninstall_commands(Install("pipx", None, editable=False)) == [
        ["pipx", "uninstall", "xsync-cli"]
    ]
