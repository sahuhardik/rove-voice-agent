"""Run the LiveKit media server for the local development loop.

`docs/07` D-02 chose LiveKit for the room model and named the bill honestly:

> **What the decision costs, honestly.** We run a media server, or pay someone
> to (`06` §9.3 item 13 — who runs it is Hardik's call).

This module is the *development* half of that bill and nothing more. It
launches the `livekit-server` binary in **`--dev` mode**, which hard-codes the
API key pair `devkey` / `secret`.

**That key pair is published in LiveKit's own documentation.** It is not a
weak secret, it is a *public* one. Anything it protects is protected by the
network, not by the credential. The consequences, stated rather than implied:

* `--dev` binds for local use and is fine behind `127.0.0.1`. Exposed to a
  network, it is an open media server that anyone can mint tokens for — which
  also means minting a token for `roomAdmin`, which §1.4.2's whole mint exists
  to withhold.
* Production needs a real key pair, from a LiveKit Cloud project or from a
  self-hosted `livekit.yaml`, delivered as `ROVE_LIVEKIT_API_KEY` /
  `ROVE_LIVEKIT_API_SECRET` and never written into a repository. `server/
  config.py` reads exactly those two variables, so moving from dev keys to
  real ones is a deployment change and not a code change.
* `--dev` also runs with TURN and redis off and a single node. §8.1 budgets a
  TURN relay for users behind restrictive NAT; that is a production item and it
  is not exercised here.

Which of those two shapes is actually deployed is `docs/06` §9.3 item 13, and
it is Hardik's call, not this module's.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from server.config import Settings

#: Where the binary was put on this host. Overridable, because the path is a
#: fact about one machine and nothing else.
DEFAULT_BINARY = Path.home() / "livekit-server" / "livekit-server"

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 7880


def find_binary(path: str | Path | None = None) -> Path | None:
    """The `livekit-server` binary, or `None` if this host has none."""
    if path:
        candidate = Path(path).expanduser()
        return candidate if candidate.is_file() else None
    if DEFAULT_BINARY.is_file():
        return DEFAULT_BINARY
    found = shutil.which("livekit-server")
    return Path(found) if found else None


def version(binary: str | Path | None = None) -> str:
    """`livekit-server --version`, or `""` if it will not run."""
    found = find_binary(binary)
    if found is None:
        return ""
    try:
        done = subprocess.run(
            [str(found), "--version"], capture_output=True, text=True, timeout=20
        )
    except Exception:  # noqa: BLE001
        return ""
    return (done.stdout or done.stderr).strip()


def node_ip_from_settings(settings: Settings) -> str | None:
    """The address LiveKit must advertise in its ICE candidates, or `None`.

    Without `--node-ip` the server advertises the host's private interface
    address, which a browser on the internet cannot reach: signalling connects
    and the microphone never publishes. The IP is derived from config rather
    than hard-coded -- the host of `ROVE_LIVEKIT_URL` when that is a public IP
    literal, else `ROVE_PUBLIC_IP` -- and loopback means a purely local loop
    that needs no flag.
    """
    host = urlparse(settings.livekit_url).hostname or ""
    for candidate in (host, settings.public_ip):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not (address.is_loopback or address.is_unspecified):
            return str(address)
    return None


@dataclass
class DevServer:
    """A `livekit-server --dev` process, started and stopped by us."""

    binary: Path
    bind: str = DEFAULT_BIND
    port: int = DEFAULT_PORT
    log_path: Path | None = None
    process: subprocess.Popen | None = None
    #: Passed as `--node-ip` when set; see `node_ip_from_settings`.
    node_ip: str | None = None

    @property
    def ws_url(self) -> str:
        return f"ws://{self.bind}:{self.port}"

    @property
    def http_url(self) -> str:
        return f"http://{self.bind}:{self.port}"

    def command(self) -> list[str]:
        """The argv this server is launched with."""
        argv = [str(self.binary), "--dev", "--bind", self.bind, "--port", str(self.port)]
        if self.node_ip:
            argv += ["--node-ip", self.node_ip]
        return argv

    def start(self, *, timeout: float = 30.0) -> "DevServer":
        """Launch it and wait until it answers.

        Raises:
            RuntimeError: If the process dies, or never binds the port.
        """
        log: Any = subprocess.DEVNULL
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command(),
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ},
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"livekit-server exited with {self.process.returncode}; "
                    f"see {self.log_path}"
                )
            if self.responding():
                return self
            time.sleep(0.25)
        self.stop()
        raise RuntimeError(f"livekit-server did not bind {self.bind}:{self.port}")

    def responding(self) -> bool:
        """Whether the media server is answering on its HTTP port."""
        import socket

        try:
            with socket.create_connection((self.bind, self.port), timeout=0.5):
                return True
        except OSError:
            return False

    def stop(self, timeout: float = 15.0) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=timeout)
        self.process = None

    def __enter__(self) -> "DevServer":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.stop()


def start_dev_server(
    *,
    binary: str | Path | None = None,
    bind: str = DEFAULT_BIND,
    port: int = DEFAULT_PORT,
    log_path: Path | None = None,
    node_ip: str | None = None,
) -> DevServer:
    """Find the binary and start it, or raise with a readable reason."""
    found = find_binary(binary)
    if found is None:
        raise RuntimeError(
            "no livekit-server binary found. Expected it at "
            f"{DEFAULT_BINARY} or on PATH — see README.md."
        )
    return DevServer(
        binary=found, bind=bind, port=port, log_path=log_path, node_ip=node_ip
    ).start()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - a loop
    """`python -m server.livekit_dev` — run it in the foreground."""
    import argparse

    parser = argparse.ArgumentParser(description="Run livekit-server in --dev mode.")
    parser.add_argument("--binary", default="", help=f"default: {DEFAULT_BINARY}")
    parser.add_argument(
        "--bind", default="", help=f"default: {DEFAULT_BIND}, or 0.0.0.0 with a node IP"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--node-ip",
        default="",
        help="default: derived from ROVE_LIVEKIT_URL / ROVE_PUBLIC_IP",
    )
    args = parser.parse_args(argv)

    node_ip = args.node_ip or node_ip_from_settings(Settings.from_env())
    # A public node IP is pointless behind a loopback bind.
    bind = args.bind or ("0.0.0.0" if node_ip else DEFAULT_BIND)
    server = start_dev_server(
        binary=args.binary or None, bind=bind, port=args.port, node_ip=node_ip
    )
    print(f"livekit-server {version(server.binary)} on {server.ws_url}")
    print("dev keys: devkey / secret — published, local-loop only. See README.md.")
    try:
        assert server.process is not None
        return server.process.wait()
    except KeyboardInterrupt:
        server.stop()
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
