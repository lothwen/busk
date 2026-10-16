"""The process split (spec §16, §18; phase-7-plan decisions 1–10).

``busk run`` runs three processes:

* the **root**, the process the operator starts: the output scheduler
  (routes, discovery, ``--console`` frame lines), the watchdog, the process
  manager and the event log. It runs no show code;
* the **engine**: the engine thread, plus threads that move commands in and
  frames, snapshots and statistics out;
* the **console**: the session, the console prompt, the surfaces, feedback,
  the web remote, autosave and the status lines. It owns the terminal.

The root links them with Unix socket pairs it makes itself, so nothing
outside the process tree can connect. ``busk run --threads`` keeps the
Phase 6 layout: one process, the same components, in-process links.

``wire``          framing, messages, raw frames and the compiled-show codec
``engine_host``   the engine process: ``python -m busk.process.engine_host``
``links``         the console's side of the engine process: ``RemoteBus``
``console_host``  the console process (``python -m busk.process.console_host``),
                  and ``run_console``, which ``--threads`` runs in one process
``root``          the root: spawns and links the children, runs the output
``report``        route and statistics lines (root, or ``--threads``)
"""
