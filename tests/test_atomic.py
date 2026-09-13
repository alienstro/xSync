import json

import pytest

from xsync_cli.core.atomic import write_json_atomic


def test_write_creates_the_file(tmp_path):
    path = tmp_path / "catalog.json"
    write_json_atomic(path, {"models": []})
    assert json.loads(path.read_text()) == {"models": []}


def test_write_keeps_one_backup(tmp_path):
    path = tmp_path / "catalog.json"
    write_json_atomic(path, {"models": [1]})
    write_json_atomic(path, {"models": [2]})
    assert json.loads(path.read_text()) == {"models": [2]}
    assert json.loads(path.with_suffix(".json.bak").read_text()) == {"models": [1]}


def test_the_second_write_replaces_the_backup(tmp_path):
    path = tmp_path / "catalog.json"
    write_json_atomic(path, {"models": [1]})
    write_json_atomic(path, {"models": [2]})
    write_json_atomic(path, {"models": [3]})
    assert json.loads(path.with_suffix(".json.bak").read_text()) == {"models": [2]}


def test_no_temporary_file_stays(tmp_path):
    path = tmp_path / "catalog.json"
    write_json_atomic(path, {"models": []})
    assert [p.name for p in tmp_path.iterdir()] == ["catalog.json"]


def test_a_failed_write_keeps_the_old_file(tmp_path):
    path = tmp_path / "catalog.json"
    write_json_atomic(path, {"models": [1]})
    with pytest.raises(TypeError):
        write_json_atomic(path, {"models": [object()]})
    assert json.loads(path.read_text()) == {"models": [1]}
