"""``tui_handoff_frontend:main``: a ``busk run --frontend`` for
``test_tui_host.py``'s hand-off test.

It runs where the TUI's frontend runs, on busk run's console process with the
run's show. It appends the show's title and the hand-off file it was given
(``$BUSK_TUI_NEXT``) to the JSON-lines file ``$BUSK_TUI_TEST_REPORT``; on a
show titled ``A`` it hands ``$BUSK_TUI_TEST_NEXT`` over to busk-tui's parent,
as the TUI does when it opens another show. Then it returns, and the run ends.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from busk_tui import parent


def main(show: Any) -> None:
    title = show.show["meta"]["title"]
    with Path(os.environ["BUSK_TUI_TEST_REPORT"]).open("a", encoding="utf-8") as report:
        report.write(json.dumps({"title": title, "next": os.environ.get(parent.NEXT)}) + "\n")
    if title == "A":
        parent.hand_off(Path(os.environ["BUSK_TUI_TEST_NEXT"]))
