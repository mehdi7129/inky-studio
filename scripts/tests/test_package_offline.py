"""Check real source selection and deterministic tar bytes without app imports."""
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("package_offline", SCRIPTS / "package_offline.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_archive_is_deterministic_flat_and_compatible_with_safe_extractor(tmp_path):
    files = {"server/a.py": (b"never executed", 0o644), "scripts/cli": (b"cli", 0o755)}
    first, second = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    module.application_archive(files, first, 1700000000)
    module.application_archive(dict(reversed(list(files.items()))), second, 1700000000)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        assert archive.getnames() == ["scripts/cli", "server/a.py"]
        assert all(member.isfile() and member.uid == member.gid == 0 for member in archive)
        assert archive.getmember("scripts/cli").mode == 0o755
        assert archive.extractfile("server/a.py").read() == b"never executed"


def test_frontend_rejects_symlinks_and_requires_built_index(tmp_path):
    with pytest.raises(ValueError, match="index"):
        module.frontend_files(tmp_path)
    (tmp_path / "index.html").write_text("built")
    (tmp_path / "bad.js").symlink_to(tmp_path / "index.html")
    with pytest.raises(ValueError, match="regular"):
        module.frontend_files(tmp_path)
    (tmp_path / "bad.js").unlink()
    (tmp_path / "nested").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        module.frontend_files(tmp_path)


def test_archive_limits_do_not_create_output(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_CONTENT", 1)
    out = tmp_path / "out.tar.gz"
    with pytest.raises(ValueError, match="limits"):
        module.application_archive({"a": (b"large", 0o644)}, out, 0)
    assert not out.exists()


def test_frontend_replaced_by_link_is_not_followed(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("initial")
    secret = tmp_path.parent / "outside.txt"
    secret.write_text("not a release asset")
    real_read = module.read_regular

    def replace_before_open(name, directory):
        if name == "index.html":
            (tmp_path / name).unlink()
            (tmp_path / name).symlink_to(secret)
        return real_read(name, directory)

    monkeypatch.setattr(module, "read_regular", replace_before_open)
    with pytest.raises(OSError):
        module.frontend_files(tmp_path)


def test_regular_read_is_bounded(tmp_path, monkeypatch):
    (tmp_path / "large").write_bytes(b"123")
    monkeypatch.setattr(module, "MAX_FILE", 2)
    directory = os.open(tmp_path, os.O_RDONLY)
    try:
        with pytest.raises(ValueError, match="bounded"):
            module.read_regular("large", directory)
    finally:
        os.close(directory)


def test_source_uses_commit_not_untracked_files_or_worktree_edits(tmp_path):
    root = SCRIPTS.parent
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--shared", str(root), str(clone)], check=True, capture_output=True)
    (clone / "server/pyproject.toml").write_text("worktree override")
    (clone / "server/not-from-git.py").write_text("untracked")
    files = module.source_files(clone, commit)
    expected = subprocess.check_output(["git", "-C", str(root), "show", f"{commit}:server/pyproject.toml"])
    assert files["server/pyproject.toml"][0] == expected
    assert "server/not-from-git.py" not in files
    assert not any("tests" in Path(name).parts or ".venv" in Path(name).parts for name in files)
    assert not any(name.startswith("ios/") or name.startswith("client/") for name in files)


def test_source_ignores_replace_refs_and_git_environment(tmp_path, monkeypatch):
    root = SCRIPTS.parent
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--shared", "--no-checkout", str(root), str(clone)],
                   check=True, capture_output=True)
    commit = subprocess.check_output(["git", "-C", str(clone), "rev-parse", "HEAD"], text=True).strip()
    original = subprocess.check_output(["git", "-C", str(clone), "rev-parse",
                                       f"{commit}:server/pyproject.toml"], text=True).strip()
    replacement = subprocess.check_output(["git", "-C", str(clone), "hash-object", "-w", "--stdin"],
                                          input=b"WRONG SOURCE").decode().strip()
    subprocess.run(["git", "-C", str(clone), "replace", original, replacement], check=True)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "not-a-repository"))
    files = module.source_files(clone, commit)
    assert b"WRONG SOURCE" not in files["server/pyproject.toml"][0]
    assert b"[project]" in files["server/pyproject.toml"][0]


