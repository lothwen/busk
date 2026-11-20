# The File menu and the launcher: implementation plan

> Source: the user's idea of 2026-11-20: a File menu behind the top-left `busk` badge (New,
> Open, Save, Save as, Import script…), and a launcher when `busk-tui` starts without a show.
> The user answered the three questions the same day (§4). §5's calls are the plan's, open to
> veto. Checked on 2026-11-20 at 2cf566e.

## 1. Scope

**In:**
- A File menu on the status bar's `busk` badge: New…, Open…, Open recent…, Save, Save as…,
  Import script…, Quit.
- Save as makes a new show: the copy gets its own id, so its autosave and crash recovery are
  its own (§4, D1).
- Opening another show, or a new one, from inside the TUI. `busk-tui` stays as a parent
  process and starts one `busk run` after another (D3).
- A warning and a confirmation before the show changes while the output is live (D2).
- A list of recent shows, kept in the TUI's `state.json`.
- A launcher when `busk-tui` is given no show: the recent shows, `[new show…]`, `[open…]`.
- GAP-03, the typed session state, which the menu needs for the show's path.

**Out** (§10): a Close item that goes back to the launcher, forgetting a recent show, a
"recovery pending" mark in the launcher, a script imported as one undo step, Revert, and
changing shows without stopping the output.

## 2. What busk does today

- **One show per run.** `busk-tui SHOW` replaces itself (`os.execve`, `app.py` `main`) with
  `python -m busk run SHOW --frontend busk_tui.app:frontend`. Its own options travel in
  `BUSK_TUI_OPTIONS`. `busk run`'s root runs the output and starts an engine process and a
  console process. `frontend(show)` runs the TUI in the console process, and the run ends when
  it returns. A console that crashes is started again and calls `frontend` again.
- **`--standalone`** loads the show in the TUI's process (`Bridge.standalone`), with no
  watchdog, autosave or recovery.
- **The show is required.** `config.parse_arguments` makes `show` a positional argument;
  without it argparse exits 2.
- **The lines exist.**
  - `save [PATH]` (`Session.save`) writes the show, by default to its own file. It backs up the
    file it replaces and sets `meta.modified`, which is not an undo step. `save PATH` makes
    PATH the show's file. It keeps `meta.id`.
  - `source FILE` runs a console script and stops at its first error. Scripts are `.busk` by
    convention (`examples/festival.busk`).
  - Both take a quoted path with spaces (checked on 2026-11-20).
- **`busk new PATH [--title T] [--state-dir D]`** (`cli._new`) refuses a file that exists and
  writes the template show with the installation's sACN CID. `installation_cid` is in
  `busk.persistence.paths`, not in the public API.
- **Autosave and recovery are keyed by the show's id.**
  - The folder is `<stateDir>/autosave/<meta.id>/`. `AutosaveWorker` fixes it when it starts
    (`autosave.py:108`).
  - `session.json` holds `showPath` (`autosave.py:209`), but `read_recovery` never reads it.
  - The event log is `<stateDir>/logs/<show id>/<UTC start>.log`.
- **Undo** applies inverse ops (`ShowStep.inverse`). `save` changes `meta.modified` outside
  the timeline.
- **The status bar** (`widgets/frame.py`):
  - The ` busk ` badge (line 131) does nothing.
  - A click on the show's title renames the show (Phase 36), and a `*` after it marks unsaved
    edits.
- **Unsaved edits** come from a temporary parser of `info`'s text (`bridge.session_from_info`)
  until GAP-03 is built (`docs/dev/tui/engine-gaps.md`). `QuitDialog` offers Save and quit,
  Quit without saving, and Cancel.
- **Keys.** Ctrl+Q opens the quit dialog. Ctrl+Z and Ctrl+Y undo and redo (`prompt_key`).
  F1–F9 and Alt+1–9 switch pages, and F10 or Alt+0 toggles help.
- **The file picker** (`widgets/file_picker.py`, 2cf566e) is the profile picker's
  `[import…]`. Typing filters the list, files that cannot be imported are dimmed, and the
  preview comes from `bridge.read_profile` on a Textual thread worker
  (`BuskApp.on_read_profile`).
- **`state.json`** (`$XDG_STATE_HOME/busk-tui/`) holds the page and layout. `write_state`
  replaces the whole file.
- **Routes.** `RouteView.state` is `"ok"` while a route sends, and `None` when nothing runs
  the output (`--no-output`). Closing an sACN route sends Stream_Terminated.
