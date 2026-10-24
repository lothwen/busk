"""The TUI's tests (``busk_tui``): skipped as a whole when Textual is not
installed (the ``tui`` extra), so the engine's suite runs without it.

Fixtures: ``club`` (the club-night example built once, as an
:class:`busk.OfflineShow` whose help, ``expected`` answers and questions are
the real ones) and ``club_path`` (that show saved in a temporary directory).
Every test gets its own config and state directories, never the user's.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

if importlib.util.find_spec("textual") is None:
    collect_ignore_glob = ["test_tui_*.py"]
else:
    import busk

    ROOT = Path(__file__).resolve().parents[2]
    CLUB_NIGHT = ROOT / "examples" / "club-night.busk"

    @pytest.fixture(scope="session")
    def club_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
        """The club-night show, built from its script and saved."""
        path = tmp_path_factory.mktemp("club") / "club.show"
        show = busk.OfflineShow(busk.new_show("Club Night"), path=path)
        show.run_script(CLUB_NIGHT)
        return path

    @pytest.fixture(scope="session")
    def club(club_path: Path) -> busk.OfflineShow:
        """The club-night show, to read and ask (not to change: it is shared)."""
        show, _ = busk.load_show(club_path)
        return busk.OfflineShow(show)

    @pytest.fixture(autouse=True)
    def tui_directories(
        tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> Path:
        """A config directory of the test's own (the state one is the
        engine suite's ``state_directory``), and no options from a run."""
        root = tmp_path_factory.mktemp("xdg-config")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
        monkeypatch.delenv("BUSK_TUI_OPTIONS", raising=False)
        return root