@pytest.mark.parametrize("name", [".env", ".env.production", ".git", "data", ".venv"])
def test_frontend_protected_content_is_refused(tmp_path, name):
    (tmp_path / name).write_text("must not be shipped")
    with pytest.raises(ValueError, match="protected"):
        module.frontend_files(tmp_path)


@pytest.mark.parametrize("commit", ["main", "HEAD", "abc123", "a" * 39, "A" * 40])
def test_mutable_or_invalid_source_rejected(commit, tmp_path):
    with pytest.raises(ValueError, match="immutable"):
        module.source_files(tmp_path, commit)


def test_mismatched_frontend_rejected_before_build(tmp_path):
    with pytest.raises(ValueError, match="same commit"):
        module.build_bundle(tmp_path, "a" * 40, tmp_path, "b" * 40,
                            tmp_path, tmp_path, tmp_path / "out")


def test_existing_output_is_not_overwritten(tmp_path):
    marker = tmp_path / "keep"
    marker.write_bytes(b"original")
    with pytest.raises(ValueError, match="exists"):
        module.build_bundle(tmp_path, "a" * 40, tmp_path, "a" * 40,
                            tmp_path, tmp_path, tmp_path)
    assert marker.read_bytes() == b"original"


def test_complete_bundle_hashes_and_installed_updater_contract(tmp_path, monkeypatch):
    root = SCRIPTS.parent
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("frontend fixture")
    (dist / "assets/app.js").write_text("fixture")

    def wheels(_dir, _provenance, project, output, source, _epoch):
        assert source == commit
        assert project.read_bytes() == subprocess.check_output([
            "git", "-C", str(root), "show", f"{commit}:server/pyproject.toml"])
        paths = output / "wheels.zip", output / "python.lock"
        for path in paths:
            path.write_bytes(b"synthetic wheelhouse output; validated by separate wheelhouse tests")
        return paths

    monkeypatch.setattr(module, "build_wheelhouse", wheels)
    manifest_path = module.build_bundle(root, commit, dist, commit, tmp_path, tmp_path, tmp_path / "out")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["source_commit"] == commit
    assert manifest["qualification"] == {"evidence": []}
    assert {asset["role"] for asset in manifest["assets"]} == {"application", "wheelhouse", "python_lock"}
    for asset in manifest["assets"]:
        data = (manifest_path.parent / asset["filename"]).read_bytes()
        assert len(data) == asset["size_bytes"]
        assert hashlib.sha256(data).hexdigest() == asset["sha256"]

    # Execute only the installed updater's actual file validator, not the app.
    # This catches new root paths rejected BEFORE a future updater is installed.
    source = subprocess.check_output(["git", "-C", str(root), "show",
                                      f"{commit}:server/inky_web/services/updater.py"], text=True)
    tree = ast.parse(source)
    nodes = [node for node in tree.body if
             isinstance(node, ast.FunctionDef) and node.name == "_validate_payload" or
             isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
             t.id in {"_BACKUP_ITEMS", "_NEVER_OVERWRITE"} for t in node.targets)]
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "installed-updater-contract", "exec"), namespace)
    archive = next(manifest_path.parent.glob("*.tar.gz"))
    extracted = tmp_path / "extracted"
    with tarfile.open(archive) as tar:
        assert all(m.isfile() for m in tar)
        for member in tar:
            target = extracted / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
    namespace["_validate_payload"](extracted)
    assert (extracted / "server/SOURCE_COMMIT").read_text().strip() == commit


def test_failure_after_staging_cleans_partial_outputs(tmp_path, monkeypatch):
    root = SCRIPTS.parent
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("frontend")
    (dist / "assets/app.js").write_text("fixture")

    def fail_wheels(_wheels, _provenance, _project, output, _commit, _epoch):
        (output / "partial.zip").write_bytes(b"incomplete")
        raise ValueError("injected wheel validation failure")

    monkeypatch.setattr(module, "build_wheelhouse", fail_wheels)
    with pytest.raises(ValueError, match="injected"):
        module.build_bundle(root, commit, dist, commit, tmp_path, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".inky-offline-*"))
