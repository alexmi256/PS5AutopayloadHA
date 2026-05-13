from __future__ import annotations

from atomic_write import atomic_write_bytes, atomic_write_text


def test_atomic_write_text_writes_content(tmp_path):
    target = tmp_path / "sources.json"
    atomic_write_text(target, '{"k": "v"}')
    assert target.read_text() == '{"k": "v"}'
    assert not (tmp_path / "sources.json.tmp").exists()


def test_atomic_write_text_overwrites_existing(tmp_path):
    target = tmp_path / "state.json"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_text_leaves_target_intact_if_tmp_write_fails(tmp_path, monkeypatch):
    target = tmp_path / "meta.json"
    target.write_text("intact original")

    # Force write_text on the .tmp path to blow up; the original file must
    # not be touched because os.replace never runs.
    real_write_text = type(target).write_text

    def boom(self, *args, **kwargs):
        if self.name.endswith(".tmp"):
            raise OSError("disk full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(type(target), "write_text", boom)

    try:
        atomic_write_text(target, "new content")
    except OSError:
        pass

    assert target.read_text() == "intact original"


def test_atomic_write_bytes_round_trip(tmp_path):
    target = tmp_path / "payload.elf"
    payload = b"\x7fELF" + b"\x00" * 1024
    atomic_write_bytes(target, payload)
    assert target.read_bytes() == payload


def test_atomic_write_accepts_str_path(tmp_path):
    target = tmp_path / "sources.json"
    atomic_write_text(str(target), "ok")
    assert target.read_text() == "ok"
