"""Show files on disk: load, save, backups and the new-show template (spec §17).

**Formats**, chosen by extension (any other is an error):

* ``.show``: a ZIP with one entry, ``show.json``, deflated and stamped with a
  fixed date (1980-01-01), so equal shows produce byte-identical files.
  Assets (gobo images, profile sources) join it in Phase 7;
* ``.json``: the same document as plain JSON, for hand-written shows and
  tests.

Both are written with ``indent=2`` and keys in schema order (the store holds
validated shows, which pydantic builds in schema order).

**Loading.** A corrupt or invalid show is refused, never half-loaded (§18):
any validation *error* raises :class:`ShowLoadError` carrying every issue.
Warnings do not prevent loading and are returned alongside the show. When a
load fails, :func:`newest_backup` names the backup to offer.

**Atomic writes** (:func:`atomic_write`): write ``.<name>.tmp`` next to the
target, flush and ``fsync`` it, ``os.replace`` it over the target, then
``fsync`` the directory. On any error the temp file is removed and the
original stays untouched.

**Backups.** Before saving over an existing file, the old file is copied to
``<stem>.backups/<stem>-<UTC timestamp><ext>`` next to it; the newest
:data:`BACKUPS_KEPT` are kept.

**Migrations** (§17) arrive with the first breaking schema change; the
schema version is still 1.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from busk import __version__
from busk.model.show import SCHEMA_VERSION, Show
from busk.model.validate import Issue, has_errors, validate_show
from busk.session.ids import IdFactory

SHOW_ENTRY: Final = "show.json"
"""The one entry of a ``.show`` ZIP."""

ZIP_DATE: Final = (1980, 1, 1, 0, 0, 0)
"""The fixed timestamp of the ZIP entry (the earliest ZIP can store)."""

BACKUPS_KEPT: Final = 10
"""Rolling backups kept next to a saved file."""

FORMATS: Final = (".show", ".json")

type WallClock = Callable[[], datetime]
"""Wall-clock time (UTC), injected so tests are deterministic."""


def utc_now() -> datetime:
    """The real wall clock."""
    return datetime.now(UTC)


class ShowLoadError(Exception):
    """The show file could not be loaded; :attr:`issues` says why."""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__(f"show failed validation with {len(issues)} issue(s)")
        self.issues = issues


# ------------------------------------------------------------------- loading


def read_show_bytes(path: str | Path) -> bytes:
    """The ``show.json`` document of ``path`` (a ``.show`` ZIP or a ``.json`` file).

    Raises :class:`ShowLoadError` for an unknown extension or a damaged ZIP,
    and :class:`OSError` if the file cannot be read.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return path.read_bytes()
    if suffix != ".show":
        raise ShowLoadError([Issue("error", "", _format_error(path))])
    data = path.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.read(SHOW_ENTRY)
    except (zipfile.BadZipFile, KeyError, zipfile.LargeZipFile) as exc:
        raise ShowLoadError([Issue("error", "", f"Not a valid .show file: {exc}")]) from None


def load_show(path: str | Path) -> tuple[Show, list[Issue]]:
    """Read and validate the show at ``path`` (``.show`` or ``.json``).

    Returns the validated show and its warnings. Raises :class:`ShowLoadError`
    if the file is not a show or validation reports any error, and
    :class:`OSError` (for example :class:`FileNotFoundError`) if the file
    cannot be read.
    """
    show, issues = validate_show(read_show_bytes(path))
    if show is None or has_errors(issues):
        raise ShowLoadError(issues)
    return show, issues


# -------------------------------------------------------------------- saving


