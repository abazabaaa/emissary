"""Real filesystem round trip: materialize an inventory, walk it back, detect the same thing."""

from __future__ import annotations

import errno
import hashlib
import os

import pytest

from campaign_detector.cli import main
from campaign_detector.detect import detect
from campaign_detector.inventory import Entry, Inventory
from campaign_detector.scenarios import get
from campaign_detector.scenarios.positive_amber_basic import ROOT
from campaign_detector.walker import MAX_DENSE_SIZE, Manifest, load_owners, materialize, walk_fs

FIELDS = ("path", "kind", "size", "mtime", "uid", "gid", "target", "sha256")


def _key(e: Entry) -> tuple:
    return tuple(getattr(e, f) for f in FIELDS)


def _d(path: str, inode: int, mtime: int = 1_300_000_000) -> Entry:
    return Entry(path, "d", 0, mtime, mtime, 1000, 1000, inode, 2)


def _f(path: str, inode: int, size: int, sha: str | None = None, nlink: int = 1, uid: int = 1000) -> Entry:
    return Entry(path, "f", size, 1_300_000_100 + inode, 1_300_000_100, uid, 1000, inode, nlink, sha256=sha)


@pytest.fixture(scope="module")
def kdr() -> Inventory:
    return get("positive_amber_basic.kdr_fep").build()


@pytest.fixture(scope="module")
def kdr_walked(kdr: Inventory, tmp_path_factory: pytest.TempPathFactory) -> tuple[Inventory, Manifest]:
    dest = tmp_path_factory.mktemp("kdr") / "fs"
    man = materialize(kdr, dest)
    return walk_fs(dest, map_root=(str(dest), "/"), owners=man.sidecar), man


def test_round_trip_entries_match(kdr: Inventory, kdr_walked: tuple[Inventory, Manifest]) -> None:
    walked, _ = kdr_walked
    assert walked.walk_errors == []  # type: ignore[attr-defined]
    assert sorted(e.path for e in walked) == sorted(e.path for e in kdr)
    for e in kdr:
        assert _key(walked.by_path[e.path]) == _key(e), e.path
    # ctime is not settable on disk; the sidecar carries it back.
    assert all(walked.by_path[e.path].ctime == e.ctime for e in kdr)


def test_round_trip_same_detection(kdr: Inventory, kdr_walked: tuple[Inventory, Manifest]) -> None:
    walked, _ = kdr_walked
    syn, real = detect(kdr), detect(walked)
    assert real.campaign_roots == syn.campaign_roots == [ROOT]
    (a,), (b,) = syn.campaigns, real.campaigns
    assert b.picked() == a.picked() == {"run_lig012", "run_lig029", "run_lig041"}
    assert b.not_picked() == a.not_picked() and len(b.not_picked()) == 43
    assert b.unknown() == a.unknown()
    assert b.missing_ids == a.missing_ids == ["run_lig017", "run_lig033"]
    assert real.to_dict() == syn.to_dict()


def test_walked_tsv_round_trip_detects(kdr: Inventory, kdr_walked: tuple[Inventory, Manifest], tmp_path) -> None:
    walked, _ = kdr_walked
    walked.to_tsv(tmp_path / "w.tsv")
    assert detect(Inventory.from_tsv(tmp_path / "w.tsv")).to_dict() == detect(kdr).to_dict()


def test_materialized_tree_on_disk(kdr: Inventory, kdr_walked: tuple[Inventory, Manifest]) -> None:
    _, man = kdr_walked
    dest = man.dest
    link = os.path.join(dest, ROOT.lstrip("/"), "analysis", "lig041_traj")
    assert os.readlink(link) == kdr.by_path[ROOT + "/analysis/lig041_traj"].target == "../run_lig041/prod020.nc"
    chunk = os.path.join(dest, ROOT.lstrip("/"), "run_lig001", "prod001.nc")
    st = os.stat(chunk)
    assert st.st_size == 1_200_000_000
    assert st.st_blocks * 512 < 1024 * 1024  # sparse: no data blocks
    assert os.lstat(os.path.join(dest, ROOT.lstrip("/"))).st_mtime == kdr.by_path[ROOT].mtime
    assert man.root_map == (dest, "/") and man.sidecar == dest + ".owners.tsv"
    back = load_owners(man.sidecar)
    assert back.owners == man.owners and back.sha == man.sha and back.ctime == man.ctime
    assert back.owners[ROOT + "/analysis/notes.txt"] == (3002, 1000)


