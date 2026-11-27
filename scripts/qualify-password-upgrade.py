#!/usr/bin/env python3
"""Exercise staged auth over real loopback HTTP/WS, using synthetic credentials only."""
from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import logging
import os
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path

sys.dont_write_bytecode = True
PREFIX = "inky-password-qa-"
MARKER = "Inky Studio synthetic password qualification only\n"
COOKIE_NAME = "inky_session"


class QualificationFailure(Exception):
    """Only fixed check labels may be included in public output."""


def serve(fd: int, directory: Path) -> None:
    """Child process: no main lifespan, display, scheduler, database or updater."""
    if (not directory.name.startswith(PREFIX)
            or stat.S_IMODE(directory.stat().st_mode) != 0o700
            or (directory / ".qualification-only").read_text() != MARKER):
        raise QualificationFailure("invalid_private_test_directory")
    os.environ["INKY_STUDIO_DATA_DIR"] = str(directory)
    os.environ["INKY_STUDIO_DISPLAY_MODE"] = "mock"
    os.environ.pop("INKY_STUDIO_DISPLAY_PROFILE", None)
    os.environ.pop("INKY_STUDIO_DISABLE_AUTH", None)
    logging.disable(logging.CRITICAL)

    import uvicorn
    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from inky_web import auth
    from inky_web.api.auth import router as auth_router
    from inky_web.api.ws import router as ws_router
    from inky_web.events import EventBus
    from inky_web.main import AuthMiddleware, validation_error

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.include_router(auth_router, prefix="/api")
    app.include_router(ws_router, prefix="/api")
    sessions = auth.SessionStore()
    app.state.sessions = sessions
    app.state.auth_service = auth.CredentialService(
        auth.load_or_create_credentials(directory), sessions,
    )
    app.state.login_limiter = auth.LoginRateLimiter()
    app.state.password_change_limiter = auth.LoginRateLimiter()
    app.state.bus = EventBus()
    with socket.socket(fileno=fd) as listener:
        if listener.getsockname()[0] != "127.0.0.1":
            raise QualificationFailure("non_loopback_socket")
        server = uvicorn.Server(uvicorn.Config(
            app, loop="asyncio", lifespan="off", log_config=None, access_log=False,
            timeout_graceful_shutdown=2,
        ))
        server.run(sockets=[listener])


class Deadline:
    def __init__(self, seconds: float) -> None:
        self.expires = time.monotonic() + seconds

    def remaining(self, maximum: float = 10) -> float:
        remaining = self.expires - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return min(remaining, maximum)

    def arm(self) -> None:
        # POSIX watchdog also bounds fragmented HTTP reads and library waits,
        # rather than relying only on per-socket inactivity timeouts.
        signal.setitimer(signal.ITIMER_REAL, self.remaining(180))


@dataclass
class Reply:
    status: int
    body: dict = field(repr=False)
    set_cookie: str = field(repr=False)
    elapsed_ms: float

    def cookie(self) -> str:
        parsed = SimpleCookie()
        parsed.load(self.set_cookie)
        if COOKIE_NAME not in parsed:
            raise QualificationFailure("session_cookie_missing")
        return f"{COOKIE_NAME}={parsed[COOKIE_NAME].value}"


class HTTPClient:
    """No proxies, redirects, automatic cookie storage or mutation retries."""

    def __init__(self, port: int, deadline: Deadline) -> None:
        self.port = port
        self.deadline = deadline

    def request(self, method: str, path: str, body: dict | None = None,
                cookie: str | None = None) -> Reply:
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        started = time.monotonic()
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=self.deadline.remaining(),
        )
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers=headers)
            response = connection.getresponse()
            raw = response.read(65537)
            if len(raw) > 65536:
                raise QualificationFailure("oversized_response")
            return Reply(response.status, json.loads(raw), response.getheader("Set-Cookie", ""),
                         round((time.monotonic() - started) * 1000, 3))
        finally:
            connection.close()


