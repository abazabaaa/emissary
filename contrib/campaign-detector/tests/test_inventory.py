"""Inventory model: path normalization, strictness and TSV round trips."""

from __future__ import annotations

import io

import pytest

from campaign_detector.inventory import COLUMNS, Entry, Inventory, normalize_path


def _d(path: str, inode: int) -> Entry:
    return Entry(path, "d", 0, 100, 100, 0, 0, inode, 2)


def _tree() -> Inventory:
    return Inventory([
        _d("/", 1), _d("/a", 2), _d("/a/b", 3),
        Entry("/a/b/x.nc", "f", 10, 200, 200, 7, 7, 4, 1, sha256="ab"),
        Entry("/a/b/y.nc", "f", 5, 300, 300, 7, 7, 5, 1, sha256="ab"),
        Entry("/a/link", "l", 6, 400, 400, 7, 7, 6, 1, target="b/x.nc"),
    ])


@pytest.mark.parametrize("raw, norm", [("/", "/"), ("/a/b/", "/a/b"), ("//a//b/../c", "/a/c"), ("/a/./b", "/a/b")])
def test_normalize_path(raw: str, norm: str) -> None:
    assert normalize_path(raw) == norm


def test_normalize_rejects_relative() -> None:
    with pytest.raises(ValueError):
        normalize_path("a/b")


def test_entry_properties() -> None:
    e = Entry("/v/run_lig001/Prod001.NC", "f", 1, 0, 0, 0, 0, 1, 1)
    assert (e.name, e.parent, e.stem, e.ext) == ("Prod001.NC", "/v/run_lig001", "Prod001", ".nc")
    assert Entry("/v/Makefile", "f", 1, 0, 0, 0, 0, 1, 1).ext == ""
    assert _d("/", 1).parent is None


def test_resolved_target() -> None:
    inv = _tree()
    assert inv.by_path["/a/link"].resolved_target() == "/a/b/x.nc"
    assert Entry("/a/l2", "l", 3, 0, 0, 0, 0, 9, 1, target="/abs/../t").resolved_target() == "/t"
    assert inv.by_path["/a/b/x.nc"].resolved_target() is None


def test_strict_parent_and_duplicates() -> None:
    with pytest.raises(ValueError):
        Inventory([_d("/", 1), _d("/a/b", 2)])
    with pytest.raises(ValueError):
        Inventory([_d("/", 1), _d("/a", 2), _d("/a", 3)])
    with pytest.raises(ValueError):
        Entry("/a/", "d", 0, 0, 0, 0, 0, 1, 2)


def test_indexes_and_navigation() -> None:
    inv = _tree()
    assert [e.name for e in inv.children("/a")] == ["b", "link"]
    assert inv.parent("/a/b").path == "/a"
    assert inv.parent("/") is None
    assert [e.path for e in inv.subtree("/a")] == ["/a", "/a/b", "/a/b/x.nc", "/a/b/y.nc", "/a/link"]
    assert [e.path for e in inv.by_sha["ab"]] == ["/a/b/x.nc", "/a/b/y.nc"]
    assert len(inv.dirs()) == 3 and len(inv.files()) == 2 and len(inv.links()) == 1
    assert "/a/b" in inv and "/zz" not in inv and len(inv) == 6
    assert [e.path for e in inv] == sorted(e.path for e in inv)


def test_tsv_round_trip_with_undecodable_name(tmp_path) -> None:
    odd = "/a/b/caf\udce9.png"
    inv = Inventory(list(_tree()) + [Entry(odd, "f", 1, 1, 1, 1, 1, 99, 1)])
    out = tmp_path / "inv.tsv"
    inv.to_tsv(out)
    assert out.read_bytes().splitlines()[0].decode() == "\t".join(COLUMNS)
    assert b"caf\xe9.png" in out.read_bytes()
    back = Inventory.from_tsv(out)
    assert list(back) == list(inv)
    assert back.by_path[odd].sha256 is None and back.by_path["/a/link"].target == "b/x.nc"


def test_tsv_stream_round_trip_and_rejects_tabs() -> None:
    buf = io.StringIO()
    _tree().to_tsv(buf)
    buf.seek(0)
    assert list(Inventory.from_tsv(buf)) == list(_tree())
    bad = Inventory([_d("/", 1), Entry("/a\tb", "f", 1, 1, 1, 1, 1, 2, 1)])
    with pytest.raises(ValueError):
        bad.to_tsv(io.StringIO())


def test_carriage_return_in_a_name_round_trips(tmp_path) -> None:
    inv = Inventory([_d("/", 1), _d("/a", 2), Entry("/a/odd\rname.nc", "f", 3, 10, 10, 7, 7, 3, 1)])
    dst = tmp_path / "cr.tsv"
    inv.to_tsv(dst)
    back = Inventory.from_tsv(dst)
    assert "/a/odd\rname.nc" in back and len(back) == 3


def test_crlf_rows_are_read_and_a_trailing_cr_is_refused(tmp_path) -> None:
    good = tmp_path / "ok.tsv"
    _tree().to_tsv(good)
    crlf = tmp_path / "crlf.tsv"
    crlf.write_bytes(good.read_bytes().replace(b"\n", b"\r\n"))
    assert [e.path for e in Inventory.from_tsv(crlf)] == [e.path for e in _tree()]
    bad = Inventory([_d("/", 1), Entry("/l", "l", 2, 1, 1, 0, 0, 2, 1, target="x\r")])
    with pytest.raises(ValueError):
        bad.to_tsv(tmp_path / "bad.tsv")
