"""IMPORT PLOT (MVR plan Phase 4): what ``rig import`` of a plot chosen in
the file picker would do to the show, and the line that does it. F3's
``[import plot…]`` and the File menu's Import plot… open it.

It shows ``rig check``'s answer (busk's ``rig_check``, GAP-59), as busk
words it. On a first import, into a show with no fixture from a plot yet, it
asks for the frame that places the plot on busk's stage: the side of the
plot the audience is on (``audience``, as the plot is drawn from above, +y
up the page), and where busk's origin, the middle of the downstage edge at
deck height, is in the plot (``origin``, in millimetres). They start at the
show's frame, else busk's (``-y``, ``0 0 0``), and each change has busk
check again. A later import shows the frame the show keeps: another moves
every fixture of the plot, and is the prompt's to give.

``[import]`` closes with the line: ``rig import "<path>"``, with
``audience`` and ``origin`` where they differ from where they started, and
``cascade`` while it is ticked. It runs only once busk has checked the frame
shown, and only when the import changes the show and nothing blocks it.
``cascade`` shows when the import removes fixtures that something uses,
ticked, as busk refuses the import without it; untick it, and the import
cannot run.

It sends nothing: it closes with the line, or ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache, partial
from pathlib import Path
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.scalar import Scalar
from textual.geometry import Size
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Static

from busk_tui import colors, commands
from busk_tui.commands import Line
from busk_tui.model import PlotRead
from busk_tui.widgets.controls import ActionButton, ButtonStrip, ReadPlot
from busk_tui.widgets.dialogs import FormDialog, dialog_css, read_number
from busk_tui.widgets.file_picker import PathLine, home_text
from busk_tui.widgets.options import pick_chips

AUDIENCES: Final[Mapping[str, str]] = {
    "-y": "-y below",
    "+y": "+y above",
    "-x": "-x left",
    "+x": "+x right",
}
"""Each side of the plot the audience may be on, as ``rig import`` names it,
and its chip: where that side is as the plot is drawn from above."""

CHECK_ROWS: Final = 16
"""The most rows of the check shown at once; the rest scroll."""
MIN_ROWS: Final = 3
"""The fewest, on a screen too small for the dialog."""


def origin_text(origin: tuple[float, float, float]) -> str:
    """``0 -1500 0 mm``: every digit, as the line has them."""
    return " ".join(commands.exact(axis + 0.0) for axis in origin) + " mm"


def frame_text(audience: str, origin: tuple[float, float, float]) -> str:
    """``audience -y · origin 0 -1500 0 mm``."""
    return f"audience {audience} · origin {origin_text(origin)}"


def check_origin(values: tuple[str, ...]) -> str | None:
    if all(read_number(value) is not None for value in values):
        return None
    return "three distances in millimetres"


class PlotDialog(ModalScreen[Line | None]):
    """Closes with a ``rig import`` line for the plot at ``path``, or
    ``None`` (see the module docs). ``found`` is busk's check of it through
    the show's frame, if the file picker has it already. ← → move the
    audience, ``o`` asks for the origin, ``x`` ticks ``cascade``, Enter
    imports and Esc cancels."""

    DEFAULT_CSS = (
        dialog_css("PlotDialog")
        + f"""
    PlotDialog > Vertical {{ width: 100; max-width: 100%; }}
    PlotDialog Horizontal {{ width: 100%; margin-top: 0; }}
    PlotDialog Horizontal.buttons {{ margin-top: 1; }}
    PlotDialog .label {{ color: {colors.MID}; width: 10; }}
    PlotDialog PathLine {{ width: 100%; height: 1; margin-bottom: 1; }}
    PlotDialog AudienceRow {{ width: auto; }}
    PlotDialog AudienceRow:focus {{ background: {colors.SEL}; }}
    PlotDialog .origin {{ color: {colors.FG}; width: auto; margin-right: 1; }}
    PlotDialog .aside {{
        color: {colors.DIM}; width: 1fr; margin-left: 2; text-wrap: nowrap; text-overflow: ellipsis;
    }}
    PlotDialog .frame {{ color: {colors.DIM}; width: 100%; }}
    PlotDialog VerticalScroll {{
        width: 100%; height: auto; max-height: {CHECK_ROWS}; margin-top: 1;
        scrollbar-size-vertical: 1;
    }}
    PlotDialog .check {{ width: 100%; }}
    PlotDialog .why {{ width: 100%; height: auto; margin-top: 1; }}
    PlotDialog .cascade {{ margin-top: 1; height: auto; }}
    PlotDialog .cascade-note {{ color: {colors.DIM}; width: 1fr; margin-left: 1; }}
    PlotDialog .line {{ color: {colors.DIM}; width: 100%; margin-top: 1; }}
    PlotDialog ActionButton {{ margin-right: 2; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "import", "Import", show=False),
        Binding("o", "origin", "Origin", show=False),
        Binding("x", "cascade", "Cascade", show=False),
    ]

    def __init__(self, path: Path, found: PlotRead | None = None) -> None:
        super().__init__()
        self.path = path
        self.found: PlotRead | None = None  # busk's newest check
        self.base: tuple[str, tuple[float, float, float]] | None = None  # the frame it starts at
        self.audience = "-y"  # the frame asked for, on a first import
        self.origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.first = False
        self.checking = False  # a check is out
        self.stale = False  # the frame changed while it was out: check again
        self.cascade = True  # ticked, while the import needs it
        self.given = found
        self._picks = cache(lambda key: partial(self.pick, key))
        self.audiences = AudienceRow()
        self.origin_text = Static("", classes="origin")
        self.ask_origin = ActionButton("origin…", self.action_origin, id="plot-origin")
        self.audience_row = Horizontal(
            Static("audience", classes="label"),
            self.audiences,
            Static("where it is, the plot drawn from above", classes="aside"),
        )
        self.origin_row = Horizontal(
            Static("origin", classes="label"),
            self.origin_text,
            self.ask_origin,
            Static("where busk's downstage centre is in the plot", classes="aside"),
        )
        self.frame = Static("", classes="frame")
        self.check = Static("", classes="check")
        self.scroll = VerticalScroll(self.check)
        self.why = Static("", classes="why")
        self.tick = ActionButton("cascade", self.action_cascade, "tempo", id="plot-cascade")
        self.cascade_note = Static("", classes="cascade-note")
        self.cascade_row = Horizontal(self.tick, self.cascade_note, classes="cascade")
        self.line_text = Static("", classes="line")
        self.send = ActionButton("import", self.action_import, "go", id="plot-import")
        self.keys = Static("", classes="note")
        self.path_line = PathLine()

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "IMPORT PLOT"
            yield self.path_line
            yield self.audience_row
            yield self.origin_row
            yield self.frame
            yield self.scroll
            yield self.why
            yield self.cascade_row
            yield self.line_text
            with Horizontal(classes="buttons"):
                yield self.send
                yield ActionButton("cancel", self.action_cancel, id="plot-cancel")
            yield self.keys

    def on_mount(self) -> None:
        self.path_line.show(home_text(self.path))
        if self.given is not None:
            self.checked(self.given)
        else:
            self.ask()

    # ------------------------------------------------------------ the check

    def ask(self) -> None:
        """Have busk check the plot through the frame shown (the show's,
        before the first answer); one check at a time, and again once it is
        back if the frame changed meanwhile."""
        if self.checking:
            self.stale = True
            return
        self.checking = True
        if self.base is None:
            self.post_message(ReadPlot(self.path, self.checked))
        else:
            self.post_message(ReadPlot(self.path, self.checked, self.audience, self.origin))
        self.draw()

    def checked(self, found: PlotRead) -> None:
        """busk's answer: the first one says whether this is a first import
        and where the frame starts."""
        self.checking = False
        if self.base is None and found.problem is None:
            self.base = (found.audience, found.origin)
            self.audience, self.origin, self.first = found.audience, found.origin, found.first
        self.found = found
        if self.stale:
            self.stale = False
            self.ask()
        self.draw()

    @property
    def ready(self) -> bool:
        """Whether ``[import]`` runs: busk has checked the frame shown, and
        the import changes the show, nothing blocks it and, if it needs
        ``cascade``, it is ticked."""
        found = self.found
        if found is None or self.checking or not found.runs:
            return False
        return self.cascade or not found.cascade

    def line(self) -> Line:
        """``rig import "<path>"``, the frame's words where they moved from
        where they started, and ``cascade`` while it is ticked and needed."""
        audience = origin = None
        if self.first and self.base is not None:
            audience = None if self.audience == self.base[0] else self.audience
            origin = None if self.origin == self.base[1] else self.origin
        found = self.found
        cascade = found is not None and found.cascade and self.cascade
        return commands.rig_import(str(self.path), audience, origin, cascade)

    # ------------------------------------------------------------ drawing

    def draw(self) -> None:
        found = self.found
        asks = self.first and self.base is not None
        self.audience_row.display = self.origin_row.display = asks
        if asks:
            self.audiences.show(pick_chips(AUDIENCES, self.audience, self._picks))
            self.origin_text.update(origin_text(self.origin))
            self.frame.update("")
            if self.focused is None:
                self.audiences.focus()
        elif self.base is not None:
            self.frame.update(f"frame: {frame_text(*self.base)}, as the show keeps it")
        else:
            self.frame.update("")
        self.frame.display = bool(str(self.frame.content))
        if found is None:
            self.check.update(Text("busk is checking the plot…", style=colors.DIM))
        elif found.problem is not None:
            self.check.update("")
        else:
            self.check.update(Text(found.text, style=colors.FG))
        self.scroll.display = found is None or found.problem is None
        self.why.update(self._why())
        self.why.display = bool(self.why.content)
        needs = found is not None and found.cascade and found.problem is None
        self.cascade_row.display = needs
        self.tick.change(reverse=self.cascade)
        self.cascade_note.update(
            "removes the fixtures it takes out of everything that uses them"
            if self.cascade
            else "without cascade busk refuses the import"
        )
        self.line_text.update(Text(f"busk> {self.line().text}"))
        self.send.change(inert=not self.ready)
        keys = ["← →: audience", "o: origin"] if asks else []
        keys += ["x: cascade"] if needs else []
        keys += ["Enter: import", "Esc: cancel"]
        self.keys.update(" · ".join(keys))
        self.call_after_refresh(self.fit)

    def on_resize(self) -> None:
        self.call_after_refresh(self.fit)

    def fit(self) -> None:
        """The check's rows: :data:`CHECK_ROWS` at most, and no more than
        the rest of the dialog leaves on the screen, so that its buttons
        show on a small one."""
        box = self.query_one(Vertical)
        rest = box.outer_size.height - self.scroll.outer_size.height
        rows = max(MIN_ROWS, min(CHECK_ROWS, self.size.height - rest))
        if self.scroll.styles.max_height != Scalar.from_number(rows):
            self.scroll.styles.max_height = rows

    def _why(self) -> Text | str:
        """Why ``[import]`` does not run, if it does not."""
        found = self.found
        if found is not None and self.checking:
            return Text("busk is checking the frame shown…", style=colors.DIM)
        if found is None or self.checking:
            return ""
        if found.problem is not None:
            text = Text("busk cannot import it:\n", style=colors.RED)
            text.append(found.problem, style=colors.FG)
            return text
        if found.blocked:
            text = Text("busk refuses this import, even with cascade:\n", style=colors.RED)
            text.append("\n".join(found.blocked), style=colors.FG)
            return text
        if not found.changes:
            if found.first:
                return Text("nothing to import: the plot has no fixture busk can add", colors.DIM)
            return Text("nothing to import: the rig is already as the plot has it", colors.DIM)
        if found.cascade and not self.cascade:
            return Text("it removes fixtures that something uses: tick cascade", colors.AMBER)
        return ""

    # ------------------------------------------------------------ the keys

    def pick(self, audience: str) -> None:
        """A side of the plot for the audience: busk checks again."""
        if audience != self.audience:
            self.audience = audience
            self.ask()

    def on_audience_row_step(self, message: AudienceRow.Step) -> None:
        message.stop()
        if self.first and self.base is not None:
            keys = list(AUDIENCES)
            self.pick(keys[(keys.index(self.audience) + message.by) % len(keys)])

    def action_origin(self) -> None:
        """``[origin…]``: a form of three distances; busk checks again."""
        if not (self.first and self.base is not None):
            return

        def given(values: tuple[str, ...] | None) -> None:
            if values is None:
                return
            x, y, z = (float(value) for value in values)
            if (x, y, z) != self.origin:
                self.origin = (x, y, z)
                self.ask()

        fields = tuple(
            (axis, commands.exact(value + 0.0))
            for axis, value in zip("xyz", self.origin, strict=True)
        )
        note = "where busk's origin, downstage centre at deck height, is in the plot, in mm"
        self.app.push_screen(FormDialog("ORIGIN", fields, check_origin, note), given)

    def action_cascade(self) -> None:
        """``x``, or a click on ``[cascade]``: it shows only while the import needs it."""
        self.cascade = not self.cascade
        self.draw()

    def action_import(self) -> None:
        if self.ready:
            self.dismiss(self.line())

    def action_cancel(self) -> None:
        self.dismiss(None)


class AudienceRow(ButtonStrip, can_focus=True):
    """The audience's chips: a click picks one; ← → step while it has the
    focus (only on a first import)."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
    ]

    class Step(Message):
        def __init__(self, by: int) -> None:
            super().__init__()
            self.by = by

    def action_step(self, by: int) -> None:
        self.post_message(self.Step(by))

    def get_content_width(self, container: Size, viewport: Size) -> int:
        """Its chips on one row, a space between two."""
        return sum(button.label.cell_len + 1 for button in self.buttons) - 1
