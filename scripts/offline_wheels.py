"""Validate already acquired wheels and package an inert, target-specific wheelhouse.

No downloads, imports of wheel code, build hooks, installation or extraction occur.
Compatibility here means declared metadata/tags, not an ELF audit or a hardware test.
Only static build requirements are covered; declare editable-hook requirements in
pyproject.toml explicitly before calling this module.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import tomllib
import zipfile
import zlib
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.parser import Parser
from pathlib import Path
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import Tag, compatible_tags, cpython_tags, parse_tag
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

TARGET = {"architecture": "arm64", "python_version": "3.13.5", "debian_release": "trixie"}
TARGET_ENV = {
    "implementation_name": "cpython",
    "implementation_version": "3.13.5",
    "os_name": "posix",
    "platform_machine": "aarch64",
    "platform_python_implementation": "CPython",
    "platform_release": "",
    "platform_system": "Linux",
    "platform_version": "",
    "python_full_version": "3.13.5",
    "python_version": "3.13",
    "sys_platform": "linux",
}
PLATFORMS = ["linux_aarch64", "manylinux2014_aarch64"] + [
    f"manylinux_2_{minor}_aarch64" for minor in range(17, 42)
]
SUPPORTED_TAGS = frozenset(cpython_tags((3, 13), abis=["cp313"], platforms=PLATFORMS)) | frozenset(
    compatible_tags((3, 13), interpreter="cp313", platforms=PLATFORMS)
)
ZIP_NAME = "inky-studio-python-arm64-cp313.zip"
LOCK_NAME = "requirements-arm64-cp313.lock"
MAX_WHEELS = 256
MAX_WHEEL_BYTES = 128 * 1024 * 1024
MAX_TOTAL_WHEEL_BYTES = 512 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 20_000
MAX_TOTAL_MEMBERS = 100_000
MAX_METADATA_BYTES = 1024 * 1024
MAX_LICENSE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_LICENSE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
NOTICE = re.compile(r"(?:licen[cs]e|copying|copyright|notice)(?:[._-].*)?\Z", re.IGNORECASE)


class WheelhouseError(ValueError):
    """An input cannot be accepted into this offline candidate."""


@dataclass
class Wheel:
    filename: str
    name: str
    version: Version
    content: bytes
    inventory: dict
    requirements: list[Requirement]
    extras: set[str]
    notices: dict[str, bytes]
    license_info: dict
    member_count: int
    expanded_size: int


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise WheelhouseError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_regular(path: Path, maximum: int) -> bytes:
    """Snapshot regular file bytes without following a final symlink or blocking on a FIFO."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise WheelhouseError(f"Not a regular file: {path.name}")
            if before.st_size > maximum:
                raise WheelhouseError(f"File size limit exceeded: {path.name}")
            content = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            if len(content) > maximum or len(content) != before.st_size:
                raise WheelhouseError(f"File size changed or exceeds limit: {path.name}")
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns
            ):
                raise WheelhouseError(f"File changed while reading: {path.name}")
            return content
    except OSError as exc:
        raise WheelhouseError(f"Cannot read regular file {path.name}: {exc.strerror}") from exc


def _safe_path(name: str, *, directory: bool = False) -> str:
    if not isinstance(name, str) or not name or len(name) > 512:
        raise WheelhouseError("Unsafe ZIP path length")
    if "\\" in name or ":" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise WheelhouseError(f"Unsafe ZIP path: {name!r}")
    clean = name[:-1] if directory and name.endswith("/") else name
    parts = clean.split("/")
    if len(parts) > 32 or any(part in {"", ".", ".."} for part in parts):
        raise WheelhouseError(f"Unsafe ZIP path: {name!r}")
    return clean


