import web_dashboard
from src.toolpaths import resolve_ffprobe, resolve_player, ffprobe_is_available


# --- resolve_ffprobe --------------------------------------------------------

def test_ffprobe_configured_absolute_path_wins():
    got = resolve_ffprobe(
        "/opt/ffprobe", which_fn=lambda n: None, isfile_fn=lambda p: p == "/opt/ffprobe"
    )
    assert got == "/opt/ffprobe"


def test_ffprobe_configured_name_resolved_on_path():
    got = resolve_ffprobe(
        "ffprobe", which_fn=lambda n: "/usr/bin/ffprobe" if n == "ffprobe" else None,
        isfile_fn=lambda p: False,
    )
    assert got == "/usr/bin/ffprobe"


def test_ffprobe_blank_falls_back_to_which():
    got = resolve_ffprobe(
        "", which_fn=lambda n: "/usr/local/bin/ffprobe" if n == "ffprobe" else None,
        isfile_fn=lambda p: False,
    )
    assert got == "/usr/local/bin/ffprobe"


def test_ffprobe_last_resort_literal():
    got = resolve_ffprobe("", which_fn=lambda n: None, isfile_fn=lambda p: False)
    assert got == "ffprobe"


# --- ffprobe_is_available ---------------------------------------------------

def test_ffprobe_available_when_file_exists():
    assert ffprobe_is_available("/opt/ffprobe",
                                which_fn=lambda n: None,
                                isfile_fn=lambda p: p == "/opt/ffprobe") is True


def test_ffprobe_available_when_on_path():
    assert ffprobe_is_available("ffprobe",
                                which_fn=lambda n: "/usr/bin/ffprobe",
                                isfile_fn=lambda p: False) is True


def test_ffprobe_not_available_when_missing():
    assert ffprobe_is_available("ffprobe",
                                which_fn=lambda n: None,
                                isfile_fn=lambda p: False) is False


def test_ffprobe_not_available_when_blank():
    assert ffprobe_is_available("", which_fn=lambda n: None, isfile_fn=lambda p: False) is False


# --- resolve_player ---------------------------------------------------------

def test_player_configured_wins():
    got = resolve_player(
        "/custom/vlc", platform_name="linux",
        which_fn=lambda n: None, isfile_fn=lambda p: p == "/custom/vlc",
    )
    assert got == "/custom/vlc"


def test_player_which_fallback():
    got = resolve_player(
        "", platform_name="linux",
        which_fn=lambda n: "/usr/bin/vlc" if n == "vlc" else None,
        isfile_fn=lambda p: False,
    )
    assert got == "/usr/bin/vlc"


def test_player_windows_default_list():
    win_path = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
    got = resolve_player(
        "", platform_name="win32",
        which_fn=lambda n: None, isfile_fn=lambda p: p == win_path,
    )
    assert got == win_path


def test_player_mac_default_list():
    mac_path = "/Applications/VLC.app/Contents/MacOS/VLC"
    got = resolve_player(
        "", platform_name="darwin",
        which_fn=lambda n: None, isfile_fn=lambda p: p == mac_path,
    )
    assert got == mac_path


def test_player_none_when_nothing_found():
    got = resolve_player(
        "", platform_name="linux", which_fn=lambda n: None, isfile_fn=lambda p: False
    )
    assert got is None


# --- launch_player (web_dashboard) ------------------------------------------

def test_launch_player_uses_given_binary(monkeypatch):
    calls = []
    monkeypatch.setattr(web_dashboard.subprocess, "Popen", lambda args: calls.append(args))
    web_dashboard.launch_player("/movies/x.mkv", player_bin="/usr/bin/vlc")
    assert calls == [["/usr/bin/vlc", "/movies/x.mkv"]]


def test_launch_player_linux_default_uses_xdg_open(monkeypatch):
    calls = []
    monkeypatch.setattr(web_dashboard.sys, "platform", "linux")
    monkeypatch.setattr(web_dashboard.subprocess, "Popen", lambda args: calls.append(args))
    web_dashboard.launch_player("/movies/x.mkv")
    assert calls == [["xdg-open", "/movies/x.mkv"]]


def test_launch_player_mac_default_uses_open(monkeypatch):
    calls = []
    monkeypatch.setattr(web_dashboard.sys, "platform", "darwin")
    monkeypatch.setattr(web_dashboard.subprocess, "Popen", lambda args: calls.append(args))
    web_dashboard.launch_player("/movies/x.mkv")
    assert calls == [["open", "/movies/x.mkv"]]
