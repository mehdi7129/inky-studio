"""In-memory format and real isolated CLI tests; no Linux publisher is exercised."""
from __future__ import annotations

import builtins
import json
import os
import pty
import select
import socket
import stat
import subprocess
import sys
import sysconfig
import venv
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from inky_web import auth
from inky_web.provisioning import factory_credentials as emitter
from inky_web.provisioning import factory_runtime as guard
from inky_web.provisioning.ownership import credential_epoch

MODULE = "inky_web.provisioning.factory_credentials"
USAGE = b"factory_credentials_usage\n"
FAILED = b"factory_credentials_failed\n"


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    # Override the shared fixture: it creates legacy DB/photos before every
    # test, which would hide an accidental emitter side effect.
    state = tmp_path / "must-not-be-created"
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(state))
    monkeypatch.setenv("INKY_STUDIO_PASSWORD", "synthetic-env-secret-must-be-ignored")
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "1")
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "invalid-and-ignored")
    return state


@pytest.fixture(scope="module")
def isolated_python(tmp_path_factory):
    # -I ignores PYTHONPATH. Use a private temporary installation, leaving the
    # shared development venv untouched. This is not the Linux image layout.
    root = tmp_path_factory.mktemp("credential-emitter-install")
    venv.EnvBuilder(with_pip=False, symlinks=True).create(root)
    site = root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    sources = Path(__file__).resolve().parents[1]
    (site / "test-install.pth").write_text(
        f"{sources}\n{sysconfig.get_path('purelib')}\n", encoding="utf-8",
    )
    return root / "bin" / "python"


def invoke(python, cwd, *, stdout=subprocess.PIPE, args=("--emit-v2",)):
    return subprocess.run(
        [str(python), "-I", "-B", "-m", MODULE, *args],
        stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.PIPE,
        cwd=cwd, timeout=20, check=False,
    )


def assert_record(payload, monkeypatch):
    assert 0 < len(payload) <= emitter.MAX_OUTPUT_BYTES == guard.MAX_CREDENTIAL_BYTES
    assert payload.isascii() and payload.endswith(b"\n") and payload.count(b"\n") == 1
    record = json.loads(payload)
    assert payload == json.dumps(record, separators=(",", ":")).encode("ascii") + b"\n"
    assert set(record) == {"version", "algorithm", "n", "r", "p", "salt", "hash", "bootstrap_password"}
    password = record["bootstrap_password"]
    assert len(password) == 16 and all(char in auth.PASSWORD_ALPHABET for char in password)
    credentials = auth._parse_record(Path("/synthetic/credentials.json"), record)
    assert len(credentials.salt) == 16 and credentials.verify(password)
    assert not credentials.verify(password + "wrong")
    # Exercise the existing *strict* guard validator on the actual output.
    # Only file/installed-policy access is replaced; no fake record parser.
    config = guard.FactoryRuntimeConfig(Path("/var/lib/inky-studio"), 1000)
    with monkeypatch.context() as patch:
        patch.setattr(guard, "select_runtime", lambda _: config)
        patch.setattr(guard, "_directory", lambda *_, **__: nullcontext(123))
        patch.setattr(guard, "_read_file", lambda *_, **__: payload)
        assert guard._verified_epoch(config) == credential_epoch(credentials.salt, credentials.digest)
    return record


def test_real_isolated_pipe_yields_independent_guard_compatible_records(
    isolated_python, tmp_path, inky_env, monkeypatch,
):
    first = invoke(isolated_python, tmp_path)
    second = invoke(isolated_python, tmp_path)
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    records = [assert_record(result.stdout, monkeypatch) for result in (first, second)]
    for field in ("bootstrap_password", "salt", "hash"):
        assert records[0][field] != records[1][field]
    assert not inky_env.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [(), ("--help",), ("--emit-v2", "extra"), ("synthetic-secret",)])
def test_real_bad_arguments_have_only_fixed_diagnostics(isolated_python, tmp_path, args):
    result = invoke(isolated_python, tmp_path, args=args)
    assert result.returncode == 64
    assert result.stdout == b"" and result.stderr == USAGE
    assert list(tmp_path.iterdir()) == []


def test_real_regular_file_is_refused_without_emission(isolated_python, tmp_path, inky_env):
    destination = tmp_path / "rejected-output"
    with destination.open("wb") as stream:
        result = invoke(isolated_python, tmp_path, stdout=stream)
    assert result.returncode == 64 and result.stderr == USAGE
    assert destination.read_bytes() == b"" and not inky_env.exists()


def test_real_tty_is_refused_without_emission(isolated_python, tmp_path):
    master, slave = pty.openpty()
    try:
        result = invoke(isolated_python, tmp_path, stdout=slave)
        assert result.returncode == 64 and result.stderr == USAGE
        # Keep the slave open so select distinguishes empty output from hangup.
        assert select.select([master], [], [], 0)[0] == []
    finally:
        os.close(master)
        os.close(slave)


def test_real_socket_is_refused_without_emission(isolated_python, tmp_path):
    reader, writer = socket.socketpair()
    try:
        result = invoke(isolated_python, tmp_path, stdout=writer)
        writer.close()
        reader.settimeout(1)
        assert result.returncode == 64 and result.stderr == USAGE
        assert reader.recv(1) == b""
    finally:
        reader.close()
        writer.close()


