"""Best-effort, bounded GitHub release checks. Never download or execute updates."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import queue
import ssl
import tempfile
import threading
import time
import urllib.request

from . import __version__
from .compatibility import version_tuple

RELEASES_URL = "https://github.com/cyberbalsa/cpc-modloader/releases/latest"
API_URL = "https://api.github.com/repos/cyberbalsa/cpc-modloader/releases/latest"
CHECK_INTERVAL = 24 * 60 * 60
RETRY_INTERVAL = 60 * 60
TIMEOUT = 3.0
MAX_RESPONSE = 256 * 1024


@dataclass(frozen=True)
class UpdateStatus:
    state: str
    latest: str | None = None
    stale: bool = False

    @property
    def notice(self) -> str | None:
        if self.state == "update_available":
            return f"loader out of date - v{self.latest} available on github"
        return None

    def report(self) -> dict:
        return asdict(self) | {"url": RELEASES_URL}


def https_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Frozen OpenSSL may retain the build distro's certificate paths. Use the
    # host's trust bundle when those paths are absent, keeping TLS verification.
    if not context.cert_store_stats()["x509_ca"] and not any(os.environ.get(k) for k in ("SSL_CERT_FILE", "SSL_CERT_DIR")):
        for path in ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem",
                     "/etc/pki/tls/certs/ca-bundle.crt", "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"):
            if Path(path).is_file():
                context.load_verify_locations(cafile=path)
                break
    return context


def fetch_latest() -> str:
    request = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"cpc-modloader/{__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=https_context()) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("release response too large")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("draft") is not False or data.get("prerelease") is not False:
        raise ValueError("not a public stable release")
    tag = data.get("tag_name")
    version_tuple(tag)
    return tag.removeprefix("v")


def check_for_updates(cache: Path, *, enabled=True, current=__version__) -> UpdateStatus:
    if not enabled:
        return UpdateStatus("disabled")
    now = time.time()
    saved = {}
    latest = None
    try:
        if cache.stat().st_size <= 4096:
            saved = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            saved = {}
        if saved.get("latest") is not None:
            version_tuple(saved["latest"])
            latest = saved["latest"].removeprefix("v")
    except (OSError, ValueError, TypeError):
        saved = {}
    checked = saved.get("checked_at", 0)
    fresh = (isinstance(checked, (int, float)) and
             0 <= now - checked < (CHECK_INTERVAL if saved.get("ok") and latest else RETRY_INTERVAL))
    ok = bool(saved.get("ok")) and latest is not None
    if not fresh:
        result = queue.Queue(maxsize=1)

        def fetch():
            try:
                result.put(fetch_latest())
            except Exception:
                result.put(None)  # Network, TLS and response failures never prevent launch.

        # A daemon also bounds DNS resolution, which socket timeouts do not cover.
        threading.Thread(target=fetch, daemon=True).start()
        try:
            received = result.get(timeout=TIMEOUT)
        except queue.Empty:
            received = None
        ok = received is not None
        if ok:
            latest = received
        temporary = None
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache.parent,
                                             prefix=".update-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"checked_at": now, "latest": latest, "ok": ok}, stream)
            os.replace(temporary, cache)
        except OSError:
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
    if latest and version_tuple(latest) > version_tuple(current):
        return UpdateStatus("update_available", latest, stale=not ok)
    return UpdateStatus("up_to_date" if ok else "unavailable", latest, stale=not ok)