- **The boundary** (`tests/tui/test_tui_boundary.py`): only `bridge.py` imports busk, and only
  names of `busk.__all__`. The plain modules import no Textual. `app.py` imports Textual only
  inside functions.
- **The pending plan** says that `busk-tui` making a show is not planned
  (`tui-pending-plan.md` §7). This plan replaces that line.

## 3. The design in one picture

The menu, from a click on the badge or Alt+F:

```
 busk ▾  show Club Night *   ● sACN 1  ● sACN 2                          21:47:05
┌ FILE ──────────────────┐
│ New…            Ctrl+N │
│ Open…           Ctrl+O │
│ Open recent…           │
│ Save            Ctrl+S │
│ Save as…               │
│ Import script…         │
│ Quit            Ctrl+Q │
└────────────────────────┘
```

Opening another show while the output is live and there are unsaved edits (D2):

```
┌ OPEN ───────────────────────────────────────────────────────────┐
│ Open "Festival Main Stage" (~/shows/festival.show)?             │
│ There are unsaved edits.                                        │
│ The output stops while the next show starts:                    │
│ 2 routes are sending (sACN 1, sACN 2).                          │
│                                                                 │
│ [s] Save and open   [o] Open without saving   [c] Cancel        │
└─────────────────────────────────────────────────────────────────┘
```

Two shows, one after the other (D3):

```
busk-tui (parent) ── starts ──▶ busk run club.show --frontend …   (root, engine, console + TUI)
     ▲                               │ File ▸ Open: the TUI writes {"open": ".../festival.show"}
     │                               │ to $BUSK_TUI_NEXT and quits; the run ends, the output stops
     └──────── reads the hand-off ◀──┘
busk-tui ── starts ──▶ busk run festival.show --frontend …
```

The launcher, `busk-tui` with no show:

```
 busk
 RECENT SHOWS                                   │ Club Night
 Club Night        ~/shows/club.show            │ ~/shows/club.show
 Festival Main     ~/shows/festival.show        │ 48 fixtures · 6 cue lists · 12 playbacks
 Old rig           ~/old/rig.show      missing  │ saved 2026-11-19 22:14
                                                │
 [new show…]   [open…]   [quit]                 │
```

## 4. Decisions (answered 2026-11-20)

- **D1. Save as gives the show a new id.** The copy is a show of its own. The file it was saved
  from stays as it was last saved.
- **D2. Opening a show while the output is live** shows a warning and asks the user to
  confirm.
- **D3. `busk-tui` stays as a parent process** and starts `busk run` as a child, instead of
  replacing itself.

## 5. Calls the user may veto

1. **`save PATH` is Save as, at the prompt too.** The menu's Save as sends the line, so the
   line carries D1:
   - `save PATH` to a file other than the show's own (compared as resolved paths) gives the show
     a new id, and sets `created` and `modified` to now. The title is kept.
   - `save`, and `save` to the show's own path, keep the id. A show that has no file yet keeps
     its id on its first save.
   - The reply says so in words: `saved copy.show as a new show; club.show stays as it was
     saved`.
   - The new id is not an undo step, as `meta.modified` is not.
2. **Autosave follows the new id.** When a save changes the id, the worker:
   - writes `cleanExit: true` to the old folder's `session.json`, because its edits went into
     the copy;
   - goes on in the new id's folder.

   The event log stays in the folder it opened in: one run, one log.
3. **GAP-03 as `engine-gaps.md` describes it.** `OfflineShow.session` and `LiveShow.session`
   return a new public `SessionStatus` with `showVersion`, `programmerVersion`, `dirty`, `path`,
   `undoSteps`, `redoSteps`, `nextUndo` and `nextRedo`. The TUI drops `session_from_info`.
4. **The menu.**
   - A click on the badge opens it, and so does Alt+F. The badge reads ` busk ▾ `.
   - Ctrl+N, Ctrl+O and Ctrl+S run New, Open and Save. Ctrl+Q stays the quit dialog.
   - Each key is checked in a pty: Textual's raw mode turns off XON/XOFF, so Ctrl+S should
     arrive.
   - Esc or a click outside closes the menu.
5. **Save** always sends `save`, even with nothing unsaved: it is harmless.
6. **Save as** uses the file picker in a save mode:
   - a folder listing and a name field, filled with the show's file name;
   - a name without a suffix gets `.show`;
   - an existing file asks "Replace x.show? busk keeps a backup of it." Saving to the show's
     own file is a plain save.