def _digest(value: object, where: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise WheelhouseError(f"Invalid SHA256: {where}")
    return value


def _origin(origin: object, wheel_hash: str, filename: str) -> dict:
    if not isinstance(origin, dict) or origin.get("kind") not in {"pypi-wheel", "native-build"}:
        raise WheelhouseError(f"Invalid origin: {filename}")
    allowed = {"kind", "url", "sha256", "build_report_sha256"}
    if origin.keys() - allowed:
        raise WheelhouseError(f"Unknown origin fields: {filename}")
    url = origin.get("url")
    if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 for char in url):
        raise WheelhouseError(f"Invalid origin HTTPS URL: {filename}")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https" and parsed.hostname and parsed.path
            and parsed.username is None and parsed.password is None
            and parsed.port in {None, 443} and not parsed.query and not parsed.fragment
            and "\\" not in url
        )
    except ValueError as exc:
        raise WheelhouseError(f"Invalid origin HTTPS URL: {filename}") from exc
    if not valid:
        raise WheelhouseError(f"Origin requires credential-free HTTPS without query/fragment: {filename}")
    source_hash = _digest(origin.get("sha256"), f"{filename} origin")
    if origin["kind"] == "pypi-wheel" and source_hash != wheel_hash:
        raise WheelhouseError(f"PyPI origin hash differs from wheel hash: {filename}")
    if origin["kind"] == "native-build":
        _digest(origin.get("build_report_sha256"), f"{filename} build report")
    elif "build_report_sha256" in origin:
        _digest(origin["build_report_sha256"], f"{filename} build report")
    return dict(origin)


def _tags(tag_text: str) -> frozenset[Tag]:
    if len(tag_text) > 256:
        raise WheelhouseError("Wheel tag length limit exceeded")
    parts = tag_text.split("-")
    if len(parts) != 3:
        raise WheelhouseError(f"Invalid wheel tag: {tag_text}")
    combinations = 1
    for part in parts:
        combinations *= len(part.split("."))
    if combinations > 64:
        raise WheelhouseError("Wheel tag expansion limit exceeded")
    try:
        tags = parse_tag(tag_text)
    except ValueError as exc:
        raise WheelhouseError(f"Invalid wheel tag: {tag_text}") from exc
    if any(tag.platform not in {*PLATFORMS, "any"} or tag.abi.endswith("t") for tag in tags):
        raise WheelhouseError(f"Unsupported platform/ABI tag for ARM64 CPython 3.13: {tag_text}")
    return tags


def _headers(data: bytes, kind: str):
    if len(data) > MAX_METADATA_BYTES:
        raise WheelhouseError(f"{kind} size limit exceeded")
    try:
        message = Parser(policy=policy.default).parsestr(data.decode("utf-8"))
    except UnicodeError as exc:
        raise WheelhouseError(f"Invalid UTF-8 {kind}") from exc
    if message.defects:
        raise WheelhouseError(f"Malformed {kind} headers")
    return message


def _one_header(message, field: str, *, required: bool = True) -> str | None:
    values = message.get_all(field, [])
    if len(values) != 1 and (required or values):
        raise WheelhouseError(f"Expected one {field} metadata header")
    return str(values[0]).strip() if values else None


def _requirement(text: str, context: str) -> Requirement:
    if not isinstance(text, str) or len(text) > 8192:
        raise WheelhouseError(f"Invalid requirement: {context}")
    try:
        requirement = Requirement(text)
    except InvalidRequirement as exc:
        raise WheelhouseError(f"Invalid requirement {text!r}: {context}") from exc
    if requirement.url:
        raise WheelhouseError(f"URL dependency is forbidden: {context}: {requirement.name}")
    if requirement.marker:
        # These kernel-dependent values are deliberately not borrowed from the builder.
        variables = re.sub(r'"[^\"]*"', "", str(requirement.marker))
        if re.search(r"\b(platform_release|platform_version|extras|dependency_groups)\b", variables):
            raise WheelhouseError(f"Marker needs an unspecified target value: {context}: {text}")
    return requirement


def _python_compatible(value: str | None, context: str) -> None:
    if value is None:
        return
    try:
        valid = SpecifierSet(value).contains(TARGET["python_version"], prereleases=True)
    except InvalidSpecifier as exc:
        raise WheelhouseError(f"Invalid Requires-Python: {context}") from exc
    if not valid:
        raise WheelhouseError(f"Requires-Python excludes 3.13.5: {context}: {value}")


