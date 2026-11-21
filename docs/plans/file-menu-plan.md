# The File menu and the launcher: implementation plan

> Source: the user's idea of 2026-11-20: a File menu behind the top-left `busk` badge (New,
> Open, Save, Save as, Import script…), and a launcher when `busk-tui` starts without a show.
> The user answered the three questions the same day (§4). §5's calls are the plan's, open to
> veto. Checked on 2026-11-20 at 2cf566e.
> Extended on 2026-11-21 at d442851: §10's items became Phases 6–10, with calls 18–25 and the
> facts at the end of §2.

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
- Added on 2026-11-21 (Phases 6–10): Close, back to the launcher; forgetting a recent show; a
  mark on the recent shows busk would recover; Import script as one undo step, with a bar and
  each line shown as it runs; Import profile… in the menu.

**Out:** Revert, changing shows without stopping the output, and stopping an import midway
(§10).

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

**For §10's items** (checked on 2026-11-21 at d442851):

- **Undo groups take programmer steps only** (`session/timeline.py`): a show step closes the
  group, so a group cannot hold a script. Each line of a `source` script is its own step.
- **The history keeps 1,000 steps** (`timeline.LIMIT`). `examples/festival.busk` (2,189 lines)
  fills it, so an import loses every step from before it. Run line by line on an
  `OfflineShow`, it takes 5.1 s.
- **`source` runs the whole script under the console's lock** (`Console._lines`) and replies
  once, at the end. `busk run --script` and the facades' `run_script` go through the same loop.
  The TUI's Import script sends `source "<path>"` (`commands.source`).
- **The bridge** runs lines one at a time on its ordered lane, and the controls' performance
  lines on another (`Bridge.send`). A performance line runs while a script holds the lock.
- **The log** keeps 2,000 entries (`widgets/log.py`, `MAX_LINES`).
- **Recovery is not public.** `read_recovery` and the autosave folder's name are inside
  `busk.persistence`. `session.json` says `cleanExit: false` while a run goes, not only after a
  crash.
- **The launcher only reads `recent`.** The hand-off file holds only `{"open": …}`
  (`parent.read_next`). The launcher runs in `app.main` before `parent.run`, with the default
  signal handlers.