7. **Import script** uses the file picker in a script mode:
   - `.busk` files can be chosen, and other files are dimmed, as the profile picker does;
   - the preview is the file's first lines, which are usually its comment;
   - the dialog sends `source "<path>"`, and the reply goes to the log;
   - each line of the script is its own undo step, as with `source` at the prompt.
8. **Recent shows** are kept in `state.json` as `recent`:
   - newest first, at most 10, with no path listed twice;
   - each entry is `{path, title, opened}`, the path absolute and `opened` an ISO time;
   - the TUI adds a show when it is running (`EngineRunning`) and after a Save as works;
   - `write_state` merges what it writes instead of replacing the file;
   - a file that is gone is listed dimmed as `missing` and cannot be opened;
   - the launcher only reads the list.
9. **The hand-off.**
   - The parent makes a private temporary folder and sets `BUSK_TUI_NEXT=<folder>/next.json`.
     The environment reaches the console process, as `BUSK_TUI_OPTIONS` does.
   - To change shows, the TUI writes `{"open": "<absolute path>"}` there (atomically) and
     exits. `busk run` ends.
   - The parent reads the file, deletes it, and starts the next run.
   - Without the file, the parent exits with `busk run`'s code, as `busk-tui SHOW` does today.
10. **Options across shows.**
    - `--state-dir`, `--library`, `--iface`, `--threads`, `--no-log`, `--stats`, `--no-recover`
      and the TUI's own options apply to every show.
    - `--script` and `--values` apply only to the show given on the command line.
11. **Signals and exit codes.**
    - While a run goes, the parent ignores SIGINT. The TUI reads Ctrl+C as a key anyway.
    - The parent passes SIGTERM and SIGHUP on to the run, waits for it, and then starts nothing
      more.
    - It exits with the run's code, or 128 + N when a signal N killed the run.
    - The plain module that does this (`busk_tui/parent.py`) imports neither busk nor Textual.
12. **One confirmation dialog for New, Open and Open recent (D2).** It says both things that
    apply:
    - **Unsaved edits** add Save and open, and Open without saving. Save and open waits for the
      save's reply, as Save and quit does (`_quitting`). A failed save keeps the current show.
    - **Live output** means a route whose state is `ok`. The dialog says "The output stops while
      the next show starts" and names those routes.

    Without either, there is no dialog. With live output but no unsaved edits, it offers Open and
    Cancel.
13. **A show is checked before it is opened.**
    - The check is `bridge.read_show(path)` on a worker, as `read_profile` is: `load_show`, then
      compiling it as `busk run` does, in an `OfflineShow`, which opens nothing.
    - It gives `model.ShowRead`: the title, the file, the numbers of fixtures, cue lists and
      playbacks, when the file was saved, and its errors.
    - A show that does not load cannot be opened. The dialog lists why, and the current show
      runs on. The launcher uses the same check.
    - If `busk run` fails anyway after a hand-off, the parent stops and exits with its code. Its
      messages stay in the terminal, as with `busk-tui SHOW` today.
14. **New show.**
    - A form asks for the title and the file, which is the title as a file name in the current
      show's folder (or the working directory, in the launcher).
    - After the confirmation, it runs `python -m busk new PATH --title T [--state-dir D]` on a
      worker: the same file `busk new` writes, with the installation's CID, refusing a file that
      exists. No engine change is needed.
    - The hand-off then opens the new show.
15. **The launcher.**
    - `busk-tui` with no show, with or without other options, opens it.
    - It shows the recent shows, a preview of the selected one (`read_show`), and
      `[new show…]`, `[open…]` and `[quit]`.
    - Keys: ↑ ↓, Enter opens, `n` new, `o` open, `q` or Esc quits.
    - It is a Textual app of its own, with no show running behind it.
    - After a choice it exits, and the parent starts the run.
    - Quitting the TUI goes back to the shell, not to the launcher.
16. **`--standalone`** loops in its own process: when the app ends with a show to open next, a
    new `Bridge.standalone` and a new `BuskApp` start on it.
17. **Between shows**, the statistics `busk run` prints when it ends land on the terminal's main
    screen. They are seen after the last quit.

## 6. Phases

One conversation per phase, as in the pending plan. The engine comes first.

### Phase 1: the engine (GAP-03, GAP-55)