def _load_wheel(path: Path, entry: dict) -> Wheel:
    filename = path.name
    if len(filename) > 240 or not filename.endswith(".whl") or "/" in filename:
        raise WheelhouseError(f"Invalid wheel filename: {filename}")
    filename_tags = _tags("-".join(filename[:-4].split("-")[-3:]))
    if not filename_tags & SUPPORTED_TAGS:
        raise WheelhouseError(f"Incompatible tag for ARM64 CPython 3.13: {filename}")
    try:
        name, version, _, parsed_tags = parse_wheel_filename(filename)
    except (InvalidWheelFilename, InvalidVersion) as exc:
        raise WheelhouseError(f"Invalid wheel filename: {filename}") from exc
    if parsed_tags != filename_tags:
        raise WheelhouseError(f"Invalid filename tag set: {filename}")
    blob = _read_regular(path, MAX_WHEEL_BYTES)
    size = entry.get("size_bytes")
    if type(size) is not int or size != len(blob):
        raise WheelhouseError(f"Wheel size mismatch: {filename}")
    wheel_hash = _digest(entry.get("sha256"), filename)
    if hashlib.sha256(blob).hexdigest() != wheel_hash:
        raise WheelhouseError(f"Wheel SHA256 mismatch: {filename}")
    origin = _origin(entry.get("origin"), wheel_hash, filename)
    inventory = {"filename": filename, "size_bytes": size, "sha256": wheel_hash, "origin": origin}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_MEMBERS:
                raise WheelhouseError(f"ZIP member count limit: {filename}")
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise WheelhouseError(f"ZIP expanded size limit: {filename}")
            members = {}
            folded = set()
            for info in infos:
                clean = _safe_path(info.filename, directory=info.is_dir())
                if info.orig_filename != info.filename or clean.casefold() in folded:
                    raise WheelhouseError(f"Duplicate/ambiguous ZIP path: {filename}: {clean}")
                folded.add(clean.casefold())
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise WheelhouseError(f"ZIP symlink/special member: {filename}: {clean}")
                if (kind == stat.S_IFDIR and not info.is_dir()) or (
                    kind == stat.S_IFREG and info.is_dir()
                ):
                    raise WheelhouseError(f"Inconsistent ZIP member type: {clean}")
                if info.flag_bits & 1 or info.compress_type not in {
                    zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED
                }:
                    raise WheelhouseError(f"Unsupported ZIP encoding/encryption: {filename}")
                if info.is_dir() and info.file_size:
                    raise WheelhouseError(f"Nonempty ZIP directory: {clean}")
                if info.file_size > max(1, info.compress_size) * 1000:
                    raise WheelhouseError(f"ZIP compression ratio limit: {clean}")
                members[clean] = info
            for clean in members:
                parts = clean.split("/")
                for count in range(1, len(parts)):
                    parent = members.get("/".join(parts[:count]))
                    if parent and not parent.is_dir():
                        raise WheelhouseError(f"ZIP file/directory collision: {clean}")
            dist_infos = {key.split("/")[0] for key in members if key.split("/")[0].endswith(".dist-info")}
            if len(dist_infos) != 1:
                raise WheelhouseError(f"Expected one root dist-info directory: {filename}")
            dist_info = dist_infos.pop()
            try:
                info_name, info_version = dist_info[:-10].rsplit("-", 1)
                matches = canonicalize_name(info_name, validate=True) == name and Version(info_version) == version
            except ValueError as exc:
                raise WheelhouseError(f"Invalid dist-info name: {filename}") from exc
            if not matches:
                raise WheelhouseError(f"dist-info differs from filename: {filename}")
            metadata_path, wheel_path = f"{dist_info}/METADATA", f"{dist_info}/WHEEL"
            for required in (metadata_path, wheel_path, f"{dist_info}/RECORD"):
                if required not in members or members[required].is_dir():
                    raise WheelhouseError(f"Missing wheel metadata file: {required}")
            if any(members[p].file_size > MAX_METADATA_BYTES for p in (metadata_path, wheel_path)):
                raise WheelhouseError(f"Wheel metadata size limit: {filename}")
            metadata = _headers(archive.read(members[metadata_path]), "METADATA")
            try:
                matches = canonicalize_name(_one_header(metadata, "Name"), validate=True) == name and Version(
                    _one_header(metadata, "Version")
                ) == version
            except ValueError as exc:
                raise WheelhouseError(f"Invalid METADATA identity: {filename}") from exc
            if not matches:
                raise WheelhouseError(f"METADATA Name/Version differs from filename: {filename}")
            _python_compatible(_one_header(metadata, "Requires-Python", required=False), filename)
            wheel_metadata = _headers(archive.read(members[wheel_path]), "WHEEL")
            if _one_header(wheel_metadata, "Wheel-Version") != "1.0":
                raise WheelhouseError(f"Unsupported Wheel-Version: {filename}")
            if _one_header(wheel_metadata, "Root-Is-Purelib").lower() not in {"true", "false"}:
                raise WheelhouseError(f"Invalid Root-Is-Purelib: {filename}")
            wheel_tags = frozenset().union(*[
                _tags(str(value).strip()) for value in wheel_metadata.get_all("Tag", [])
            ])
            if wheel_tags != filename_tags:
                raise WheelhouseError(f"WHEEL tags differ from filename: {filename}")
            requirements = [_requirement(str(value), filename) for value in metadata.get_all("Requires-Dist", [])]
            try:
                extras = {canonicalize_name(str(value).strip(), validate=True) for value in metadata.get_all("Provides-Extra", [])}
            except ValueError as exc:
                raise WheelhouseError(f"Invalid Provides-Extra: {filename}") from exc
            declared = [str(value).strip() for value in metadata.get_all("License-File", [])]
            declared_paths = {}
            for relative in declared:
                _safe_path(relative)
                candidates = (f"{dist_info}/licenses/{relative}", f"{dist_info}/{relative}")
                declared_paths[relative] = next((key for key in candidates if key in members and not members[key].is_dir()), None)
            notice_paths = {
                key for key, info in members.items() if not info.is_dir() and (
                    key.startswith(f"{dist_info}/licenses/")
                    or NOTICE.fullmatch(key.rsplit("/", 1)[-1])
                    or key in declared_paths.values()
                )
            }
            if any(members[key].file_size > MAX_LICENSE_BYTES for key in notice_paths):
                raise WheelhouseError(f"License file size limit: {filename}")
            if sum(members[key].file_size for key in notice_paths) > MAX_TOTAL_LICENSE_BYTES:
                raise WheelhouseError(f"License total size limit: {filename}")
            notices = {}
            # Read every member in bounded chunks: validates CRC and corrupt/overlapping
            # streams without extracting or importing anything from the wheel.
            for key, info in members.items():
                if info.is_dir():
                    continue
                chunks, actual = [], 0
                with archive.open(info) as stream:
                    while chunk := stream.read(64 * 1024):
                        actual += len(chunk)
                        if actual > info.file_size or actual > MAX_UNCOMPRESSED_BYTES:
                            raise WheelhouseError(f"ZIP expanded size mismatch: {key}")
                        if key in notice_paths:
                            chunks.append(chunk)
                if actual != info.file_size:
                    raise WheelhouseError(f"ZIP expanded size mismatch: {key}")
                if key in notice_paths:
                    notices[key] = b"".join(chunks)
            license_info = {
                "name": str(name), "version": str(version), "wheel": filename,
                "license_expression": _one_header(metadata, "License-Expression", required=False),
                "license_metadata": _one_header(metadata, "License", required=False),
                "declared_license_files": declared,
                "missing_declared_license_files": sorted(key for key, value in declared_paths.items() if value is None),
                "no_notice_files_found": not bool(notices),
            }
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError, NotImplementedError, zlib.error) as exc:
        raise WheelhouseError(f"Invalid wheel ZIP: {filename}: {exc}") from exc
    return Wheel(filename, str(name), version, blob, inventory, requirements, extras, notices,
                 license_info, len(infos), total_size)