- **Ctrl+W** deletes a word in the prompt (Textual's `Input`).
- **The profile picker's `[import…]`** opens `FileDialog` in profile mode and sends
  `profile import "<path>"` (`ProfileDialog.action_import`).

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

Importing a script (calls 20 and 21), the bar in the hint row:

```
 festival.busk:811  record cue 101/6 "Breakdown"
 recorded cue 101/6 "Breakdown"
 festival.busk:812  record cue 101/7 "Final Drop"
 recorded cue 101/7 "Final Drop"
 > _
 IMPORT festival.busk  ━━━━━━━━━━━━╸──────────────────  812 / 2189 · lines typed now wait
```

A recent show that busk would recover (call 24):

```
 Club Night        recovers  ~/shows/club.show  │ Its last run did not end cleanly
                                                │ (2026-11-20 22:14): busk recovers the
                                                │ programmer and its unsaved edits.
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

**Calls for §10's items** (2026-11-21, Phases 6–10):

18. **A script is one undo step (GAP-56)**, wherever it runs: `source FILE` at the prompt or
    from the TUI, `busk run --script`, and the facades' `run_script`.
    - The timeline gets a `ScriptStep`. It holds the show ops of the script's lines (forward in
      order, inverse in reverse order), and the programmer before the first line and after the
      last, as a programmer step keeps it. Undo puts both back in one published snapshot, and
      redo does the same the other way.
    - Its label is the line, `source festival.busk`, so undo replies `undid: source
      festival.busk`.
    - A nested `source` joins the outer script's step. A script that changes nothing leaves no
      step.
    - A script that stops at an error leaves one step for the lines that ran, so one Ctrl+Z
      takes back a half import.
    - An `undo` or `redo` line in a script closes the step so far, as it closes an undo group.
      The lines after it make a step of their own.
    - The steps from before a long script stay in the history (§2: festival.busk fills it
      today).
19. **A script reports each line as it runs (GAP-57).** `run_script(path, *, each=None)` on both
    facades calls `each(number, total, line, reply)` after each line of the file, on the thread
    that runs the script. `total` is the file's number of lines. A nested `source` is one line,
    with its whole reply. No new public name. The engine runs the lines, not the TUI, so they
    run as `source` runs them: under the console's lock, with nested `source`, `quit` and the
    one undo step.
20. **Import script runs the script through the bridge**, not as a `source` line.
    - `Bridge.run_script(path)` queues it on the ordered lane. It runs after the lines sent
      before it, and the lines sent after it wait for it.
    - Each line shows in the log as it runs, with its place (`festival.busk:812`), then its
      reply, as a typed line does. Blank lines and comments are not shown.
    - The lines arrive at the bridge's drain rate, many at a time. The log keeps its 2,000
      entries, so the first lines of a long script scroll out.
    - The end says what happened: `imported festival.busk: 2,189 lines (Ctrl+Z undoes it)`, or
      the failing line with busk's words, then `stopped at line 812 of 2,189 (Ctrl+Z undoes the
      lines before it)`.
21. **The import bar** takes the hint row's place, under the prompt, while a script runs:
    `IMPORT festival.busk`, a bar, `812 / 2189` (lines of the file) and `lines typed now wait`.
    - The TUI stays usable: the pages, the reads, and the performance controls, which run beside
      a script. Lines typed meanwhile wait their turn.
    - New…, Open…, Open recent… and Close say in the log that a script is importing, and do
      nothing until it ends.
    - There is no stop: a script runs to its end or to its first error (§10).
22. **Import profile…** goes in the File menu after Import script…, with no key.
    - It opens the profile picker's file picker (`FileDialog` in profile mode), on the last
      profile file chosen in this run (`ProfileDialog.last`), else in the show's folder.
    - Then it sends `profile import "<path>"`, and the reply goes to the log.
23. **Forgetting a recent show.** Delete, or `d`, on a row takes it off `recent` at once,
    without a question, in the launcher and in Open recent…. The file is not touched.
    - `config.forget_show(state, path)` writes it, merging as `write_state` does. The launcher
      now writes `state.json` (call 8 said it only reads it).
    - The row goes and the cursor stays where it was. The notes add `Delete: forget`.
24. **The recovery mark (GAP-58).** busk tells whether `busk run PATH` would recover a show.
    - `busk.pending_recovery(path, *, state_dir=None)` returns `busk.PendingRecovery` or `None`.
      It has `written`, when the last run last wrote its `session.json`, and `edits`, whether an
      autosave newer than the file comes back. It follows `read_recovery`'s rules, without
      `--restarted`'s force. These are the 48th and 49th public names.
    - The TUI reads it with `bridge.recovery_read(path, state_dir)`, giving `model.Recovery`.
      The list reads each row's on a worker when it opens (it reads the file's id, not the whole
      show), and a row's mark comes when it is known.
    - A row whose show would be recovered reads `title  recovers  path`, with the mark in amber.
      The preview adds "Its last run did not end cleanly (2026-11-20 22:14): busk recovers the
      programmer and its unsaved edits." Without `edits`, the line ends at "the programmer".
    - With `--no-recover` there is no mark: busk-tui passes it to `busk run`, which then
      recovers nothing.
    - A show that another `busk run` runs right now is marked too, since its `session.json` says
      what a crash leaves. A copy made with `cp` (§9) is marked when busk would recover into it.
25. **Close** goes in the File menu before Quit. It goes back to the launcher.
    - No key: Ctrl+W deletes a word in the prompt.
    - The confirmation is Open's (call 12), worded for closing: Save and close, Close without
      saving, Cancel. With live output it says "The output stops until a show is opened" and
      names the routes.
    - The TUI hands over `{"close": true}` in `$BUSK_TUI_NEXT` and quits. `parent.read_next`
      reads it as `CLOSE`, and `parent.run` returns, saying the run closed. `main` then runs the
      launcher again, outside the parent's signal handlers as at the start, and `parent.run` on
      the show chosen. Quitting the launcher exits with 0.
    - Only a run that ends with 0 goes back to the launcher, as only such a run opens the next
      show (Phase 3).
    - `--values` and `--script` do not apply again: a show chosen after a Close is opened, not
      given (call 10).
    - `--standalone` runs the launcher in its own process too, then goes on with its loop.
    - Without busk-tui's parent, Close says so in the log and does nothing, as Open… does.
    - A busk-tui started with a show closes to the launcher too.

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

**Done** 2026-11-21, on fc84ee2. Code: `src/busk_tui/launcher.py` (new: `Launcher`,
`LauncherScreen`); in `app.py`, `main` runs it when `options.show` is `None` and puts its choice
in `options.show`; `config.parse_arguments`' `show` is `nargs="?"`; `RecentShows` in
`widgets/show_dialogs.py` (new: the list, the preview and the reading, taken out of
`RecentDialog`, which now shows one), and `OpenDialog`'s `running`. Tests:
`tests/tui/test_tui_launcher.py` (new), the launcher in `test_tui_host.py` (busk run, quitting, a
crash, `--standalone`), `test_tui_config.py`, `test_tui_boundary.py`, and Open recent's height in
`test_tui_open.py`. What differs from the steps above, or goes beyond them:

- **The launcher's choice is the show given**, so `--values` and `--script` apply to it (call 10
  says "the show given on the command line"; without one, the launcher's stands in for it).
- **Its choices read `[n New show…]  [o Open…]  [q Quit]`**, the dialogs' `Choice`, with their
  keys, and clicks work. Its badge is ` busk `, without `▾`: it has no menu.
- **Ctrl+C quits it too**, beside `q` and Esc, since nothing runs (Textual's own Ctrl+Q also
  does).
- **New show in the launcher** asks no confirmation (nothing runs) and runs `busk new` with
  `--state-dir`; when `busk new` refuses, its words show in red under the choices.
- **A show that does not load** gets Phase 3's dialog with busk's errors, without "The show that
  runs now goes on.".
- **Enter reads the show again**, as Open recent… does, even when the preview has read it.
- **It runs in busk-tui's own process**, the parent, which now imports busk (through
  `bridge.show_read`) and Textual before it starts `busk run`. A pty run checked the hand-over:
  the launcher pops the kitty keyboard mode it pushed, turns the mouse off and leaves the
  alternate screen before the run's TUI takes the terminal, and nothing is written between them.
- **The debug log is set up once** (`_debug_log`), as the launcher and then `--standalone` each
  set it up.
- **The empty launcher** says "No recent shows: busk-tui lists the shows it opens." and drops the
  `↑ ↓` note.

Checks: the whole suite (`-n 6`, 9:28) 7,234 passed, 1 skipped, 2 failed: Phase 2's
`test_waveforms.py::test_vectorised_equals_the_scalar_transcription`, and
`test_tui_program.py::test_a_drag_that_pauses_opens_a_new_undo_group_when_it_moves_on`, F2's drag
under load (two hovers took longer than its 0.5 s pause; it passes alone, three times). Both are
untouched here. Then `tests/tui` again on the final sources, 1,879 passed. 20 mutations, 19
caught; the one missed, the list's `focus()`, is Textual's auto-focus doing the same. ruff,
format and mypy clean. Pty runs: under `busk run`, the launcher, Enter on Club Night, Ctrl+O
Festival, quit with 0; with `--standalone`, `n` "Late Night", a click on the badge, Open recent
Club Night, quit with 0; the launcher at 80×24, empty, and `q` with 0.

### Phase 5: the user's check

17. **On the rig.**
    - Start `busk-tui` with no show and open the festival show, with the TupperDMX simulator
      running.
    - Change shows while the output is live, and watch the fixtures during the gap.
    - Save as, `kill -9` the run, and check that recovery goes to the copy and not to the
      original.

    Findings go to §9.

### Phase 6: the engine (GAP-56, GAP-57, GAP-58)

18. **GAP-56: a script is one undo step** (call 18). A `ScriptStep` in `timeline.py`.
    `Console._lines` opens it for the outermost script and closes it at the end, after an error
    or a `quit` line too. The session's undo and redo apply it in one snapshot.
    Verify:
    - `source` of a script that patches, records and selects: one `undo` puts the show and the
      programmer back, and one `redo` brings both back; `SessionStatus.undoSteps` grows by 1;
    - a nested `source`; a script that fails at line N (one step for the lines before it); a
      script that changes nothing (no step); an `undo` line inside a script;
    - `busk run --script`, and `run_script` on both facades;
    - the steps from before `examples/festival.busk` are still there after it;
    - a performance line that runs beside the lock while a script runs: find which lines can,
      and whether they push a step, and write the rule in GAP-56.
19. **GAP-57: `run_script`'s `each`** (call 19).
    Verify:
    - one call per line, in order, with `total`;
    - a failing line is reported before `ScriptError` is raised;
    - a nested `source` is one call;
    - on `LiveShow`, the calls come as the lines run, not all at the end.
20. **GAP-58: `busk.pending_recovery`** (call 24).
    Verify:
    - no `session.json`; a clean exit; a crash with and without a newer autosave; a file that
      is not a show; the default `state_dir`; the public API golden file;
    - with processes, as Phase 1 did: `kill -9` a run, then `pending_recovery` says so, and
      `busk run` recovers; after a clean quit it says `None`.
21. **Docs.** `docs/console.md` (`source` is one undo step), `docs/library.md` (`run_script`'s
    `each`, `pending_recovery`), the spec's §15.4, `docs/faq.md` ("How far back does `undo`
    go?"), `engine-gaps.md` (GAP-56 to GAP-58), CHANGELOG.

**Done** 2026-11-21, on d442851. The Done notes of GAP-56 to GAP-58 in `engine-gaps.md` have the
details. Code: `ScriptStep`, `open_script` and `close_script` (`src/busk/session/timeline.py`),
`Session.script` and `_script_step` (`src/busk/session/session.py`), `Console._lines` and
`run_lines`' `each` (`src/busk/console/console.py`), the facades' `run_script`
(`src/busk/runner.py`), `pending_recovery` and `PendingRecovery`
(`src/busk/persistence/autosave.py`). Tests: `tests/test_script_undo.py` (new), the pending
recovery in `test_autosave.py` and `test_recovery.py`, `test_signatures.py`, `test_public_api.py`
and its golden, `api_consumer.py`. What differs from the steps above, or goes beyond them:

- **The step grows on top of the stack,** as an undo group's does, instead of being pushed
  when the script ends. So it is there while the script runs: `undoSteps` grows by 1 at the
  script's first change and `nextUndo` names the script, which Phase 7's bar can rely on.
- **An `undo` line in a script takes back all the script's lines before it** (vetoable): call
  18 says it "closes the step so far, as it closes an undo group", and `undo` in an open group
  takes the whole group back. The lines after it make a step of their own.
- **Undo groups and scripts:** opening and closing a script close the open group. A group
  opened inside a script counts its steps for `undo group end` and makes none of its own.
- **Beside a script** (step 18's question): only performance lines run while a script holds the
  console, and they push no step. A command that reaches the session another way meanwhile,
  `submit` from another thread or a surface's select button or `command` binding, joins the
  script's step, as it joins an open undo group.
- **The label** is `source` and the path as given, quoted when it is not one word, as
  `source` takes it. Phase 7's import passes an absolute path, so its label names it.
- **`each` is told of every line,** blank lines and comments too, their reply empty, the line
  stripped: call 20's "blank lines and comments are not shown" is the TUI's to filter. An
  exception from `each` stops the script and comes out of `run_script`.
- **`pending_recovery` reads only the show's id,** so a file with an id that fails validation is
  answered; `written` is the `session.json`'s modification time, a UTC `datetime`.
- **The TUI's wording** (no behaviour change): the TUI sends `source`, which is now one step, so
  `commands.source`'s docstring and the guide's Import script… paragraph said each line was its
  own step; they say one step now. One Ctrl+Z after an import already takes it back whole.
- **A test changed meaning:** `test_build_from_scratch.py` walked the Phase 3 build script's
  100+ undo steps; it now checks that the script is one step, and a new test walks the same
  lines typed one by one.
- **The internals doc** (`docs/dev/internals.md`, "Edits and undo") has a few lines on the step.

Checks: the whole suite (`-n 6`, 9:31) 7,279 passed, 1 skipped, 2 failed: Phase 2's
`test_waveforms.py::test_vectorised_equals_the_scalar_transcription`, and
`test_tui_e2e.py::test_f6_records_and_changes_presets_from_controls_on_the_real_engine`, a pilot
click on the wrong tile under load (it runs no script; it passes alone, three times). 27
mutations, 26 caught; the one missed showed that resetting the script's step in
`Timeline.redone` can never matter (a push clears the redo stack, so a redo follows an undo,
which resets it), and that line was removed; the tests of the timeline, the session, scripts,
recovery, the public API, the docs and the File menu then passed again. ruff, format, mypy and
`mypy --strict tests/api_consumer.py` clean.

### Phase 7: importing (no process change)

22. **Import script with the bar** (calls 20 and 21): `Bridge.run_script` and its events
    (`model.ScriptLine`, `model.ScriptDone`), the lines in the log, the bar in the hint row, and
    New, Open and Close held while a script runs. `FakeBridge` gets `run_script`.
    Verify:
    - e2e on `FakeBridge`: the bar moves and goes away; the lines and their replies reach the
      log in order; a failing line; one Ctrl+Z after it undoes the whole import;
    - a line typed during the import runs after it;
    - the perf gate while a 2,000-line script runs;
    - a pty run under `busk run`: Import script `examples/festival.busk` into a new show, timed,
      live.
23. **Import profile…** (call 22) in `FileMenu`'s `ITEMS` and `_file_chosen`.
    Verify: a pilot test from the menu to the line sent; a refusal reaches the log.
24. **Docs.** The guide's File menu (the import bar, Import profile…), CHANGELOG.

**Done** 2026-11-21, on 271e8d8. Code: `Bridge.run_script`, `_run_script`, `_Halted`,
`SCRIPT_POLL_S` (`src/busk_tui/bridge.py`); `model.ScriptLine`, `ScriptDone` and
`BridgeLike.run_script`; in `shell.py`, `Importing`, `start_import`, `_script_line`,
`_script_done`, `_log_reply` (shared with typed lines), `_show_bar`, `_held`, `import_profile`
and `LOG_S`; `HintRow.show_import`, `import_text` and `progress_text` (`widgets/prompt.py`);
`LogView.hold` and `flush`; `import_profile` in `FileMenu`'s `ITEMS`. Tests:
`tests/tui/test_tui_import.py` (new, on `FakeBridge` and on the real engine), the scripts in
`test_tui_bridge.py` (on the stub, which gains `run_script`), the held log in
`test_tui_prompt.py`, the menu in `test_tui_file_menu.py`, the gate in `test_tui_perf.py` and
`tui_perf_frontend.py` (a `script` mode); `FakeBridge.run_script` and `script_events` in
`tui_fakes.py`. What differs from the steps above, or goes beyond them:

- **The reader looks 4 times a second while a script runs** (vetoable). The perf gate found
  the import of festival.busk 2.9 times as slow through the TUI as with `run_script` alone
  (12.9 s against 4.5 s, under `busk run`): the show changes at almost every line, and each of
  the reader's 20 looks a second converted it all again (the show model, the selection's
  options, the routes and surfaces). The script holds the GIL for most of the time, so the
  TUI's work comes out of the script's. So the pages, and the live state the performance
  controls show, follow the show at 4 Hz during an import.
- **The log's pane is written 5 times a second while a script imports** (`LogView.hold`,
  vetoable): each write of `RichLog` lays the screen out again (`virtual_size` is a layout
  reactive), at every drain. The entries take each line at once. With both: 7.8 to 8.1 s in the
  gate, 7.4 to 9.7 s in a pty, against 4.5 s.
- **Another Import script… waits too**, saying so in the log, as New…, Open… and Open
  recent… do (call 21 names those and Close). `_open` checks again, for a show read or made
  while an import started.
- **Where it starts and how it ends.** The log says `importing ~/shows/festival.busk`, and the
  bar reads `starting` until the first line has run (it waits for the lines sent before it).
  `(Ctrl+Z undoes it)` is said only when busk's undo stack changed (`undoSteps` and `nextUndo`,
  before and after): a script that changes nothing, or is refused at its first line, leaves no
  step. A `quit` line ends it with `imported rig.busk: 2 of 3 lines, to its quit (…)`, and
  opens the quit dialog, as a `quit` in a `source`d script did. A file that cannot be read gets
  busk's words (`cannot read '…': No such file or directory`), or `it is not UTF-8 text`.
- **A script's line in the log** is ` ui> festival.busk:812  <line>` (the TUI ran it), then its
  reply as a typed line's: a result, or an error without busk's `error: `.
- **The bar keeps the hint row** while typing and under the mouse (F8's cells); only Ctrl+C's
  `press Ctrl+C again to quit` shows over it, until it is disarmed. The context's busy mark
  (`⧗ line 1.2s`) is left out for a script.
- **Quitting during an import:** Save and quit saves once the script has ended (the save waits
  its turn); Quit without saving stops the script after the line it runs (the bridge's `each`
  raises once the bridge stops), so `Bridge.stop` does not wait out its 5 s. In a pty, the run
  ended 0.68 s after the quit, and the lines that ran were in the autosave.
- **The gate for an import** compares the overruns with the bare run's: busk's own edits cost
  the engine 2 to 4 overruns per import with no display at all (the compiled show changes at
  each), more than 0.2 % of the import's ticks; with the TUI, 2 or 3, a smaller share. So the
  gate is that the TUI adds none (`check(…, overruns=)`), and that an import takes at most 2.5
  times as long as `run_script` (`MAX_IMPORT`), which the 2.9 above fails. Its festival.busk
  leaves out the route, the surfaces, the bindings and the feedback (no packets, no port), with
  the profiles' paths absolute: 2,129 lines.
- **`--standalone`** imports festival.busk in 23 s in a pty: the engine, its output and the
  script share one process.
- **festival.busk alone** takes 5.06 s line by line and 5.14 s with `run_script` on an
  `OfflineShow`: Phase 6's one step costs nothing.

Checks: the whole suite (`-n 6`, 10:47) 7,303 passed, 1 skipped, 2 failed: Phase 2's
`test_waveforms.py::test_vectorised_equals_the_scalar_transcription`, and
`test_tui_e2e.py::test_an_f2_drag_is_one_undo_on_the_real_engine`, a wait that timed out under
load (it runs no script; it passes alone, three times). Both are untouched here. The gate
(`-m perf`, the import alone) passes: 8.1 s against 4.4 s, 2 overruns of 802 ticks against 2
of 401. 31 mutations, all caught. ruff, format and mypy clean. Pty runs under `busk run` on a new show: Alt+F, Import
script festival.busk (the bar, the lines and their replies, the end), `gm 70%` typed during it
running after it, one Ctrl+Z (`undid: source …/festival.busk`), quit with 0; the same quitting
mid-import (0.68 s, exit 0); the import under `--standalone`, quit with 0.

### Phase 8: the recent shows (forget, the recovery mark)

25. **Forget** (call 23): `config.forget_show`, and Delete and `d` in `RecentShows`.
    Verify:
    - in `test_tui_config.py`: the merge keeps the rest of the file; a path not in the list; a
      file that cannot be written;
    - pilot tests in the launcher and in Open recent….
26. **The recovery mark** (call 24): `bridge.recovery_read`, `model.Recovery`, the rows' mark,
    the preview's line, and `--no-recover`.
    Verify:
    - pilot tests on fake reads, and `test_tui_bridge.py` on a state dir holding a crashed
      `session.json`;
    - a pty run: `kill -9` a run, start `busk-tui` with no show and see the mark, open the show,
      quit, and the mark is gone.
27. **Docs.** The guide's launcher and Open recent…, CHANGELOG.

**Done** 2026-11-21, on fefb602. Code: `config.forget_show` and `Options.recovers`
(`src/busk_tui/config.py`), `no_recover` in `BUSK_TUI_OPTIONS`; `bridge.recovery_read`,
`model.Recovery`, `controls.ReadRecovery`; in `widgets/show_dialogs.py`, `recovery_text`,
`recent_text`'s mark, `RecentList.index`, `mark` and `forget`, and in `RecentShows` the Delete
and `d` binding (`action_forget`), the reading (`_recovers`), the preview's line and
`RecentShows.Emptied`; `on_read_recovery` and `recovery` in `Launcher` and `BuskApp`;
`app.recovery`. Tests: forget and the mark in `test_tui_launcher.py` and `test_tui_open.py`,
`forget_show` and `recovers` in `test_tui_config.py`, `recovery_read` in `test_tui_bridge.py` on
a state dir a crash left (`tui_fakes.crashed`), the readers `main` and `frontend` give in
`test_tui_host.py`. What differs from the steps above, or goes beyond them:

- **No mark under `--standalone`** (vetoable): it loads the file and recovers nothing, so a mark
  would promise what does not happen, as with `--no-recover` (call 24 names only that).
  `Options.recovers` says both.
- **`--no-recover` travels in `BUSK_TUI_OPTIONS`** (`no_recover`), as `--state-dir` does: the
  TUI under `busk run` needs both for Open recent…'s marks.
- **The apps read, not the bridge.** `RecentShows` asks once (`ReadRecovery`, the rows whose
  file is there), and the launcher and `BuskApp` read the rows on one worker, in order, with the
  reader `app.py` gives them (`app.recovery`: `recovery_read` with the state dir given, or
  `None`, which reads nothing). The bridge does not know `--state-dir`, and the tests on
  `FakeBridge` read nothing unless given a reader.
- **The preview's line** comes after what busk reads in the file, after a blank line, in amber.
  A mark that comes after the preview is drawn is added to it.
- **Forgetting** writes `state.json` from `RecentShows`, which the launcher and Open recent…
  share. A file that cannot be written is ignored, as the rest of `state.json` is; the row goes
  anyway. A missing show can be forgotten too. On the last row, the cursor moves up.
- **The last row forgotten:** the launcher says "No recent shows…" and drops its note; Open
  recent… says it too, and its note becomes `Esc: close` (`RecentShows.Emptied`).
- **A test renamed:** `test_it_only_reads_the_recent_shows` is now
  `test_opening_a_recent_show_leaves_the_state_file_as_it_was`, since the launcher writes on a
  forget.
- **Seen in a pty, not changed:** after a recovery, a row's title is the recovered show's
  (`Club Edit`, the unsaved rename) while its preview reads the file's (`Club Night`): the row
  keeps the title the status bar had when the show ran (Phase 2).

Checks: the whole suite (`-n 6`, 11:49) 7,318 passed, 1 skipped, 1 failed: Phase 2's
`test_waveforms.py::test_vectorised_equals_the_scalar_transcription`, untouched here. An earlier
`tests/tui` run also failed `test_tui_e2e.py::test_an_f2_drag_is_one_undo_on_the_real_engine`
under load (it passes alone, three times; Phase 7 saw it too). 34 mutations, all caught; three
were caught only after tests were added (a `None` reading passed on, a mark for a row forgotten
meanwhile, a second forget before the list is taken away). ruff, format and mypy clean. Pty runs,
with `kill -9` of `busk run` after an unsaved rename and its autosave (exit 137): under `busk
run`, Open recent… marks the crashed Festival in amber with the preview's line; the launcher
marks both shows; Enter on Club Night recovers its rename, Quit without saving exits 0, and the
launcher no longer marks it; `--no-recover` and `--standalone` mark nothing; Delete, then `d`,
empty the list, "No recent shows" shows, `state.json` keeps `recent: []`, and both files stay.

### Phase 9: Close

28. **Close** (call 25): `FileMenu`, `shell.close_show`, the close hand-off (`parent.hand_off`,
    `read_next`), what `parent.run` returns, the loop in `app.main`, and the launcher in
    `_standalone`.
    Verify:
    - `test_tui_parent.py`: a close hand-off returns closed; a run that ends with another code
      after a close ends the parent;
    - `test_tui_host.py`: Close, the launcher, another show, quit with 0; Close, then quit the
      launcher with 0; `--values` is not applied again;
    - e2e on `FakeBridge`: each way through the confirmation; Close without busk-tui's parent;
    - pty runs under `busk run` and `--standalone`: Close, the launcher, Enter, Close, `q`, exit
      0. The kitty keyboard mode is pushed and popped evenly between the apps.
29. **Docs.** The guide's "Start" and "Opening another show", CHANGELOG.

**Done** 2026-11-21, on fd88b99. Code: `Close` and `CLOSE`, and `CLOSE` in `read_next`,
`hand_off` and what `run` returns (`src/busk_tui/parent.py`); in `app.py`, `main`'s loop and
`_launch`, the launcher in `_standalone`, and the close in `frontend`'s hand-off; in `shell.py`,
`close_show`, `_open` taking a show or `CLOSE`, `_confirm_open`'s `closing`, and `_can_open`'s
words; `OpenDialog`'s `closing` (`widgets/show_dialogs.py`); `close` in `FileMenu`'s `ITEMS`.
Tests: the close in `test_tui_parent.py`; in `test_tui_host.py`, `main`'s loop, `--standalone`'s,
the frontend's hand-off of a close, and two real runs that end in one (`tui_handoff_frontend.py`
closes the show `$BUSK_TUI_TEST_CLOSE` names); a Close section in `test_tui_open.py`; the menu's
rows in `test_tui_file_menu.py`; Close held in `test_tui_import.py`. What differs from the steps
above, or goes beyond them:

- **x is Close without saving** (vetoable): `c` is Cancel there, as in every dialog. Without
  unsaved edits it offers `[x Close]  [c Cancel]`; `o` does nothing in it.
- **The question names the show**: `Close "Club Night" (~/shows/club.show) and go back to the
  launcher?`, or "the show" while the TUI knows no title.
- **Without busk-tui's parent** each item says what it cannot do: `this TUI cannot close the
  show: busk-tui SHOW can, …`. New… now says `cannot start a new show`, where it said `cannot
  open another show`: one message for the four.
- **Held while a script imports**, as call 21 says, and again when the close comes: Save and
  close waits for the save's reply, and an import can start meanwhile (`_open` checks, as for
  Open).
- **The launcher's first choice is still the show given** (Phase 4): with no show,
  `busk-tui --values v.json` applies `--values` to the first show chosen, and not to one
  chosen after a Close.
- **A run that closes after a SIGTERM or SIGHUP** ends the parent with the run's code, as a
  run that hands a show over does: the parent starts nothing more, the launcher neither.
- **The launcher reads `recent` each time it opens**, so the show just closed is first.

Checks: the whole suite (`-n 6`, 8:14) 7,332 passed, 1 skipped, 2 failed: Phase 2's
`test_waveforms.py::test_vectorised_equals_the_scalar_transcription`, and
`test_watchdog.py::test_a_killed_engine_comes_back_with_the_same_frame_and_no_gap`, which reads
the receiver's last sACN packet before one has come (`IndexError` in `process_harness`'s
`latest`). It runs no TUI, and fails 4 times in 6 alone on fd88b99 without these changes. 21
mutations, all caught. ruff, format and mypy clean.
Pty runs at 120×32: under `busk run`, Club Night sending sACN to localhost: Alt+F (kitty) Close,
the dialog naming the route, `o` doing nothing, `x`; the launcher, Enter on Festival, an unsaved
rename, a click on the badge, Close, `c`, Close again, `s` (the file then holds the new title);
the launcher, `q`, exit 0. With `--standalone` and no show: the launcher, Festival, Close at
once (nothing unsaved, no route), `o` Club Night, Close through the route's warning, Enter on
it, Close, `q`, exit 0: seven Textual apps in one process (§8). In both raw streams each app
pushes the kitty keyboard mode (`ESC[>25u`) and pops it inside its own alternate screen, and
nothing was left running.

### Phase 10: the user's check

30. **On the rig**, with the TupperDMX simulator running:
    - import `examples/festival.busk` into a new show, watch the bar and the lines, then Ctrl+Z
      once;
    - Close, then open another show from the launcher;
    - forget a show;
    - `kill -9` a run and find the mark in the launcher.

    Findings go to §9.

## 7. Compatibility

- **`save PATH` to another file changes meaning.** The copy is a new show. A script that made a
  backup with `save backup.show` now makes a new show; the CHANGELOG says so. busk is 0.1.x.
- **`busk-tui SHOW` behaves as today,** with one more process, the parent.
- **An old `state.json`** (page and layout only) still reads.
- **`SessionStatus` is added** to the public API; nothing is removed.
- **A script is one undo step** (Phase 6). One `undo` after `source` or `--script` takes back
  the whole script, where it took back its last line. The CHANGELOG says so.
- **`run_script` gains `each`**, optional and keyword-only. `pending_recovery` and
  `PendingRecovery` are added; nothing is removed.
- **The hand-off file** may hold `{"close": true}`. Only busk-tui writes it and reads it.

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
- **The log under a script.** festival.busk sends over 4,000 lines and replies in a few
  seconds. Phase 7 measures the frame rate while it runs.
- **The launcher many times in one process.** With Close, `--standalone` starts Textual apps
  without a limit, where Phase 3 checked three. Phase 9 checked seven in a pty.

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

The items listed here on 2026-11-20 are now Phases 6–10:

- Close, back to the launcher: Phase 9 (call 25).
- Forgetting a recent show: Phase 8 (call 23).
- A "recovery pending" mark on the launcher's rows: Phase 8 (call 24, GAP-58).
- Import script as one undo step: Phase 6 (call 18, GAP-56). An undo group cannot hold it (§2),
  so the step is a new kind.
- A bar while a script imports, with its lines shown as they run: Phases 6 and 7 (calls 19–21,
  GAP-57).
- Import profile… in the File menu: Phase 7 (call 22).

Left after them:

- Stopping an import midway. busk stops a script only on the main thread's Ctrl+C
  (`Console.interrupted`), and the TUI's lines run on the bridge's thread. But an exception
  from `run_script`'s `each` stops it between two lines (GAP-57), as the bridge does when it
  stops (Phase 7, `_Halted`): a stop key would need no engine change.