@contextlib.contextmanager
def running_server(directory: Path, deadline: Deadline):
    deadline.arm()
    # The parent binds once, avoiding the free-port lookup/startup race. Only the
    # child retains the listening descriptor after Popen returns.
    process = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--serve-fd", str(listener.fileno()),
                 "--qa-data-dir", str(directory)],
                pass_fds=(listener.fileno(),), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        client = HTTPClient(port, deadline)
        while True:
            deadline.remaining()
            if process.poll() is not None:
                raise QualificationFailure("isolated_server_startup")
            try:
                response = client.request("GET", "/api/auth/status")
                if response.status == 200:
                    break
            except (ConnectionError, TimeoutError, http.client.HTTPException):
                pass
            time.sleep(min(0.05, deadline.remaining()))
        yield client
    finally:
        # Shutdown has its own finite budget; do not interrupt terminate/reap
        # with an alarm that expires while handling an earlier test failure.
        signal.setitimer(signal.ITIMER_REAL, 0)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        # The child owns every server thread and socket, so reaping it also
        # bounds shutdown when a server implementation regresses.
        if process is not None and process.poll() is None:
            raise QualificationFailure("isolated_server_cleanup")


def qualify(seconds: float, report: dict) -> None:
    deadline = Deadline(seconds)
    deadline.arm()
    from inky_web import __version__
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    report["backend_version"] = __version__
    report["python"] = sys.version.split()[0]

    def check(condition: bool, name: str) -> None:
        if not condition:
            raise QualificationFailure(name)
        report["checks"].append(name)

    with tempfile.TemporaryDirectory(prefix=PREFIX) as temporary:
        directory = Path(temporary)
        check(stat.S_IMODE(directory.stat().st_mode) == 0o700, "private_test_directory")
        (directory / ".qualification-only").write_text(MARKER)
        initial = "QA-" + secrets.token_urlsafe(18)
        replacement = "QA-new-é-" + secrets.token_urlsafe(18)
        path = directory / "credentials.json"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stored:
            json.dump({"password": initial}, stored)

        with running_server(directory, deadline) as client:
            status = client.request("GET", "/api/auth/status")
            check(status.body == {"authenticated": False, "auth_required": True,
                                  "password_change_supported": True}, "public_capability")
            record = json.loads(path.read_text())
            check(record.get("version") == 2 and record.get("algorithm") == "scrypt"
                  and "password" not in record and "bootstrap_password" not in record,
                  "legacy_migration_hash_only")
            check(client.request("POST", "/api/auth/logout").status == 401, "unauthenticated_401")
            first = client.request("POST", "/api/auth/login", {"password": initial})
            second = client.request("POST", "/api/auth/login", {"password": initial})
            check(first.status == second.status == 200, "two_independent_logins")
            first_cookie, second_cookie = first.cookie(), second.cookie()
            check(first_cookie != second_cookie, "distinct_sessions")
            report["timings_ms"]["initial_login"] = first.elapsed_ms

            wrong = client.request("POST", "/api/auth/password", {
                "current_password": "synthetic-wrong-password", "new_password": replacement,
            }, first_cookie)
            check(wrong.status == 403 and not wrong.set_cookie, "wrong_password_403")
            check(client.request("GET", "/api/auth/status", cookie=first_cookie).body.get("authenticated")
                  is True, "wrong_password_preserves_session")
            invalid = client.request("POST", "/api/auth/password", {
                "current_password": initial, "new_password": "short",
            }, first_cookie)
            check(invalid.status == 422 and initial not in json.dumps(invalid.body)
                  and '"input"' not in json.dumps(invalid.body), "validation_422_without_secret")

            # A connected loopback socket prevents proxy configuration from
            # redirecting even the WebSocket handshake to an external host.
            with socket.create_connection(("127.0.0.1", client.port), timeout=deadline.remaining()) as tcp:
                with connect(f"ws://127.0.0.1:{client.port}/api/ws", sock=tcp,
                             additional_headers={"Cookie": second_cookie},
                             open_timeout=deadline.remaining(), close_timeout=2, max_size=65536) as ws:
                    check(json.loads(ws.recv(timeout=deadline.remaining(5))).get("type") == "hello", "websocket_hello")
                    rotated = client.request("POST", "/api/auth/password", {
                        "current_password": initial, "new_password": replacement,
                    }, first_cookie)
                    check(rotated.status == 200 and rotated.body.get("authenticated") is True,
                          "rotation_200")
                    new_cookie = rotated.cookie()
                    check(new_cookie not in {first_cookie, second_cookie}
                          and "httponly" in rotated.set_cookie.lower()
                          and "samesite=strict" in rotated.set_cookie.lower(), "replacement_cookie")
                    report["timings_ms"]["rotation"] = rotated.elapsed_ms
                    try:
                        ws.recv(timeout=deadline.remaining(5))
                    except ConnectionClosed as closed:
                        check(closed.rcvd is not None and closed.rcvd.code == 1008,
                              "idle_websocket_revoked_1008")
                    else:
                        raise QualificationFailure("idle_websocket_not_revoked")

            for cookie in (first_cookie, second_cookie):
                check(client.request("POST", "/api/auth/logout", cookie=cookie).status == 401,
                      "old_session_revoked")
            check(client.request("GET", "/api/auth/status", cookie=new_cookie).body.get("authenticated")
                  is True, "replacement_session_valid")
            check(client.request("POST", "/api/auth/login", {"password": initial}).status == 401,
                  "old_password_rejected")
            check(client.request("POST", "/api/auth/login", {"password": replacement}).status == 200,
                  "new_password_accepted")
            # Wrong old password + successful rotation consumed two attempts.
            for _ in range(3):
                response = client.request("POST", "/api/auth/password", {
                    "current_password": "synthetic-wrong-password", "new_password": replacement,
                }, new_cookie)
                check(response.status == 403, "rotation_attempt_counted")
            throttled = client.request("POST", "/api/auth/password", {
                "current_password": replacement, "new_password": replacement,
            }, new_cookie)
            check(throttled.status == 429, "rotation_rate_limit_429")
            check(client.request("GET", "/api/auth/status", cookie=new_cookie).body.get("authenticated")
                  is True, "rate_limit_preserves_session")
            persisted = path.read_text()
            check(initial not in persisted and replacement not in persisted
                  and "bootstrap_password" not in json.loads(persisted), "no_persisted_plaintext")
            check(stat.S_IMODE(path.stat().st_mode) == 0o600, "private_credentials")

        # A new OS process reloads the real file; sessions must not survive it.
        with running_server(directory, deadline) as restarted:
            check(restarted.request("POST", "/api/auth/logout", cookie=new_cookie).status == 401,
                  "restart_revokes_sessions")
            check(restarted.request("POST", "/api/auth/login", {"password": initial}).status == 401,
                  "restart_rejects_old_password")
            login = restarted.request("POST", "/api/auth/login", {"password": replacement})
            check(login.status == 200, "restart_accepts_new_password")
            report["timings_ms"]["reloaded_login"] = login.elapsed_ms
    check(not directory.exists(), "temporary_data_removed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60,
                        help="Overall test deadline in seconds (5–180), plus bounded cleanup")
    parser.add_argument("--serve-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--qa-data-dir", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve_fd is not None:
        try:
            serve(args.serve_fd, args.qa_data_dir)
            return 0
        except BaseException:
            return 1  # Never emit a traceback carrying request/credential state.
    if not 5 <= args.timeout <= 180:
        parser.error("--timeout must be between 5 and 180 seconds")
    report = {"status": "failed", "checks": [], "timings_ms": {}}
    started = time.monotonic()
    logging.disable(logging.CRITICAL)

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    def timed_out(signum, frame):
        raise TimeoutError

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, timed_out)
    try:
        qualify(args.timeout, report)
        report["status"] = "passed"
    except QualificationFailure as error:
        report["failed_check"] = str(error)  # These messages are fixed labels only.
    except KeyboardInterrupt:
        report["failed_check"] = "interrupted"
    except Exception as error:
        report["failed_check"] = type(error).__name__  # Do not print exception values.
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
