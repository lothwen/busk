"""The profile picker (``docs/plans/tui-rig-plan.md`` §4 calls 7 and 8, §6.6):
what ``fixture add`` takes, from ``ShowModel.choices``, with a filter.

A modal dialog, because its filter is typed and only a modal has the keyboard.
It chooses and sends nothing: the form that opened it does. The show's own
profiles come first, marked. ↑ ↓ move, Enter or a click chooses, Esc cancels.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from busk_tui import colors
from busk_tui.model import ProfileChoice
from busk_tui.widgets.dialogs import dialog_css

MARK: Final = "●"
MAKER_CELLS: Final = 16
NAME_CELLS: Final = 28
MODES_CELLS: Final = 20
ROWS: Final = 12
PAGE: Final = ROWS - 1


def modes_text(choice: ProfileChoice) -> str:
    """Each mode and the channels it takes: ``3ch (3), 8ch (8)``."""
    return ", ".join(f"{mode.name} ({mode.footprint})" for mode in choice.modes)


def choice_text(choice: ProfileChoice) -> Text:
    """A row of the list: the mark of a show's own, the maker, name and modes."""
    text = Text(no_wrap=True)
    text.append(MARK if choice.source == "show" else " ", style=colors.CYAN)
    for words, cells, style in (
        (choice.manufacturer, MAKER_CELLS, colors.DIM),
        (choice.name, NAME_CELLS, colors.FG),
        (modes_text(choice), MODES_CELLS, colors.MID),
    ):
        piece = Text(words, style=style)
        piece.truncate(cells, overflow="ellipsis", pad=True)
        text.append(" ")
        text.append_text(piece)
    return text


def matches(choice: ProfileChoice, words: Sequence[str]) -> bool:
    """Whether the maker and name hold all of ``words``, in any case."""
    text = f"{choice.manufacturer} {choice.name}".casefold()
    return all(word in text for word in words)


class ProfileDialog(ModalScreen[str | None]):
    """Closes with a profile's name, or ``None`` (see the module docs). It
    starts on ``chosen``, else the first."""

    DEFAULT_CSS = (
        dialog_css("ProfileDialog")
        + f"""
    ProfileDialog > Vertical {{ width: 76; max-width: 100%; }}
    ProfileDialog Input {{ width: 100%; margin-bottom: 1; }}
    ProfileDialog OptionList {{
        height: {ROWS}; padding: 0; border: none; background: {colors.BG};
        scrollbar-size-vertical: 1;
    }}
    ProfileDialog OptionList > .option-list--option-highlighted {{
        background: {colors.SEL}; text-style: none;
    }}
    ProfileDialog .none {{ height: {ROWS}; color: {colors.DIM}; }}
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("pageup", f"move(-{PAGE})", "Page up", show=False),
        Binding("pagedown", f"move({PAGE})", "Page down", show=False),
    ]

    def __init__(self, choices: Sequence[ProfileChoice], chosen: str | None = None) -> None:
        super().__init__()
        self.choices = tuple(choices)
        self.chosen = chosen
        self.shown: tuple[ProfileChoice, ...] = ()
        self.field = Input(placeholder="filter", compact=True)
        self.list = OptionList()
        self.list.can_focus = False  # the filter keeps the keyboard
        self.none = Static("", classes="none")

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "PROFILE"
            yield self.field
            yield self.list
            yield self.none
            yield Static(
                f"{MARK} in this show · ↑ ↓: move · Enter: choose · Esc: cancel", classes="note"
            )

    def on_mount(self) -> None:
        self._fill(self.chosen)
        self.field.focus()

    def _fill(self, keep: str | None) -> None:
        """The profiles the filter finds, on ``keep`` if it is one, else the first."""
        words = self.field.value.casefold().split()
        self.shown = tuple(choice for choice in self.choices if matches(choice, words))
        names = [choice.name for choice in self.shown]
        self.list.clear_options()
        self.list.add_options([Option(choice_text(choice)) for choice in self.shown])
        self.list.highlighted = (names.index(keep) if keep in names else 0) if names else None
        self.list.display = bool(names)
        self.none.display = not names
        self.none.update(Text(f"no profile has {self.field.value.strip()!r}"))

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        index = self.list.highlighted
        self._fill(None if index is None else self.shown[index].name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        index = self.list.highlighted
        if index is not None:
            self.dismiss(self.shown[index].name)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(self.shown[event.option_index].name)

    def action_move(self, by: int) -> None:
        index = self.list.highlighted
        if index is not None:
            self.list.highlighted = index + by  # the list stops it at its ends

    def action_cancel(self) -> None:
        self.dismiss(None)
