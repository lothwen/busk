"""Where busk keeps its own state: the state directory and the installation CID.

The **state directory** holds what belongs to this installation rather than
to a show: the sACN CID and the autosaves. It is ``--state-dir`` when given,
else ``$XDG_STATE_HOME/busk``, else ``~/.local/state/busk``.

The **installation CID** (§5.16: "persistent per installation") lives in
``<stateDir>/cid``, created once with a random UUID. ``busk new`` copies it
into the show's ``output.sacnCid``.

The **event logs** (phase-7-plan §5.21) live in ``<stateDir>/logs/<meta.id>``.

The **web key** (phase-6-plan decision 15) lives in ``<stateDir>/web-key``:
8 URL-safe characters, created once and readable by the owner only. Every
web remote URL carries it (``?k=<key>``); deleting the file makes a new one.
"""

from __future__ import annotations

import os
import re
import secrets
import uuid
from pathlib import Path

from busk.persistence.show_file import atomic_write


def state_directory(override: Path | None = None) -> Path:
    """The state directory (not created here)."""
    if override is not None:
        return override
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "busk"


def installation_cid(state_dir: Path) -> str:
    """The installation's sACN CID, created on first use."""
    path = state_dir / "cid"
    try:
        return str(uuid.UUID(path.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        pass
    cid = str(uuid.uuid4())
    state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(path, (cid + "\n").encode("utf-8"))
    return cid


_WEB_KEY = re.compile(r"[A-Za-z0-9_-]{8,128}")


def web_key(state_dir: Path) -> str:
    """The installation's web remote key, created on first use. A file that
    holds no valid key is replaced."""
    path = state_dir / "web-key"
    try:
        key = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        key = ""
    if _WEB_KEY.fullmatch(key):
        return key
    key = secrets.token_urlsafe(6)  # 6 random bytes: 8 characters
    state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(path, (key + "\n").encode("utf-8"))
    path.chmod(0o600)
    return key


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_name(show_id: str) -> str:
    """``show_id`` as a directory name: characters unsafe in a file name are
    replaced (show ids are opaque strings)."""
    name = _UNSAFE.sub("_", show_id) or "_"
    return "_" if name in (".", "..") else name


def autosave_directory(state_dir: Path, show_id: str) -> Path:
    """``<stateDir>/autosave/<meta.id>``; characters unsafe in a file name are
    replaced (show ids are opaque strings)."""
    return state_dir / "autosave" / _safe_name(show_id)


def log_directory(logs: Path, show_id: str) -> Path:
    """``<logs>/<meta.id>``, where ``logs`` is ``<stateDir>/logs``; unsafe
    characters are replaced as in :func:`autosave_directory`."""
    return logs / _safe_name(show_id)