1. **GAP-03: `session`** on `OfflineShow` and `LiveShow`, returning `busk.SessionStatus` (the
   47th public name) with the fields of call 3.
   Verify:
   - on both facades, an edit sets `dirty` and adds 1 to `showVersion`;
   - undo and redo change the counts and the labels;
   - a save clears `dirty` and gives `path`;
   - the public API golden file.
2. **GAP-55: `save PATH` to another file is a new show** (D1, call 1). Change `Session.save`,
   and give the reply in words.
   Verify:
   - a save to the show's own path keeps the id; one to another file gives a new id, with
     `created` and `modified`;
   - `undo` after it keeps the new id (check that no step's inverse replaces `meta` whole);
   - the original file is unchanged on disk, and a later `save` writes the copy;
   - a show without a file keeps its id.
3. **Autosave follows the id** (call 2).
   Verify on a fake clock: edits, then a Save as, then no clean exit. `read_recovery` finds
   nothing for the original's id, and the copy's edits under the copy's id.

   Then with processes:
   - `busk run a.show`, `save b.show`, an edit, then `kill -9` the run;
   - `busk run a.show` starts clean;
   - `busk run b.show` recovers the edit.
4. **Docs.** `docs/console.md` (`save PATH`), `docs/library.md` (`session`), the spec's save
   section, `engine-gaps.md` (GAP-03 done, GAP-55 added and done), CHANGELOG.

**Done** 2026-11-20, on 2cf566e. The Done notes of GAP-03 and GAP-55 in `engine-gaps.md` have
the details. Code: `Session.save` and `SessionStatus` (`src/busk/session/session.py`), the
facades' `session` (`src/busk/runner.py`), `AutosaveWorker._saved`, `Recovery.showPath` and
`claim` (`src/busk/persistence/autosave.py`), `_saved_as` (`src/busk/process/console_host.py`).
What differs from the steps above, or goes beyond them:

- **`SessionStatus.path` is absolute** (`os.path.abspath`), so Phase 2's recent shows can keep
  it as it is.
- **One moment.** The timeline now moves before the session publishes its snapshot (a `then`
  callable on `_commit` and `_set_programmer`). Before, a show step went on the timeline after
  the edit was published, and an undo or redo moved it after its change was.
- **A console restarted after a crash comes back on the copy** (vetoable; not in call 2).
  Without this, a console killed after a Save as reloads the show named on the command line
  and puts the original back on stage. The old folder's `session.json` already names the copy
  (`showPath`). A console started with `--restarted` follows it, to the last copy, and says
  `club.show was saved as copy.show: recovering that`. A console that is not restarted first
  points its own folder back at its file (`claim`), so a copy left by an earlier run is never
  followed.
- **A bug found and fixed:** an edit made within 0.5 s after a save, before the worker's next
  pass, was taken as saved. It was never autosaved, and a clean quit did not keep it. The plan's
  own process check hit it. `SessionSnapshot` now carries the version and stamp the last save
  wrote (`savedVersion`, `savedStamp`).
- **The TUI is untouched:** `session_from_info` stays until step 5.

### Phase 2: the File menu (no process change)

5. **The bridge reads `session`.** Remove `session_from_info` and the `info` runs behind it.
   `SessionState` gains `path`, and the quit dialog always knows about unsaved edits.
   Verify: the tests on the `*` and the quit dialog; `FakeBridge`.
6. **`FileMenu`** on the badge and Alt+F (call 4), with Save, Save as…, Import script… and Quit
   in this phase, and Ctrl+S. New, Open and Open recent come in Phase 3, so no item is ever
   grey.
   Verify: pilot tests (a click on the badge, Alt+F, Esc, a click outside); a pty run for
   Alt+F and Ctrl+S.
7. **The file picker's modes** (calls 6 and 7): profile (as today), save (a name field) and
   script (first lines). Each mode decides which files can be chosen and what the preview reads.
   Verify: `tests/tui/test_tui_file_picker.py` gets a test per mode. Save as writes a file with
   a new id and the replace question; Import script runs `source` and shows its reply.
8. **Recent shows are written** (call 8).
   Verify, in `test_tui_config.py`:
   - a merge keeps the page, the layout and the list;
   - the cap of 10, and no path twice;
   - a file that cannot be written is ignored;
   - an old `state.json` reads.
9. **Docs.** `docs/tui/guide.md`: the badge in "The screen", "Keys", and `recent` in "Files".
   The TUI spec's status bar (§5).

**Done** 2026-11-20, on 4379878. Code: `session_state` and the reader's `session` read
(`src/busk_tui/bridge.py`), `SessionState.path` (`model.py`), `FileMenu`
(`src/busk_tui/widgets/file_menu.py`), the picker's `Mode`, `KINDS`, `save_name`, `save_text`
and `script_text` (`widgets/file_picker.py`), `action_file_menu`, `save_as` and `import_script`
(`shell.py`), `commands.save_as` and `commands.source`, `config.remember_show` and the merging
`write_state`. Tests: `tests/tui/test_tui_file_menu.py` (new, one test on the real engine), the
modes in `test_tui_file_picker.py`, the recent shows in `test_tui_config.py`, the session in
`test_tui_bridge.py` and `test_tui_bridge_live.py`. What differs from the steps above, or goes
beyond them:

- **An engine fix:** `save "<path>"` kept the escapes of a quoted path (`\"`, `\\`), so the
  menu's Save as, which quotes as every TUI line does, would have written another file than the
  one named. The contract test found it. `_cmd_save` now reads one quoted path as a token, as
  `source` does; an unquoted path is the rest of the line, as before. §2's "both take a quoted
  path with spaces" held, but not for these two characters.
- **Alt+F arrives only from a terminal that reports Alt with the key** (the kitty keyboard
  protocol, which Textual asks for: kitty, for one). Textual reads `Esc f`, what xterm, VTE and
  tmux send for Alt+F, as Ctrl+→ (iTerm's word keys), so there the prompt's cursor moves a word
  instead. The guide says so and points to the badge. Checked in a pty: `ESC [102;3u` opens the
  menu, `ESC f` does not. See §9: Alt+1–9 have the same trouble.
- **Ctrl+S goes through the prompt's key hook** (`prompt_key`), as Ctrl+Z does, not an app
  binding, so a save never overtakes a line typed just before it. It works whatever the prompt
  holds, and not while a dialog or the menu is open. Checked in a pty: it arrives.
- **Saving, the picker's keys** (call 6 left them open): the field is the name, and the cursor
  starts on no row. ↑ ↓ put it on a row, and a show file's name goes into the field; typing takes
  it off the rows. Enter goes into the folder the cursor is on, else saves as the name. → and ←
  go into and up from folders (onto no row), and Backspace on an empty name goes up. The preview
  says what Enter would do (the show's own file, a file it replaces, or a copy, "a show of its
  own: club.show stays as it was saved").
- **A name that does not end in `.show` or `.json`** (in any case, as busk reads them) gets
  `.show`, not only a name with no suffix: `club.v2` saves `club.v2.show`, as busk would refuse
  `club.v2`.
- **The replace question** is the app's, asked after the picker closes, with the line it
  confirms (`ConfirmDialog`); No goes back to the screen, not to the picker.
- **The recent shows are written when the session's file changes**: the first read of a show
  with a file, and a Save as. That is call 8's two moments, with the path the session gives (the
  bridge's `EngineRunning` has no path). The title is the status bar's then.
- **Both pickers start in the show's folder** (Import script was not said), or where busk-tui
  runs, with an empty name, for a show without a file.
- **The menu does not dim the frame** (`FileMenu { background: transparent }` in `busk.tcss`,
  which outranks the dialogs' rule). Its keys do nothing while it is open but its own, Alt+F and
  Esc. The help overlay lists Ctrl+S and Alt+F; the key legend is as it was.
- **The quit dialog's "cannot tell"** stays for the moment before the bridge's first look,
  when no session has come yet.

Checks: the whole suite (`-n 6`, 9:43) 7,179 passed, 1 skipped, 1 failed:
`test_waveforms.py::test_vectorised_equals_the_scalar_transcription`, untouched here, where
Hypothesis found a `phi` of -1.45e-106, whose phase rounds to 1.0, past the test's own scalar
curve (`min()` of nothing). 19 mutations, all caught. ruff, format and mypy clean. A pty run
under `busk run`: the badge, Ctrl+S, Alt+F as kitty sends it, Save as a copy, Import script,
the quit dialog and `recent` in `state.json`.

### Phase 3: one show after another

10. **The parent** (D3, calls 9–11, 16): `app.main` starts `busk run` as a child through
    `busk_tui/parent.py` instead of `os.execve`. `--standalone` loops in its own process.
    Verify:
    - unit tests with a fake runner: a hand-off starts the next show, no hand-off exits with the
      code, a signal is passed on, 128 + N;
    - `test_tui_host.py` updated;
    - the boundary test lists `parent` as plain;
    - a pty run on the real `busk run`: Open B, B's title is in the status bar, and quitting
      leaves the shell with code 0.
11. **`bridge.read_show`** and `model.ShowRead` (call 13), and the file picker's open-show
    mode with that preview.
    Verify: a good show, one with errors, one that does not compile, a file that is not a show.
12. **New…, Open… and Open recent…** in the menu, with Ctrl+N and Ctrl+O, the confirmation
    dialog (call 12), the New form (call 14) and the hand-off.
    Verify, as e2e tests on `FakeBridge`:
    - each way through the dialog;
    - the live-output warning appears only with a route in state `ok`;
    - Save and open waits for the save, and a failed save keeps the show;
    - a show that does not load is refused and the current one runs on;
    - New refuses a file that exists.
13. **Docs.** The guide's new section "Opening another show": the output stops between shows.
    The `tui-pending-plan.md` §7 line on `busk-tui` making shows is updated. CHANGELOG.

**Done** 2026-11-20, on 4643af4. Code: `src/busk_tui/parent.py` (new: `run`, `hand_off`,
`read_next`, `NEXT`); in `app.py`, `main` (`parent.run` instead of `os.execve`), `frontend`
(`opens`, the hand-off) and `_standalone` (the loop); `config.busk_run_command(options, show)`
with `Options.first`, `config.busk_new_command`, `state_dir` in `BUSK_TUI_OPTIONS`,
`config.RecentShow` and `recent_shows`; `bridge.show_read`, `Bridge.read_show`, `model.ShowRead`,
`controls.ReadShow`; the picker's `open` mode and `show_text`; `widgets/show_dialogs.py` (new:
`OpenDialog`, `NewShowDialog`, `RecentList`, `RecentDialog`, `file_name`, `new_path`); in
`shell.py`, `new_show`, `open_show`, `open_recent`, `_check_open`, `_confirm_open`, `_make_show`,
`_open` and `next_show`, and Ctrl+N and Ctrl+O in `prompt_key`. Tests:
`tests/tui/test_tui_parent.py` and `tests/tui/test_tui_open.py` (new), `tui_handoff_frontend.py`
(new) with four new tests in `test_tui_host.py`, `show_read` in `test_tui_bridge.py`, the open
mode in `test_tui_file_picker.py`, the options in `test_tui_config.py`. What differs from the
steps above, or goes beyond them:

- **Open recent… leaves out the show that runs**: opening it again would be Revert (§10).
  Open… still takes the show's own file, and opens it again from disk.
- **`RecentList` and `RecentDialog` are built here** (`widgets/show_dialogs.py`), since Open
  recent… needs them. Phase 4's launcher reuses the list and the preview (`show_text`).
- **A recent row** reads `title  missing  path`: the mark comes before the path, which the row
  cuts at its end when it is long.
- **New…'s file name** is the title's words in lower case, joined by `-` (`Late Night` is
  `late-night.show`), in the show's folder. It follows the title as it is typed, until the file
  is typed in. The form refuses an empty title and a file that exists. `busk new` refuses one
  too (a file made meanwhile), and its words go to the log.
- **`--title=T`**, not `--title T`: a title that starts with `-` would be read as an option.
- **`--state-dir` travels in `BUSK_TUI_OPTIONS`**, for `busk new`'s sACN CID under `busk run`.
- **A frontend without busk-tui's parent** (`busk run --frontend busk_tui.app:frontend`, typed
  by hand) has no `$BUSK_TUI_NEXT`: New…, Open… and Open recent… say so in the log and do
  nothing.
- **Before the session is known** (the bridge's first look), the confirmation says that the TUI
  cannot tell whether there are unsaved edits and offers Save and open, as the quit dialog does.
- **A show that does not load** gets the same dialog, with busk's errors (8 at most) and Close.
- **The route names** in the dialog are the status bar's (`sACN·U1`), not `sACN 1`.
- **Only a run that ends with 0** starts the next show; another code ends the parent, even after
  a hand-off.
- **The parent's SIGINT handler** does nothing but is a Python function, not `SIG_IGN`, which
  `busk run` would inherit through exec. Checked: the run's Python still raises
  KeyboardInterrupt.
- **A signal told twice is harmless** (§8): `busk run`'s root takes a second SIGTERM or SIGHUP
  as the first (`_terminate`; `_kill_at` is set once), so the parent passes on a hang-up that
  reached the run too. Checked in a pty: a hang-up, and a SIGTERM to `busk-tui` alone, each end
  the whole tree, with nothing left running. After a hang-up the exit code is 120, CPython's when
  it cannot flush onto the terminal that went; `busk run` alone ends the same way.
- **Textual three times in one process** (§8, `--standalone`): keys, the mouse and the screen
  work in each app, in a pty.

Checks: the whole suite (`-n 6`, 9:42) 7,219 passed, 1 skipped, 1 failed: Phase 2's
`test_waveforms.py::test_vectorised_equals_the_scalar_transcription`, untouched here; then
`tests/tui` again on the final sources, 1,865 passed. 22 mutations, all caught. ruff, format and
mypy clean. Two pty runs: under `busk run`, Alpha sending sACN to localhost, Ctrl+O Bravo through
the warning (Bravo's title about 1 s later), Ctrl+N "Late Night", Alt+F (kitty) Open recent
Bravo, quit with 0; with `--standalone`, Ctrl+N, a click on the badge, Open recent, quit with 0.

### Phase 4: the launcher

14. **The options.** `show` becomes optional, and with no show the launcher runs before the
    loop of Phase 3.
    Verify: config tests; `busk-tui --standalone` with no show.
15. **The launcher** (call 15). A `RecentList` widget is shared with Open recent….
    Verify:
    - pilot tests: an empty list, a missing file, Enter, `n`, `o`, `q`;
    - a pty run: `busk-tui` with no show, choose a recent one, open another from the menu, quit.
16. **Docs.** The guide's "Start", the README's `busk-tui` lines, CHANGELOG.

### Phase 5: the user's check

17. **On the rig.**
    - Start `busk-tui` with no show and open the festival show, with the TupperDMX simulator
      running.
    - Change shows while the output is live, and watch the fixtures during the gap.
    - Save as, `kill -9` the run, and check that recovery goes to the copy and not to the
      original.

    Findings go to §9.

## 7. Compatibility

- **`save PATH` to another file changes meaning.** The copy is a new show. A script that made a
  backup with `save backup.show` now makes a new show; the CHANGELOG says so. busk is 0.1.x.
- **`busk-tui SHOW` behaves as today,** with one more process, the parent.
- **An old `state.json`** (page and layout only) still reads.
- **`SessionStatus` is added** to the public API; nothing is removed.

## 8. Risks

- **The terminal between two Textual apps.** The launcher must give the terminal back
  completely before `busk run`'s TUI takes it. A pty test catches leftovers.
- **Signals.** The parent and the run share the terminal and its process group, so a hang-up
  reaches both. The run must not be told twice.
- **How long the output stops** between shows (start-up, compile, recovery, opening routes) on
  a large show. It is measured in Phase 5.
- **Textual twice in one process** (`--standalone`'s loop). Global state left by the first app
  is checked in Phase 3.
- **The perf gate flaps** under load (see the memory of earlier phases): new e2e tests make
  the suite longer.

## 9. Found while planning (busk, not fixed here)

- **A show file copied in the shell keeps its id.** Recovery is keyed by the id alone.
  `session.json` holds `showPath` (`autosave.py:209`), but `read_recovery` never compares it. So
  a crash while editing the copy restores its edits into the original the next time that file
  opens.
  - D1 closes this for Save as, but not for `cp`.
  - The fix: `read_recovery` compares the path and says why it skipped a recovery.
- **Alt+digit does not switch pages in most terminals** (found in Phase 2). The guide says to
  use Alt+1–9 over SSH, where F-keys may not arrive. Textual reads `Esc 1` … `Esc 0`, what a
  terminal without the kitty keyboard protocol sends, as the characters macOS's Option key
  types (`¡`, `™` …), so they go into the prompt instead. They work from a terminal that speaks
  the protocol (kitty). Alt+F, the File menu's key, has the same limit.

## 10. After this

- Close: back to the launcher without quitting.
- Forgetting a recent show from the list.
- A "recovery pending" mark on launcher rows, read from the show's `session.json`.
- Import script as one undo step, inside an undo group.
- Revert: open the show again from disk.
- Import profile in the File menu, beside F3's picker.
- Changing shows without stopping the output: the engine loading a new show while it runs.
