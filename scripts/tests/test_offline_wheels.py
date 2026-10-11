"""Synthetic, inert wheel fixtures: never import a package from a wheel."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "offline_wheels.py"
SPEC = importlib.util.spec_from_file_location("offline_wheels", SCRIPT)
offline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = offline
SPEC.loader.exec_module(offline)

COMMIT = "a" * 40
EPOCH = 1_790_531_200


def wheel_bytes(name="example", version="1.0", *, tags="py3-none-any", requires=(), extras=(),
                python=">=3.8", metadata_name=None, metadata_version=None, files=(),
                license_files=(), license_text=None, wheel_tags=None):
    distribution = name.replace("-", "_").replace(".", "_")
    info = f"{distribution}-{version}.dist-info"
    metadata = ["Metadata-Version: 2.4", f"Name: {metadata_name or name}",
                f"Version: {metadata_version or version}", f"Requires-Python: {python}"]
    metadata.extend(f"Requires-Dist: {value}" for value in requires)
    metadata.extend(f"Provides-Extra: {value}" for value in extras)
    metadata.extend(f"License-File: {value}" for value in license_files)
    wheel = "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n"
    wheel += "".join(f"Tag: {tag}\n" for tag in (wheel_tags or [tags]))
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(f"{info}/METADATA", "\n".join(metadata) + "\n\n")
        archive.writestr(f"{info}/WHEEL", wheel + "\n")
        archive.writestr(f"{info}/RECORD", "")
        # If imported by the implementation this would fail, making its inertness visible.
        archive.writestr(f"{distribution}/__init__.py", "raise RuntimeError('do not import wheels')\n")
        if license_text is not None:
            archive.writestr(f"{info}/licenses/LICENSE", license_text)
        for member, data in files:
            archive.writestr(member, data)
    return f"{distribution}-{version}-{tags}.whl", content.getvalue()


class Fixture:
    def __init__(self, root):
        self.root = root
        self.directory = root / "wheels"
        self.directory.mkdir()
        self.provenance = root / "provenance.json"
        self.project = root / "pyproject.toml"
        self.inventory = []
        self.project_roots(["example"])

    def project_roots(self, runtime, *, pi=(), build=()):
        self.project.write_text(
            '[project]\nname="test-app"\nversion="1.0"\nrequires-python=">=3.11"\n'
            f"dependencies={json.dumps(runtime)}\n"
            f"[project.optional-dependencies]\npi={json.dumps(list(pi))}\n"
            f"[build-system]\nrequires={json.dumps(list(build))}\nbuild-backend=\"example\"\n"
        )

    def add(self, *args, **kwargs):
        filename, blob = wheel_bytes(*args, **kwargs)
        (self.directory / filename).write_bytes(blob)
        digest = hashlib.sha256(blob).hexdigest()
        entry = {"filename": filename, "size_bytes": len(blob), "sha256": digest,
                 "origin": {"kind": "pypi-wheel", "url": f"https://files.pythonhosted.org/{filename}", "sha256": digest}}
        self.inventory.append(entry)
        return entry

    def write_provenance(self):
        self.provenance.write_text(json.dumps({"schema_version": 1, "target": offline.TARGET, "wheels": self.inventory}))

    def build(self, name="output"):
        self.write_provenance()
        return offline.build_wheelhouse(self.directory, self.provenance, self.project,
                                       self.root / name, COMMIT, EPOCH)


@pytest.fixture
def fixture(tmp_path):
    return Fixture(tmp_path)


def test_complete_runtime_pi_build_closure_notices_and_reproducibility(fixture):
    fixture.project_roots(["example[photos]>=1"], pi=["board"], build=["builder", "editable"])
    first = fixture.add(requires=["image>=2; extra == 'photos'", "unixdep; sys_platform == 'linux'",
                                  "windowsdep; sys_platform == 'win32'"], extras=["photos"],
                        license_files=["LICENSE", "MISSING"], license_text="Example MIT notice")
    fixture.add("image", "2.1")
    fixture.add("board", tags="cp313-cp313-linux_aarch64")
    fixture.add("unixdep", tags="cp39-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64")
    fixture.add("builder", requires=["unixdep"])
    fixture.add("editable")
    one_zip, one_lock = fixture.build()
    other_zip, other_lock = fixture.build("output2")
    assert one_zip.read_bytes() == other_zip.read_bytes()
    assert one_lock.read_bytes() == other_lock.read_bytes()
    assert one_zip.name == "inky-studio-python-arm64-cp313.zip"
    assert one_lock.name == "requirements-arm64-cp313.lock"
    with zipfile.ZipFile(one_zip) as archive:
        provenance = json.loads(archive.read("provenance.json"))
        assert provenance["source_commit"] == COMMIT
        assert provenance["target"] == offline.TARGET
        selected = next(item for item in provenance["wheels"] if item["name"] == "example")
        assert selected["origin"] == first["origin"]
        assert selected["roles"] == ["runtime"]
        assert next(item for item in provenance["wheels"] if item["name"] == "unixdep")["roles"] == ["build", "runtime"]
        index = json.loads(archive.read("licenses/index.json"))
        example = next(item for item in index["distributions"] if item["name"] == "example")
        assert example["missing_declared_license_files"] == ["MISSING"]
        assert example["no_notice_files_found"] is False
        assert archive.read(example["files"][0]["path"]) == b"Example MIT notice"
        assert next(item for item in index["distributions"] if item["name"] == "board")["no_notice_files_found"] is True
        assert archive.read(first["filename"]) == (fixture.directory / first["filename"]).read_bytes()
        assert archive.testzip() is None
    requirements = [line for line in one_lock.read_text().splitlines() if not line.startswith("#")]
    assert len(requirements) == 6
    assert f"example==1.0 --hash=sha256:{first['sha256']}" in requirements


@pytest.mark.parametrize("tag", [
    "cp313-cp313-manylinux_2_42_aarch64", "cp313-cp313-manylinux_2_17_x86_64",
    "cp313-cp313-musllinux_1_2_aarch64", "cp313-cp313t-linux_aarch64",
    "cp314-cp314-linux_aarch64", "cp312-cp312-linux_aarch64", "py2-none-any",
    "cp313-abi3t-linux_aarch64", "cp313-cp313-macosx_11_0_arm64",
])
def test_incompatible_target_tags_are_rejected(fixture, tag):
    fixture.add(tags=tag)
    with pytest.raises(offline.WheelhouseError, match="tag"):
        fixture.build()


@pytest.mark.parametrize("tags", ["cp313-cp313-manylinux_2_41_aarch64", "cp37-abi3-manylinux_2_17_aarch64",
                                  "cp313-cp313-linux_aarch64", "py3-none-any"])
def test_target_tags_are_accepted(fixture, tags):
    fixture.add(tags=tags)
    fixture.build()


def test_universal_wheel_separate_tag_headers(fixture):
    fixture.add(tags="py2.py3-none-any", wheel_tags=["py2-none-any", "py3-none-any"])
    fixture.build()


@pytest.mark.parametrize("changes,match", [
    ({"metadata_name": "different"}, "Name/Version"),
    ({"metadata_version": "9.0"}, "Name/Version"),
    ({"python": "<3.13"}, "Requires-Python"),
    ({"wheel_tags": ["cp313-cp313-linux_aarch64"]}, "WHEEL tags"),
])
def test_metadata_must_match_target_and_filename(fixture, changes, match):
    fixture.add(**changes)
    with pytest.raises(offline.WheelhouseError, match=match):
        fixture.build()


@pytest.mark.parametrize("field,value,match", [("sha256", "0" * 64, "SHA256 mismatch"),
                                               ("size_bytes", 1, "size mismatch")])
def test_exact_inventory_hash_and_size(fixture, field, value, match):
    fixture.add()[field] = value
    with pytest.raises(offline.WheelhouseError, match=match):
        fixture.build()


def test_directory_and_provenance_must_have_exact_same_files(fixture):
    fixture.add()
    (fixture.directory / "unlisted.whl").write_bytes(b"extra")
    with pytest.raises(offline.WheelhouseError, match="uninventoried"):
        fixture.build()


def test_two_versions_of_distribution_rejected(fixture):
    fixture.add()
    fixture.add(version="2.0")
    with pytest.raises(offline.WheelhouseError, match="Multiple wheels/versions"):
        fixture.build()


def test_missing_transitive_dependency_rejected(fixture):
    fixture.add(requires=["missing>=2"])
    with pytest.raises(offline.WheelhouseError, match="example requires missing"):
        fixture.build()


def test_conflicting_transitive_version_rejected(fixture):
    fixture.add(requires=["dependency>=2", "dependency<2"])
    fixture.add("dependency", "2.1")
    with pytest.raises(offline.WheelhouseError, match="version mismatch"):
        fixture.build()


def test_markers_use_fixed_target_and_extra_transitive_closure(fixture):
    fixture.project_roots(["example[standard]", "another"])
    fixture.add(extras=["standard", "photos"], requires=[
        "image; extra == 'photos'", "network[tls]; extra == 'standard'",
        "not-on-mac; sys_platform == 'darwin'", "not-python312; python_version < '3.13'",
        "linux-arm; platform_machine == 'aarch64' and python_full_version == '3.13.5'",
    ])
    fixture.add("another", requires=["example[photos]"])
    fixture.add("image")
    fixture.add("network", extras=["tls"], requires=["crypto; extra == 'tls'"])
    fixture.add("crypto")
    fixture.add("linux-arm")
    fixture.build()


def test_unknown_extra_rejected(fixture):
    fixture.project_roots(["example[nonexistent]"])
    fixture.add()
    with pytest.raises(offline.WheelhouseError, match="Unknown requested extras"):
        fixture.build()


def test_unprovided_kernel_marker_rejected(fixture):
    fixture.add(requires=["other; platform_release > '5'"])
    with pytest.raises(offline.WheelhouseError, match="unspecified target value"):
        fixture.build()


def test_unreachable_wheel_rejected(fixture):
    fixture.add()
    fixture.add("unused")
    with pytest.raises(offline.WheelhouseError, match="outside the declared dependency closure"):
        fixture.build()


@pytest.mark.parametrize("location", ["root", "inactive-transitive"])
def test_direct_dependency_urls_rejected_even_inactive(fixture, location):
    direct = "other @ https://example.org/a.whl ; sys_platform == 'win32'"
    if location == "root":
        fixture.project_roots(["example", direct])
        fixture.add()
    else:
        fixture.add(requires=[direct])
    with pytest.raises(offline.WheelhouseError, match="URL dependency"):
        fixture.build()


@pytest.mark.parametrize("url", ["http://example.org/a.whl", "https://user:secret@example.org/a.whl",
                                 "https://example.org/a.whl?token=secret", "https://example.org/a.whl#frag",
                                 "https://example.org\\@other.org/a.whl"])
def test_origins_require_credential_free_https(fixture, url):
    fixture.add()["origin"]["url"] = url
    with pytest.raises(offline.WheelhouseError, match="HTTPS"):
        fixture.build()


def test_native_source_and_build_report_hashes_preserved(fixture):
    entry = fixture.add(tags="cp313-cp313-linux_aarch64")
    entry["origin"] = {"kind": "native-build", "url": "https://files.pythonhosted.org/source.tar.gz",
                       "sha256": "b" * 64, "build_report_sha256": "c" * 64}
    archive_path, _ = fixture.build()
    with zipfile.ZipFile(archive_path) as archive:
        assert json.loads(archive.read("provenance.json"))["wheels"][0]["origin"] == entry["origin"]


def test_native_build_without_report_hash_rejected(fixture):
    entry = fixture.add()
    entry["origin"]["kind"] = "native-build"
    with pytest.raises(offline.WheelhouseError, match="build report"):
        fixture.build()


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../../escape", "a\\escape", "C:/file",
                                   "a//file", "./file", "a/./file", "bad\x01file"])
def test_unsafe_zip_member_names_rejected(fixture, path):
    fixture.add(files=[(path, "payload")])
    with pytest.raises(offline.WheelhouseError, match="Unsafe ZIP path"):
        fixture.build()


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK])
def test_zip_special_files_rejected(fixture, kind):
    member = zipfile.ZipInfo("unsafe")
    member.create_system = 3
    member.external_attr = (kind | 0o644) << 16
    fixture.add(files=[(member, "destination")])
    with pytest.raises(offline.WheelhouseError, match="symlink/special"):
        fixture.build()


def test_ambiguous_zip_case_names_rejected(fixture):
    fixture.add(files=[("package/ONE", "first"), ("package/one", "second")])
    with pytest.raises(offline.WheelhouseError, match="ambiguous ZIP"):
        fixture.build()


def test_zip_file_directory_collision_rejected(fixture):
    fixture.add(files=[("package/file", "first"), ("package/file/nested", "second")])
    with pytest.raises(offline.WheelhouseError, match="file/directory collision"):
        fixture.build()


def test_wheel_symlink_rejected(fixture):
    entry = fixture.add()
    wheel = fixture.directory / entry["filename"]
    outside = fixture.root / "original.whl"
    wheel.rename(outside)
    wheel.symlink_to(outside)
    with pytest.raises(offline.WheelhouseError, match="regular file"):
        fixture.build()


def test_wheel_fifo_does_not_block(fixture):
    entry = fixture.add()
    wheel = fixture.directory / entry["filename"]
    wheel.unlink()
    os.mkfifo(wheel)
    with pytest.raises(offline.WheelhouseError, match="regular file"):
        fixture.build()


def test_size_limits_apply_before_output_creation(fixture, monkeypatch):
    fixture.add()
    monkeypatch.setattr(offline, "MAX_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(offline.WheelhouseError, match="expanded size limit"):
        fixture.build()
    assert not (fixture.root / "output").exists()


def test_license_limit_is_enforced(fixture, monkeypatch):
    fixture.add(license_text="Too many bytes")
    monkeypatch.setattr(offline, "MAX_LICENSE_BYTES", 1)
    with pytest.raises(offline.WheelhouseError, match="License file size"):
        fixture.build()


def test_existing_outputs_are_never_overwritten(fixture):
    fixture.add()
    archive, lock = fixture.build()
    before = archive.read_bytes(), lock.read_bytes()
    with pytest.raises(offline.WheelhouseError, match="refusing to overwrite"):
        fixture.build()
    assert before == (archive.read_bytes(), lock.read_bytes())


def test_provenance_duplicate_keys_and_mismatched_source_rejected(fixture):
    fixture.add()
    fixture.write_provenance()
    value = fixture.provenance.read_text()
    fixture.provenance.write_text(value.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    with pytest.raises(offline.WheelhouseError, match="Duplicate JSON"):
        offline.build_wheelhouse(fixture.directory, fixture.provenance, fixture.project, fixture.root / "output", COMMIT, EPOCH)
    value = json.loads(value)
    value["source_commit"] = "b" * 40
    fixture.provenance.write_text(json.dumps(value))
    with pytest.raises(offline.WheelhouseError, match="source_commit differs"):
        offline.build_wheelhouse(fixture.directory, fixture.provenance, fixture.project, fixture.root / "output", COMMIT, EPOCH)