def show_json(show: Show) -> bytes:
    """The show as UTF-8 JSON, ``indent=2``, with a final newline."""
    return (json.dumps(show, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def encode_show(show: Show, path: str | Path) -> bytes:
    """The bytes of ``show`` in the format ``path``'s extension asks for."""
    suffix = Path(path).suffix.lower()
    data = show_json(show)
    if suffix == ".json":
        return data
    if suffix != ".show":
        raise ValueError(_format_error(Path(path)))
    return zip_show_json(data)


def zip_show_json(data: bytes) -> bytes:
    """A deterministic ``.show`` ZIP holding ``data`` as ``show.json``."""
    info = zipfile.ZipInfo(SHOW_ENTRY, date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix, whatever the platform: same bytes everywhere
    info.external_attr = 0o644 << 16
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, data, compresslevel=6)
    return buffer.getvalue()


def save_show(show: Show, path: str | Path, *, now: datetime, backups: bool = True) -> Path | None:
    """Write ``show`` to ``path`` atomically, backing up the file it replaces.

    Returns the backup's path, or ``None`` when there was nothing to back up.
    The caller sets ``meta.modified`` first (saving is not an edit).
    """
    path = Path(path)
    data = encode_show(show, path)
    kept = backup(path, now) if backups and path.exists() else None
    atomic_write(path, data)
    return kept


def atomic_write(path: str | Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` atomically (see the module docs)."""
    path = Path(path)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Make the rename durable. Directories cannot be opened on Windows; skip there."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


# ------------------------------------------------------------------- backups


def backup_directory(path: Path) -> Path:
    """Where the backups of ``path`` live: ``<stem>.backups`` next to it."""
    return path.with_name(f"{path.stem}.backups")


def file_stamp(now: datetime) -> str:
    """A UTC timestamp for file names that sorts in time order."""
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def backup(path: Path, now: datetime) -> Path:
    """Copy ``path`` into its backup directory and keep the newest :data:`BACKUPS_KEPT`."""
    directory = backup_directory(path)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = file_stamp(now)
    target = directory / f"{path.stem}-{stamp}{path.suffix}"
    counter = 1
    while target.exists():  # two saves within one microsecond (or a frozen test clock)
        target = directory / f"{path.stem}-{stamp}-{counter}{path.suffix}"
        counter += 1
    shutil.copy2(path, target)
    rotate(directory, path, BACKUPS_KEPT)
    return target


def _backups(directory: Path, path: Path) -> list[Path]:
    """The backups of ``path``, oldest first."""
    pattern = re.compile(
        rf"{re.escape(path.stem)}-(\d{{8}}T\d{{12}}Z)(?:-(\d+))?{re.escape(path.suffix)}"
    )
    found = []
    for candidate in directory.glob(f"{path.stem}-*{path.suffix}"):
        match = pattern.fullmatch(candidate.name)
        if match is not None:
            found.append(((match[1], int(match[2] or 0)), candidate))
    return [candidate for _, candidate in sorted(found)]


def rotate(directory: Path, path: Path, keep: int) -> None:
    """Delete all but the newest ``keep`` backups of ``path``."""
    backups = _backups(directory, path)
    for old in backups[: max(len(backups) - keep, 0)]:
        old.unlink(missing_ok=True)


def newest_backup(path: str | Path) -> Path | None:
    """The newest backup of ``path``, to offer when it fails to load (§18)."""
    path = Path(path)
    directory = backup_directory(path)
    if not directory.is_dir():
        return None
    backups = _backups(directory, path)
    return backups[-1] if backups else None


# ------------------------------------------------------------------ template


def iso_time(now: datetime) -> str:
    """``meta.created`` / ``meta.modified``: ISO 8601 in UTC, to the second."""
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_show(title: str, *, ids: IdFactory, now: datetime, cid: str) -> Show:
    """The ``busk new`` template: a valid, empty show.

    One grand master, one empty page ``Main``, no routes; ``output`` sends at
    100 Hz as ``Busk Console`` with the installation's sACN CID (§5.16).
    """
    stamp = iso_time(now)
    doc: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "meta": {
            "id": ids.new("show"),
            "title": title,
            "created": stamp,
            "modified": stamp,
            "app": f"busk {__version__}",
        },
        "profiles": [],
        "universes": [],
        "fixtures": [],
        "groups": [],
        "presets": [],
        "effects": [],
        "cueLists": [],
        "playbacks": [],
        "pages": [{"id": ids.new("page"), "name": "Main", "number": 1, "slots": []}],
        "masters": [{"id": ids.new("m"), "name": "Grand Master", "kind": "grand"}],
        "surfaces": [],
        "bindings": [],
        "output": {
            "engineHz": 100,
            "sacnSourceName": "Busk Console",
            "sacnCid": cid,
            "holdLastFrameOnEngineStall": True,
            "routes": [],
        },
        "park": [],
    }
    show, issues = validate_show(json.dumps(doc))
    if show is None or issues:  # the template is valid by construction
        raise AssertionError(issues)
    return show


def _format_error(path: Path) -> str:
    return f"Unknown show file extension {path.suffix or '(none)'!r}: use .show or .json"