def test_real_closed_pipe_exits_70_without_traceback(isolated_python, tmp_path):
    reader, writer = os.pipe()
    os.close(reader)
    try:
        result = invoke(isolated_python, tmp_path, stdout=writer)
        assert result.returncode == 70 and result.stderr == FAILED
    finally:
        os.close(writer)


@pytest.fixture
def private_pipe(monkeypatch):
    writes = {1: bytearray(), 2: bytearray()}
    monkeypatch.setattr(sys, "argv", [MODULE, "--emit-v2"])
    monkeypatch.setattr(os, "fstat", lambda _: SimpleNamespace(st_mode=stat.S_IFIFO))

    def write(fd, value):
        writes[fd].extend(value)
        return len(value)

    monkeypatch.setattr(os, "write", write)
    return writes


@pytest.mark.parametrize("mode", [stat.S_IFREG, stat.S_IFCHR, stat.S_IFSOCK, stat.S_IFDIR])
def test_invalid_stdout_refused_before_generation(private_pipe, monkeypatch, mode):
    monkeypatch.setattr(os, "fstat", lambda _: SimpleNamespace(st_mode=mode))
    monkeypatch.setattr(emitter, "emit_v2", lambda: pytest.fail("Generation before pipe validation"))
    assert emitter.main() == 64
    assert private_pipe == {1: b"", 2: USAGE}


def test_invalid_fd_refused_before_generation(private_pipe, monkeypatch):
    def invalid(_):
        raise OSError("synthetic-secret")

    monkeypatch.setattr(os, "fstat", invalid)
    monkeypatch.setattr(emitter, "emit_v2", lambda: pytest.fail("Generation before pipe validation"))
    assert emitter.main() == 64
    assert private_pipe == {1: b"", 2: USAGE}


def test_bad_arguments_refused_before_generation(private_pipe, monkeypatch):
    monkeypatch.setattr(sys, "argv", [MODULE, "--emit-v2", "synthetic-secret"])
    monkeypatch.setattr(emitter, "emit_v2", lambda: pytest.fail("Generation before argument validation"))
    assert emitter.main() == 64
    assert private_pipe == {1: b"", 2: USAGE}


def test_application_import_failure_has_fixed_diagnostic(private_pipe, monkeypatch):
    original_import = builtins.__import__

    def broken(name, *args, **kwargs):
        if name == "inky_web":
            raise ImportError("synthetic-secret-path")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", broken)
        status = emitter.main()
    assert status == 70
    assert private_pipe == {1: b"", 2: FAILED}


def test_generation_failure_has_fixed_diagnostic(private_pipe, monkeypatch):
    def broken(*_, **__):
        raise RuntimeError("synthetic-secret")

    monkeypatch.setattr(auth, "_new_credentials", broken)
    assert emitter.main() == 70
    assert private_pipe == {1: b"", 2: FAILED}


def test_partial_write_failure_keeps_prefix_private_and_never_retries_generation(private_pipe, monkeypatch):
    calls = []
    payload = b'{"synthetic-secret":"private"}\n'

    def generate():
        calls.append(True)
        return payload

    def broken_write(fd, value):
        if fd == 2:
            private_pipe[2].extend(value)
            return len(value)
        if private_pipe[1]:
            raise BrokenPipeError("synthetic-secret")
        private_pipe[1].extend(value[:8])
        return 8

    monkeypatch.setattr(emitter, "emit_v2", generate)
    monkeypatch.setattr(os, "write", broken_write)
    assert emitter.main() == 70 and calls == [True]
    assert private_pipe == {1: payload[:8], 2: FAILED}


@pytest.mark.parametrize("chunk", [0, 3])
def test_write_progress_is_complete_or_failed(private_pipe, monkeypatch, chunk):
    payload = b'{"synthetic":"private"}\n'
    monkeypatch.setattr(emitter, "emit_v2", lambda: payload)

    def short_write(fd, value):
        count = min(chunk, len(value)) if fd == 1 else len(value)
        private_pipe[fd].extend(value[:count])
        return count

    monkeypatch.setattr(os, "write", short_write)
    assert emitter.main() == (0 if chunk else 70)
    assert private_pipe == ({1: payload, 2: b""} if chunk else {1: b"", 2: FAILED})


def test_oversized_record_fails_before_stdout(private_pipe, monkeypatch):
    monkeypatch.setattr(auth, "_new_credentials", lambda *_, **__: SimpleNamespace(
        record=lambda: {"synthetic": "x" * emitter.MAX_OUTPUT_BYTES},
    ))
    assert emitter.main() == 70
    assert private_pipe == {1: b"", 2: FAILED}


def test_serializer_has_no_state_environment_or_network_access(monkeypatch, tmp_path):
    def forbidden(*_, **__):
        pytest.fail("Serializer attempted state/environment/network access")

    class NoEnvironment:
        get = __getitem__ = __iter__ = __contains__ = forbidden

    with monkeypatch.context() as patch:
        for name in ("load_or_create_credentials", "reset_credentials", "_write_credentials", "_read_record"):
            patch.setattr(auth, name, forbidden)
        for name in ("mkdir", "read_bytes", "read_text", "write_bytes", "write_text", "open"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(os, "open", forbidden)
        patch.setattr(os, "environ", NoEnvironment())
        patch.setattr(socket, "socket", forbidden)
        payload = emitter.emit_v2()
    assert payload.isascii() and payload.endswith(b"\n")
    assert list(tmp_path.iterdir()) == []