def _requirement_list(values: object, context: str) -> list[Requirement]:
    if not isinstance(values, list) or len(values) > 1024:
        raise WheelhouseError(f"Expected bounded requirement list: {context}")
    return [_requirement(value, context) for value in values]


def _active(requirement: Requirement, extras: set[str]) -> bool:
    if requirement.marker is None:
        return True
    try:
        # Extras extend the base dependency set; always evaluate the base context
        # as well as each explicitly requested extra.
        return any(requirement.marker.evaluate({**TARGET_ENV, "extra": extra}) for extra in {"", *extras})
    except (ValueError, KeyError) as exc:
        raise WheelhouseError(f"Cannot evaluate target marker: {requirement}") from exc


def _closure(roots: list[Requirement], wheels: dict[str, Wheel], root_extras: set[str]) -> set[str]:
    queue = deque((requirement, "pyproject", root_extras) for requirement in roots)
    activated: dict[str, set[str]] = {}
    while queue:
        requirement, parent, contexts = queue.popleft()
        if not _active(requirement, contexts):
            continue
        name = str(canonicalize_name(requirement.name))
        wheel = wheels.get(name)
        if wheel is None:
            raise WheelhouseError(f"Missing transitive/root dependency: {parent} requires {requirement}")
        if not requirement.specifier.contains(wheel.version, prereleases=True):
            raise WheelhouseError(f"Dependency version mismatch: {parent} requires {requirement}; found {wheel.version}")
        requested = {str(canonicalize_name(extra)) for extra in requirement.extras}
        if requested - wheel.extras:
            raise WheelhouseError(f"Unknown requested extras for {name}: {sorted(requested - wheel.extras)}")
        if name not in activated or requested - activated[name]:
            activated.setdefault(name, set()).update(requested)
            queue.extend((dependency, name, activated[name].copy()) for dependency in wheel.requirements)
    return set(activated)