def test_hardlinks_share_inode_and_owners_mapping(tmp_path) -> None:
    inv = Inventory([
        _d("/", 1), _d("/v", 2), _d("/v/a", 3), _d("/v/b", 4),
        _f("/v/a/x.nc", 10, 4096, sha="aa", nlink=2), _f("/v/b/x.nc", 10, 4096, sha="aa", nlink=2),
        _f("/v/a/y.nc", 11, 0, uid=2001),
    ])
    materialize(inv, tmp_path / "fs")
    owners = {e.path: (e.uid, e.gid, e.sha256) for e in inv}
    walked = walk_fs(tmp_path / "fs", map_root=(str(tmp_path / "fs"), "/"), owners=owners)
    a, b = walked.by_path["/v/a/x.nc"], walked.by_path["/v/b/x.nc"]
    assert a.inode == b.inode and a.nlink == b.nlink == 2
    assert walked.by_path["/v/a/y.nc"].inode != a.inode
    assert all(_key(walked.by_path[e.path]) == _key(e) for e in inv)


def test_symlink_target_verbatim(tmp_path) -> None:
    targets = {"/v/rel": "../v/a/../a/x.nc", "/v/abs": "/somewhere/else//x", "/v/dangling": "nope"}
    inv = Inventory([_d("/", 1), _d("/v", 2), _d("/v/a", 3), _f("/v/a/x.nc", 4, 10)] + [
        Entry(p, "l", len(t), 1_300_000_000, 1_300_000_000, 1000, 1000, 5 + i, 1, target=t)
        for i, (p, t) in enumerate(targets.items())])
    materialize(inv, tmp_path / "fs")
    walked = walk_fs(tmp_path / "fs", map_root=(str(tmp_path / "fs"), "/"))
    for p, t in targets.items():
        e = walked.by_path[p]
        assert (e.kind, e.target, e.size, e.mtime) == ("l", t, len(t), 1_300_000_000)


def test_non_utf8_names_survive(tmp_path) -> None:
    name = os.fsdecode(b"caf\xe9")  # surrogate-escaped
    inv = Inventory([_d("/", 1), _d("/v", 2), _d("/v/" + name, 3), _f(f"/v/{name}/x.nc", 4, 10)])
    materialize(inv, tmp_path / "fs")
    os.mkdir(os.fsencode(tmp_path / "fs" / "v") + b"/raw\xff\xfe")
    walked = walk_fs(tmp_path / "fs", map_root=(str(tmp_path / "fs"), "/"))
    raw = "/v/" + os.fsdecode(b"raw\xff\xfe")
    assert {"/v/" + name, f"/v/{name}/x.nc", raw} <= set(walked.by_path)
    walked.to_tsv(tmp_path / "w.tsv")
    back = Inventory.from_tsv(tmp_path / "w.tsv")
    assert os.fsencode(back.by_path[raw].path) == b"/v/raw\xff\xfe"
    assert f"/v/{name}/x.nc" in back


def _tree_with_subdirs(tmp_path) -> str:
    root = tmp_path / "t"
    for d in ("a", "b/deep", "c"):
        os.makedirs(root / d)
        (root / d / "f.txt").write_bytes(b"x")
    return str(root)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_directory_is_reported(tmp_path) -> None:
    root = _tree_with_subdirs(tmp_path)
    os.chmod(os.path.join(root, "b"), 0)
    seen: list[OSError] = []
    try:
        inv = walk_fs(root, map_root=(root, "/t"), on_error=seen.append)
    finally:
        os.chmod(os.path.join(root, "b"), 0o755)
    assert [e.errno for e in seen] == [errno.EACCES]
    assert "/t/b" in inv and "/t/b/deep" not in inv
    assert {"/t/a/f.txt", "/t/c/f.txt"} <= set(inv.by_path)
    assert len(inv.walk_errors) == 1  # type: ignore[attr-defined]


def test_stale_directory_is_skipped(tmp_path, monkeypatch) -> None:
    """Works as root too: inject ESTALE on opening one directory."""
    root = _tree_with_subdirs(tmp_path)
    real_open = os.open

    def flaky_open(path, flags, *args, **kwargs):
        if path == "b":
            raise OSError(errno.ESTALE, os.strerror(errno.ESTALE), path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", flaky_open)
    seen: list[OSError] = []
    inv = walk_fs(root, map_root=(root, "/t"), on_error=seen.append)
    monkeypatch.undo()
    assert [(e.errno, e.filename) for e in seen] == [(errno.ESTALE, os.path.join(root, "b"))]
    assert "/t/b" in inv and "/t/b/f.txt" not in inv and "/t/b/deep" not in inv
    assert {"/t", "/", "/t/a/f.txt", "/t/c/f.txt"} <= set(inv.by_path)
    assert inv.walk_errors == [f"{os.path.join(root, 'b')}: ESTALE {os.strerror(errno.ESTALE)}"]  # type: ignore[attr-defined]


def test_on_error_can_abort(tmp_path, monkeypatch) -> None:
    root = _tree_with_subdirs(tmp_path)
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda p, f, *a, **k: (_ for _ in ()).throw(PermissionError(errno.EACCES, "no", p))
                        if p == "c" else real_open(p, f, *a, **k))

    def boom(exc: OSError) -> None:
        raise exc

    with pytest.raises(PermissionError):
        walk_fs(root, on_error=boom)


