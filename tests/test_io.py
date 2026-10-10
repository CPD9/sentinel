import json
import os

import pytest

from pipeline.io import write_json_atomic


def test_roundtrip_and_no_temp_left(tmp_path):
    p = write_json_atomic(tmp_path / "a" / "x.json", {"ü": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"ü": 1}
    assert [f.name for f in p.parent.iterdir()] == ["x.json"]


def test_unserialisable_keeps_old_file(tmp_path):
    p = write_json_atomic(tmp_path / "x.json", {"v": 1})
    with pytest.raises(TypeError):
        write_json_atomic(p, {"v": object()})
    assert json.loads(p.read_text()) == {"v": 1}
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_failed_replace_keeps_old_file_and_cleans_temp(tmp_path, monkeypatch):
    p = write_json_atomic(tmp_path / "x.json", {"v": 1})
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        write_json_atomic(p, {"v": 2})
    monkeypatch.undo()
    assert json.loads(p.read_text()) == {"v": 1}
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_fsync_called_before_replace(tmp_path, monkeypatch):
    order = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1])
    write_json_atomic(tmp_path / "x.json", {})
    assert order == ["fsync", "replace"]
