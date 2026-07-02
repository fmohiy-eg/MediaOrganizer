from run_dashboard import resolve_bind


def test_defaults_to_8081_when_unset():
    assert resolve_bind({}) == ("0.0.0.0", 8081)


def test_uses_config_server_block():
    cfg = {"server": {"host": "127.0.0.1", "port": 9000}}
    assert resolve_bind(cfg) == ("127.0.0.1", 9000)


def test_cli_port_overrides_config():
    cfg = {"server": {"host": "0.0.0.0", "port": 8081}}
    assert resolve_bind(cfg, cli_port="8090") == ("0.0.0.0", 8090)   # str coerced to int


def test_cli_host_overrides_config():
    cfg = {"server": {"host": "0.0.0.0", "port": 8081}}
    assert resolve_bind(cfg, cli_host="127.0.0.1")[0] == "127.0.0.1"


def test_non_numeric_port_exits_cleanly():
    import pytest
    with pytest.raises(SystemExit) as e:               # clean message, not a traceback
        resolve_bind({}, cli_port="abc")
    assert e.value.code == 1