def _zip_write(archive: zipfile.ZipFile, name: str, content: bytes, timestamp: tuple) -> None:
    info = zipfile.ZipInfo(name, timestamp)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_STORED
    archive.writestr(info, content)


def build_wheelhouse(
    wheel_dir: Path, provenance_path: Path, pyproject_path: Path, output_dir: Path,
    source_commit: str, epoch: int,
) -> tuple[Path, Path]:
    """Create deterministic ZIP + hashed lock for a complete, preselected wheel set.

    Existing output files are never overwritten. Origins are asserted input
    provenance, not authenticated remote statements. Native build report hashes
    are carried through but the reports/ELF/runtime are not qualified here.
    """
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise WheelhouseError("source_commit must be a full lowercase Git SHA1")
    if type(epoch) is not int or not 0 <= epoch <= 4_354_819_198:
        raise WheelhouseError("epoch must be a nonnegative timestamp representable in ZIP")
    dt = datetime.fromtimestamp(max(epoch, 315_532_800), UTC)
    timestamp = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second // 2 * 2)
    if wheel_dir.is_symlink() or not wheel_dir.is_dir():
        raise WheelhouseError("wheel_dir must be a real directory")
    raw_provenance = _read_regular(provenance_path, MAX_JSON_BYTES)
    try:
        provenance = json.loads(raw_provenance, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WheelhouseError("Invalid provenance JSON") from exc
    if not isinstance(provenance, dict) or type(provenance.get("schema_version")) is not int or provenance["schema_version"] != 1:
        raise WheelhouseError("Expected provenance schema_version 1")
    if provenance.get("target") != TARGET:
        raise WheelhouseError("Provenance target must be ARM64 / CPython 3.13.5 / Trixie")
    if "source_commit" in provenance and provenance["source_commit"] != source_commit:
        raise WheelhouseError("Provenance source_commit differs from the requested source")
    entries = provenance.get("wheels")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_WHEELS:
        raise WheelhouseError("Expected a nonempty bounded wheels inventory")
    by_filename = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str):
            raise WheelhouseError("Invalid wheel inventory entry")
        filename = _safe_path(entry["filename"])
        if "/" in filename or filename in by_filename:
            raise WheelhouseError("Wheel inventory filenames must be unique basenames")
        by_filename[filename] = entry
    if {path.name for path in wheel_dir.iterdir()} != set(by_filename):
        raise WheelhouseError("Wheel directory contains missing/uninventoried files")
    wheels: dict[str, Wheel] = {}
    total_size = expanded_size = members = license_size = 0
    for filename, entry in sorted(by_filename.items()):
        # Check aggregate sizes before retaining the next bounded snapshot.
        declared_size = entry.get("size_bytes")
        if type(declared_size) is not int or declared_size < 0 or declared_size > MAX_WHEEL_BYTES:
            raise WheelhouseError(f"Invalid inventory size: {filename}")
        total_size += declared_size
        if total_size > MAX_TOTAL_WHEEL_BYTES:
            raise WheelhouseError("Total wheel size limit exceeded")
        wheel = _load_wheel(wheel_dir / filename, entry)
        if wheel.name in wheels:
            raise WheelhouseError(f"Multiple wheels/versions for one distribution: {wheel.name}")
        expanded_size += wheel.expanded_size
        members += wheel.member_count
        license_size += sum(len(content) for content in wheel.notices.values())
        if expanded_size > MAX_TOTAL_UNCOMPRESSED_BYTES or members > MAX_TOTAL_MEMBERS or license_size > MAX_TOTAL_LICENSE_BYTES:
            raise WheelhouseError("Aggregate ZIP/notice limit exceeded")
        wheels[wheel.name] = wheel
    raw_project = _read_regular(pyproject_path, MAX_METADATA_BYTES)
    try:
        project_file = tomllib.loads(raw_project.decode("utf-8"))
        project = project_file["project"]
        if {"dependencies", "optional-dependencies"} & set(project.get("dynamic", [])):
            raise WheelhouseError("Dynamic project dependencies cannot be validated inertly")
        _python_compatible(project.get("requires-python"), "pyproject")
        roots = _requirement_list(project["dependencies"], "project.dependencies")
        roots += _requirement_list(project.get("optional-dependencies", {}).get("pi", []), "project.optional-dependencies.pi")
        build_roots = _requirement_list(project_file["build-system"]["requires"], "build-system.requires")
    except (UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise WheelhouseError("Invalid static pyproject dependencies/build-system") from exc
    roles = {"runtime": _closure(roots, wheels, {"pi"}), "build": _closure(build_roots, wheels, set())}
    unused = wheels.keys() - roles["runtime"] - roles["build"]
    if unused:
        raise WheelhouseError(f"Wheels outside the declared dependency closure: {', '.join(sorted(unused))}")
    payloads = {}
    license_index = []
    final_inventory = []
    lock_lines = [
        "# Inky Studio: ARM64, CPython 3.13.5, Debian Trixie (glibc <= 2.41).",
        f"# Application source commit: {source_commit}",
        "# Exact runtime + Pi + static build dependencies; install using --no-index --require-hashes.",
        "# Dynamic build hooks and native runtime compatibility are not qualified by this lock.",
    ]
    for name, wheel in sorted(wheels.items()):
        wheel_roles = sorted(role for role, closure in roles.items() if name in closure)
        final_inventory.append({**wheel.inventory, "name": name, "version": str(wheel.version), "roles": wheel_roles})
        payloads[wheel.filename] = wheel.content
        notice_entries = []
        for original, content in sorted(wheel.notices.items()):
            destination = f"licenses/{name}-{wheel.version}/{original}"
            payloads[destination] = content
            notice_entries.append({"wheel_path": original, "path": destination,
                                   "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        license_index.append({**wheel.license_info, "files": notice_entries})
        lock_lines.append(f"{name}=={wheel.version} --hash=sha256:{wheel.inventory['sha256']}")
    payloads["licenses/index.json"] = _json_bytes({
        "schema_version": 1,
        "scope": "Collected wheel notices and explicit omissions; not a legal compliance determination.",
        "distributions": license_index,
    })
    payloads["provenance.json"] = _json_bytes({
        "schema_version": 1, "target": TARGET, "source_commit": source_commit, "source_date_epoch": epoch,
        "input_provenance_sha256": hashlib.sha256(raw_provenance).hexdigest(),
        "pyproject_sha256": hashlib.sha256(raw_project).hexdigest(),
        "wheels": final_inventory, "licenses_index": "licenses/index.json",
        "qualification": {"metadata_closure_validated": True, "native_runtime_qualified": False,
                          "dynamic_build_hooks_executed": False, "external_provenance_authenticated": False},
    })
    if output_dir.is_symlink():
        raise WheelhouseError("Output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path, lock_path = output_dir / ZIP_NAME, output_dir / LOCK_NAME
    if any(path.exists() or path.is_symlink() for path in (zip_path, lock_path)):
        raise WheelhouseError("Wheelhouse output already exists; refusing to overwrite")
    created = []
    try:
        with tempfile.TemporaryDirectory(prefix=".offline-wheels-", dir=output_dir) as temporary:
            zip_temp, lock_temp = Path(temporary) / ZIP_NAME, Path(temporary) / LOCK_NAME
            with zipfile.ZipFile(zip_temp, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, content in sorted(payloads.items()):
                    _zip_write(archive, name, content, timestamp)
            lock_temp.write_text("\n".join(lock_lines) + "\n", encoding="utf-8")
            for temporary_path, final in ((zip_temp, zip_path), (lock_temp, lock_path)):
                temporary_path.chmod(0o644)
                os.utime(temporary_path, (epoch, epoch))
                os.link(temporary_path, final)  # Atomic creation, never follows/overwrites a destination.
                created.append(final)
    except OSError as exc:
        for path in created:
            path.unlink()
        raise WheelhouseError(f"Cannot create wheelhouse outputs: {exc.strerror}") from exc
    return zip_path, lock_path