def test_hash_matches_real_bytes(tmp_path) -> None:
    inv = Inventory([_d("/", 1), _d("/v", 2), _f("/v/a.bin", 3, 3_000_001, sha="s1"),
                     _f("/v/copy.bin", 4, 3_000_001, sha="s1"), _f("/v/other.bin", 5, 3_000_001, sha="s2"),
                     _f("/v/empty", 6, 0, sha="s3")])
    materialize(inv, tmp_path / "fs", sparse=False)
    walked = walk_fs(tmp_path / "fs", map_root=(str(tmp_path / "fs"), "/"), hash=True,
                     owners=str(tmp_path / "fs") + ".owners.tsv")
    for p in ("/v/a.bin", "/v/copy.bin", "/v/other.bin", "/v/empty"):
        data = (tmp_path / "fs" / p.lstrip("/")).read_bytes()
        assert len(data) == inv.by_path[p].size
        assert walked.by_path[p].sha256 == hashlib.sha256(data).hexdigest()  # computed hash beats the sidecar
    assert walked.by_path["/v/a.bin"].sha256 == walked.by_path["/v/copy.bin"].sha256
    assert walked.by_path["/v/a.bin"].sha256 != walked.by_path["/v/other.bin"].sha256
    assert walked.by_path["/v/empty"].sha256 == hashlib.sha256(b"").hexdigest()


def test_dense_refuses_big_files(tmp_path) -> None:
    inv = Inventory([_d("/", 1), _f("/big", 2, MAX_DENSE_SIZE + 1)])
    with pytest.raises(ValueError, match="sparse=False"):
        materialize(inv, tmp_path / "fs", sparse=False)
    assert not (tmp_path / "fs").exists()


def test_dest_must_be_empty(tmp_path) -> None:
    (tmp_path / "fs").mkdir()
    (tmp_path / "fs" / "junk").write_text("x")
    with pytest.raises(FileExistsError):
        materialize(Inventory([_d("/", 1)]), tmp_path / "fs")


def test_unmapped_walk_emits_ancestors(tmp_path) -> None:
    root = _tree_with_subdirs(tmp_path)
    inv = walk_fs(root)
    parts = root.strip("/").split("/")
    for i in range(len(parts) + 1):
        assert inv.by_path["/" + "/".join(parts[:i])].kind == "d"
    assert inv.by_path[root + "/a/f.txt"].size == 1


def test_map_root_below_destination(tmp_path) -> None:
    root = _tree_with_subdirs(tmp_path)
    inv = walk_fs(os.path.join(root, "b"), map_root=(root, "/data/proj"))
    assert {"/", "/data", "/data/proj", "/data/proj/b", "/data/proj/b/deep/f.txt"} <= set(inv.by_path)
    assert inv.by_path["/data"].inode == 0  # synthesised: no on-disk counterpart
    assert inv.by_path["/data/proj"].inode == os.stat(root).st_ino
    with pytest.raises(ValueError):
        walk_fs(root, map_root=(os.path.join(root, "b"), "/"))


def test_symlinks_not_followed_unless_asked(tmp_path) -> None:
    root = _tree_with_subdirs(tmp_path)
    os.makedirs(tmp_path / "outside")
    (tmp_path / "outside" / "secret").write_bytes(b"s")
    os.symlink("a", os.path.join(root, "to_a"))
    os.symlink("f.txt", os.path.join(root, "a", "to_f"))
    os.symlink("..", os.path.join(root, "a", "up"))
    os.symlink("../../outside", os.path.join(root, "a", "out"))
    plain = walk_fs(root, map_root=(root, "/t"))
    assert all(plain.by_path[p].kind == "l" for p in ("/t/to_a", "/t/a/to_f", "/t/a/up", "/t/a/out"))
    followed = walk_fs(root, map_root=(root, "/t"), follow_symlinks=True, hash=True)
    f, to_f = followed.by_path["/t/a/f.txt"], followed.by_path["/t/a/to_f"]
    assert (to_f.kind, to_f.size, to_f.inode, to_f.sha256) == ("f", 1, f.inode, f.sha256)
    # links to directories stay links: no escape from root, no double walk
    assert all(followed.by_path[p].kind == "l" for p in ("/t/to_a", "/t/a/up", "/t/a/out"))
    assert not any("secret" in p or p.startswith("/t/to_a/") for p in followed.by_path)


