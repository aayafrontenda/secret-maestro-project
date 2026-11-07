from maestro.env import load_env_file


def test_env_file_fills_unset_variables_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nMAESTRO_T_A=from-file\nMAESTRO_T_B=from-file\nMAESTRO_T_EMPTY=\nMAESTRO_T_Q=\"quoted value\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAESTRO_T_B", "from-shell")
    for key in ("MAESTRO_T_A", "MAESTRO_T_EMPTY", "MAESTRO_T_Q"):
        monkeypatch.delenv(key, raising=False)
    loaded = load_env_file(env)
    import os

    assert os.environ["MAESTRO_T_A"] == "from-file"
    assert os.environ["MAESTRO_T_B"] == "from-shell"  # the shell wins
    assert "MAESTRO_T_EMPTY" not in os.environ  # empty means "use the default"
    assert os.environ["MAESTRO_T_Q"] == "quoted value"
    assert sorted(loaded) == ["MAESTRO_T_A", "MAESTRO_T_Q"]  # monkeypatch removes them again after the test


def test_missing_env_file_is_fine(tmp_path):
    assert load_env_file(tmp_path / "absent.env") == []