def test_line_breaks_in_names_are_skipped(tmp_path) -> None:
    root = _tree_with_subdirs(tmp_path)
    for bad in ("cr\rname", "tab\tname", "nl\nname"):
        (tmp_path / "t" / "a" / bad).write_bytes(b"")
    os.symlink("x\ry", os.path.join(root, "c", "badlink"))
    seen: list[OSError] = []
    inv = walk_fs(root, map_root=(root, "/t"), on_error=seen.append)
    assert sorted(e.errno for e in seen) == [errno.EINVAL] * 4
    inv.to_tsv(tmp_path / "w.tsv")
    assert set(Inventory.from_tsv(tmp_path / "w.tsv").by_path) == set(inv.by_path)
    assert "/t/a/f.txt" in inv and "/t/c/badlink" not in inv


def test_failed_hash_does_not_fall_back_to_sidecar(tmp_path, monkeypatch) -> None:
    root = _tree_with_subdirs(tmp_path)
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda p, f, *a, **k: (_ for _ in ()).throw(OSError(errno.EIO, "io", p))
                        if p == "f.txt" and not f & os.O_DIRECTORY else real_open(p, f, *a, **k))
    owners = {"/t/a/f.txt": (1, 2, "recorded-sha")}
    inv = walk_fs(root, map_root=(root, "/t"), hash=True, owners=owners)
    monkeypatch.undo()
    e = inv.by_path["/t/a/f.txt"]
    assert (e.uid, e.gid, e.sha256) == (1, 2, None)
    assert len(inv.walk_errors) == 3  # type: ignore[attr-defined]


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="needs /proc")
def test_abort_closes_directory_fds(tmp_path, monkeypatch) -> None:
    root = tmp_path / "t"
    os.makedirs(root / "l1" / "l2" / "l3" / "l4")
    before = _open_fds()

    def boom(exc: OSError) -> None:
        raise exc

    real_open = os.open
    monkeypatch.setattr(os, "open", lambda p, f, *a, **k: (_ for _ in ()).throw(OSError(errno.ESTALE, "stale", p))
                        if p == "l4" else real_open(p, f, *a, **k))
    with pytest.raises(OSError):
        walk_fs(root, on_error=boom)
    monkeypatch.undo()
    assert _open_fds() == before


def test_materialize_inode_collision_across_volumes(tmp_path) -> None:
    inv = Inventory([_d("/", 1), _d("/v3", 2), _d("/v4", 3),
                     Entry("/v3/a", "f", 4096, 100, 100, 1, 1, 5000, 2),
                     Entry("/v4/b", "f", 1024, 200, 200, 1, 1, 5000, 2)])
    materialize(inv, tmp_path / "fs")
    a, b = os.stat(tmp_path / "fs" / "v3" / "a"), os.stat(tmp_path / "fs" / "v4" / "b")
    assert a.st_ino != b.st_ino and (a.st_size, b.st_size) == (4096, 1024)


def test_cli_materialize_walk_detect(tmp_path, capsys) -> None:
    dest, out = tmp_path / "kdr_fs", tmp_path / "walked.tsv"
    assert main(["materialize", "--scenario", "positive_amber_basic.kdr_fep", "--dest", str(dest)]) == 0
    assert main(["materialize", "--scenario", "positive_amber_basic.kdr_fep", "--dest", str(dest)]) == 1
    assert main(["walk", "--root", str(dest), "--out", str(out), "--map-root", f"{dest}:/",
                 "--owners", f"{dest}.owners.tsv"]) == 0
    capsys.readouterr()
    assert main(["detect", "--inventory", str(out)]) == 0
    text = capsys.readouterr().out
    assert f"campaign {ROOT}" in text
    assert "picked 3  not_picked 43  unknown 0" in text
    assert "missing ids: run_lig017, run_lig033" in text
    assert main(["materialize", "--scenario", "no_such.scenario", "--dest", str(tmp_path / "x")]) == 1
    with pytest.raises(SystemExit):
        main(["walk", "--root", str(dest), "--out", str(out), "--map-root", "nocolon"])
