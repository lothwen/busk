# Phase 1.5 — sACN output: implementation plan

> Source spec: `busking-console-architecture-python.md` (§14, §16, §18). Builds on `phase-0-plan.md` and `phase-1-plan.md`; module paths refer to the layout in the README. "E1.31" means ANSI E1.31-2018, *Lightweight streaming protocol for transport of DMX512 using ACN* (free from ESTA's TSP site).

## Context

Phase 1 converts logical values into the DMX bytes that the manufacturers' charts give for three real fixtures, but the bytes only reach the console. phase-1-plan §10 recommends a short **Phase 1.5** straight after it, so those fixtures can be checked on hardware before Phase 2's MIDI demo:

- the `OutputDriver` protocol (§14.5);
- E1.31 data packets, multicast to `239.255.{hi}.{lo}` or unicast;
- per-universe sequence numbers;
- send-on-change with a keep-alive well inside the 2.5 s timeout;
- Stream_Terminated packets on shutdown;
- CID, source name and priority taken from the show.

The Phase 0 poll loop (`ConsoleOutput.run`) becomes the §14 output scheduler, and this phase settles whether console printing becomes a debug driver or stays a CLI option (phase-0-plan §8).

Phase 2's plan already contains a minimal sACN step (its decisions 13–15, §5.9–§5.10 and step 9) and says to drop that step if an earlier phase delivers output. This plan takes it over and adds what Phase 2 had deferred to Phase 6: send-on-change with keep-alive, and termination. §10 lists what that changes in the Phase 2 plan.

The engine is unchanged. It still publishes a static logical frame, converted, as an immutable `Frame` of `bytes`. Everything new runs on the output thread.

**Precondition:** Phase 1 is implemented and its tests pass (612 tests, ruff and mypy clean).

**Done when:**
- With the demo route's `iface` set to the machine's wired interface, `busk run examples/phase1-demo.json --values examples/phase1-values.json` drives the three real fixtures to their chart-derived looks, and an sACN viewer shows universe 1 carrying exactly the golden bytes (manual checklist, §8).
- An end-to-end test runs the same command over localhost unicast. It receives 4 data packets carrying the golden bytes, then 3 Stream_Terminated packets, with sequence numbers 0–6 and the show's CID, source name, priority and universe.
- The packet header matches a golden written by hand from the E1.31 tables, and the transmission rules hold as properties on a fake clock.
- Every Phase 1 acceptance test still passes.

---

## 1. Scope

| In Phase 1.5 | Deferred (to) |
|---|---|
| E1.31 data packets: full 512 slots, null START code, IPv4 multicast and unicast | IPv6 multicast (E1.31-2018) (6). Fewer than 512 slots (not planned) |
| Per-universe sequence numbers, shared by the routes that send a universe | Universe discovery every 10 s, universe synchronisation (6) |
| Send-on-change, 3 repeats, then a keep-alive every 0.9 s; at most 44 packets/s per route | Art-Net and DMX-USB routes: validated, reported as ignored (6) |
| Stream_Terminated ×3 on shutdown | Termination when a route is disabled or removed live (3, with show edits) |
| Synchronous `OutputDriver` protocol and `DriverStatus` (§14.5) | `packetsPerSec` and route status in a UI (6) |
| Output scheduler thread (the Phase 0 poll loop grown up); console printing as a `--console` sink of it | Reopening a route that failed to open (7, auto-reconnect §18). `holdLastFrameOnEngineStall: false` (7, with the watchdog) |
| One validation rule: two show universes on one sACN universe | |
| A manual hardware checklist for the three Phase 1 fixtures | |

---

## 2. Decisions and assumptions

1. **sACN only, IPv4, full universes.** Every packet carries a null START code and all 512 slots (`UNIVERSE_SIZE`), which every receiver accepts. Art-Net and DMX-USB routes stay valid show data. `busk run` lists them as ignored.
2. **One preallocated packet per route.** The header is built once, at open time (§3). A send writes only the sequence byte, the options byte and the 512 data bytes into the `bytearray`, then calls `sendto`. Nothing else is allocated per packet.
3. **Sequence numbers are per sACN universe**, as E1.31's sequence numbering requires: one counter per universe for each source (CID). Routes that send the same `universe`, such as multicast plus a unicast backup to one node, share its counter, so a receiver that hears both still sees increasing numbers.
   - Counters start at 0 and are never persisted (§17). A restart after termination, or after the 2.5 s timeout, is a new stream for receivers.
   - Two **enabled** sACN routes that send *different* show universes on the same `universe` would present two different data streams under one CID. A new validation rule makes this an error (§5.7).
4. **Transmission follows E1.31 §6.6** (rate limit and null START code transmission requirements). The output scheduler runs at `OUTPUT_HZ = 44`, the DMX512 refresh ceiling, so a route sends at most one packet per cycle. Per route:
   - when the universe **changed** since the previous cycle, send it;
   - on each of the next **3** cycles, send it again. E1.31 asks for three packets of non-changing data before suppression. Sending the change plus three repeats satisfies either reading of whether the change packet counts;
   - after that, send a **keep-alive** whenever **0.9 s** have passed since the last send. E1.31 allows 800–1000 ms. At 44 Hz the keep-alive lands every 40 cycles (0.909 s), far inside the 2.5 s data-loss timeout. A keep-alive is identical to the last packet except for its sequence number.

   This replaces Phase 2 decision 13, which sent continuously at 44 Hz.
5. **Termination.** `close()` sends **3** packets with the Stream_Terminated option bit (`0x40`). They carry the last data (receivers ignore it) and consecutive sequence numbers. After that the route never sends again. A route that never sent a packet sends no termination. Termination needs an orderly shutdown (Ctrl+C or `--duration`). After a crash or `kill -9`, receivers fall back to the 2.5 s timeout, which is how E1.31 is meant to fail.
6. **`OutputDriver` is synchronous**, as in Phase 2 decision 14, and drivers run on the output thread. It keeps §14.5's shape with two deviations:
   - `send(data: bytes, changed: bool, now: float)` takes `bytes`, because that is what `Frame` carries;
   - `DriverStatus` has `ok`, `detail`, `packets` and `errors`. `packetsPerSec` needs a time window and arrives with the UI (Phase 6).
7. **Interfaces and sockets.**
   - **Multicast** to `239.255.{u >> 8}.{u & 0xFF}`, port 5568. The interface comes from `destination.iface`:
     - a **name** sets `IP_MULTICAST_IF` with a Linux `struct ip_mreqn` built from `socket.if_nametoindex(iface)`;
     - an **IPv4 address** sets it with that `in_addr`. Use this form on other platforms.
   - The multicast TTL stays at the OS default of 1, because lighting networks are one subnet. `IP_MULTICAST_LOOP` stays on, so a viewer on the same machine sees the traffic.
   - **Unicast** to `host:5568`. The host is resolved once at open (`getaddrinfo`, `AF_INET`), never in the send path.
   - The port is read from the module constant `SACN_PORT` at open time, so tests can point a route at an ephemeral localhost port.
   - Sockets are non-blocking. A full send buffer counts as an error and never stalls the output thread.
8. **Failures are per route (§18).**
   - If a route can't open (unknown interface, unresolvable host), the route is reported and left out for the rest of the run, and the others carry on. The message lists the available interfaces (`socket.if_nameindex()`). Reconnecting is Phase 7.
   - An `OSError` while sending is counted. It sets `ok = False` with the error as `detail` and never raises. The next due send retries. A failed send still counts as sent for the keep-alive timer, so a dead link is retried about once a second, not 44 times a second. The first successful send sets `ok` again.
   - The scheduler also wraps each driver call in `try/except Exception`. A driver bug is counted as a fault on its route and the other routes and the console keep running.
9. **The console printer is a debug sink, `busk run --console`**, serviced by the output scheduler on the same thread. This is Phase 2 decision 15, and it settles phase-0-plan §8: the console is not a route protocol. The Phase 0/1 line format is unchanged. Without `--console`, `busk run` prints no frame lines.
10. **Shutdown order:** stop the engine, join it, then stop the output thread. The output thread makes one last pass, so the final frame is sent and printed, and then closes every driver (termination). Two `threading.Event`s replace the shared one.
11. **Hold last frame.** If the engine stalls, `latest` stops changing and the routes send keep-alives of the last frame, which holds the look (`holdLastFrameOnEngineStall: true`, the default). `false` needs a definition of "stalled" and of what to send instead, so it waits for the Phase 7 watchdog (§9).
12. **No new dependencies.** `socket`, `struct` and `uuid` are enough.
13. **The tests never touch a real network by default.** CLI tests run on copies of the shows whose routes are disabled, or pointed at a localhost receiver. A real multicast test runs only when `BUSK_TEST_IFACE` names an interface.

---

## 3. E1.31 data packet

The packet is always 638 bytes. All multi-byte fields are big-endian.

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 2 | Preamble size | `0x0010` |
| 2 | 2 | Post-amble size | `0x0000` |
| 4 | 12 | ACN packet identifier | `ASC-E1.17\0\0\0` |
| 16 | 2 | Root flags & length | `0x7000 \| 622` = `0x726E` |
| 18 | 4 | Root vector | `0x00000004` (VECTOR_ROOT_E131_DATA) |
| 22 | 16 | CID | `uuid.UUID(output.sacnCid).bytes` |
| 38 | 2 | Framing flags & length | `0x7000 \| 600` = `0x7258` |
| 40 | 4 | Framing vector | `0x00000002` (VECTOR_E131_DATA_PACKET) |
| 44 | 64 | Source name | `output.sacnSourceName`, UTF-8, NUL-padded (validation keeps it ≤ 63 bytes, so it is always NUL-terminated) |
| 108 | 1 | Priority | `route.priority` |
| 109 | 2 | Synchronization address | `0` (no sync) |
| 111 | 1 | Sequence number | per sACN universe, mod 256 |
| 112 | 1 | Options | `0`; `0x40` Stream_Terminated (`0x80` Preview_Data and `0x20` Force_Synchronization are never set) |
| 113 | 2 | Universe | `route.universe` |
| 115 | 2 | DMP flags & length | `0x7000 \| 523` = `0x720B` |
| 117 | 1 | DMP vector | `0x02` (VECTOR_DMP_SET_PROPERTY) |
| 118 | 1 | Address & data type | `0xA1` |
| 119 | 2 | First property address | `0x0000` |
| 121 | 2 | Address increment | `0x0001` |
| 123 | 2 | Property value count | `513` = `0x0201` |
| 125 | 1 | START code | `0x00` |
| 126 | 512 | DMX data | the universe row |

Multicast groups: universe 1 → `239.255.0.1`, 256 → `239.255.1.0`, 63999 → `239.255.249.255`.

---

## 4. Project layout (additions to Phase 1)

```
src/busk/
  output/
    driver.py           # OutputDriver protocol, DriverStatus
    sacn.py             # packet layout, data_packet(), multicast_group(), Sequences, SendPolicy, SacnSender
    scheduler.py        # OUTPUT_HZ, ScheduledRoute, build_routes(), OutputScheduler (the §14 output thread)
    console.py          # ConsoleOutput: print-on-change, now a sink of the scheduler (run() and clock removed)
  model/validate.py     # + sACN universe conflict rule
  cli.py                # run: routes, --console, status changes, per-route summary, ordered shutdown
tests/
  sacn_receiver.py      # independent E1.31 parser + localhost receiver (shared by the tests below)
  test_sacn.py          # packet golden and fields, groups, sequences, SacnSender over localhost
  test_sacn_policy.py   # send-on-change / repeat / keep-alive rules, table-driven and hypothesis
  test_output_scheduler.py
  test_console_output.py test_cli.py test_validate.py test_perf.py   # updated / extended
  builders.py           # + offline(show), localhost_route(show, port)
```

---

## 5. Component design

### 5.1 Packet (`output/sacn.py`)

```python
SACN_PORT: Final = 5568
PACKET_SIZE: Final = 638
SEQUENCE: Final = 111   # offsets written per send
OPTIONS: Final = 112
DATA: Final = 126
STREAM_TERMINATED: Final = 0x40

def data_packet(*, cid: bytes, sourceName: str, priority: int, universe: int) -> bytearray: ...
def multicast_group(universe: int) -> str: ...
```
`data_packet` returns the §3 layout with sequence 0, options 0 and zeroed data. It is built with `struct.pack_into` from named offsets, one per row of the table.

### 5.2 Sequences and the send policy (`output/sacn.py`)

```python
class Sequences:
    """E1.31 sequence numbers: one counter per sACN universe, shared by its routes."""
    def next(self, universe: int) -> int: ...     # 0, 1, …, 255, 0, …

class SendPolicy:
    """When a route transmits (decision 4). Pure: no sockets, time is passed in."""
    def due(self, changed: bool, now: float) -> bool: ...
```
- `due` returns `True` on a change (and arms 3 repeats), on each armed repeat, and when `now − lastSent ≥ KEEPALIVE_S` (0.9). Whenever it returns `True` it records `now` as `lastSent`. Before the first send `lastSent` is `−inf`.
- Keeping the policy free of sockets lets `test_sacn_policy.py` check it exhaustively on a fake clock. Art-Net's once-a-second keep-alive (Phase 6) can reuse it with other constants.

### 5.3 `SacnSender` (`output/sacn.py`)

```python
class SacnSender:                       # implements OutputDriver
    def __init__(self, route: SacnRoute, *, cid: bytes, sourceName: str, sequences: Sequences): ...
    protocol: Literal["sacn"]
    def open(self) -> None: ...         # socket, interface, address; failures go to status()
    def send(self, data: bytes, changed: bool, now: float) -> None: ...
    def close(self) -> None: ...        # 3 × Stream_Terminated, then close the socket; idempotent
    def status(self) -> DriverStatus: ...
```
- `send` returns at once if the route isn't open or was closed. Otherwise it asks `SendPolicy.due`. If due, it writes `sequences.next(universe)`, the options byte and `data` into the packet and calls `sendto`.
- **Status is read by the main thread** while the output thread sends. The sender replaces an immutable `(ok, detail)` pair only on transitions and increments plain `int` counters, so a read never sees half an update. `status()` builds the `DriverStatus` on the caller's thread.
- `description` (for the CLI): `U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100`, or `… unicast 10.0.0.20 …`.

### 5.4 Driver protocol (`output/driver.py`)

```python
@dataclass(frozen=True, kw_only=True)
class DriverStatus:
    ok: bool
    detail: str          # "" when ok; the last error otherwise
    packets: int         # sent successfully
    errors: int          # failed sends

class OutputDriver(Protocol):
    @property
    def protocol(self) -> Literal["dmxUsb", "artnet", "sacn"]: ...
    def open(self) -> None: ...
    def send(self, data: bytes, changed: bool, now: float) -> None: ...   # never blocks, never raises OSError
    def close(self) -> None: ...                                          # sends termination if applicable
    def status(self) -> DriverStatus: ...
```

### 5.5 Output scheduler (`output/scheduler.py`)

```python
OUTPUT_HZ: Final = 44.0

@dataclass(kw_only=True)
class ScheduledRoute:
    id: str
    row: int                 # universe row in Frame.universes / CompiledShow.universes
    driver: OutputDriver
    description: str
    faults: int = 0          # exceptions raised by the driver (decision 8)

def build_routes(settings: OutputSettings, universes: Sequence[CompiledUniverse]
                 ) -> tuple[list[ScheduledRoute], list[str]]: ...

class OutputScheduler:
    def __init__(self, engine: FrameSource, routes: Sequence[ScheduledRoute], clock: Clock,
                 console: ConsoleOutput | None = None): ...
    def service(self, now: float) -> None: ...
    def run(self, stop: threading.Event) -> None: ...
```
- `build_routes` creates one `SacnSender` per **enabled** sACN route, with one shared `Sequences`, and opens it. It returns the routes that opened, plus one notice line for each route that is disabled, ignored (`artnet r2: ignored (Art-Net output arrives in Phase 6)`) or failed to open (`sACN r1: cannot open: no network interface 'eth0' (available: lo, enp5s0)`).
- `service(now)`:
  1. Read `engine.latest` once. Before the first frame, do nothing.
  2. Mark universe *u* as changed when its bytes differ from the previous cycle's frame (everything is changed on the first frame). If it is the same `Frame` object, nothing changed.
  3. Call `send(frame.universes[row], changed[row], now)` on every route, each inside its own `try/except Exception` (decision 8).
  4. Service the console sink, if any.
- `run(stop)` loops `service` on a `FixedRateSchedule(clock, OUTPUT_HZ)` until `stop` is set. It then calls `service` once more (decision 10) and, in a `finally`, `close()`s every driver, each guarded like `send`.

### 5.6 Console (`output/console.py`)

The print-on-change logic and the line format are unchanged. The scheduler now calls `ConsoleOutput.service(now)`. `ConsoleOutput.run`, its `clock` parameter and `POLL_HZ` are removed, since the scheduler and `OUTPUT_HZ` replace them. The module docstring changes from "stand-in for network output" to "debug sink".

### 5.7 Validation (`model/validate.py`)

One new row in the semantic pass:

| Area | Rule |
|---|---|
| Output | Two **enabled** sACN routes with the same `universe` must have the same `universeId`. The error is on the later route's `output.routes[i].universe`: *sACN universe 1 is already sent by route 'r1' from universe 'u1'* |

Disabled routes are skipped, because they send nothing. Phase 3 revalidates `output` whenever an edit enables one.

### 5.8 CLI (`busk run SHOW [--values FILE] [--duration S] [--console]`)

1. Load, compile and compile the values, as in Phase 1.
2. `build_routes`. Print a line for each open route on stdout (`sACN r1: U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100`). Print the notices too: disabled and ignored routes on stdout, open failures on stderr. If no route is open and `--console` is off, print `no output: no sACN route is open (add --console to print frames)` on stderr. The run still continues.
3. Start the engine and the output scheduler threads. They use separate stop events.
4. The main thread wakes every 0.25 s, which it already does to keep Ctrl+C responsive. Each time, it prints any route whose `(ok, detail)` changed, on stderr: `sACN r1: send failed: [Errno 101] Network is unreachable`, then `sACN r1: sending again`.
5. On Ctrl+C or `--duration`, shut down in decision 10's order.
6. Print the Phase 1 engine statistics line, then one line per route on stdout: `sACN r1: 7 packets, 0 errors`, followed by `, N faults` when there were any.

The old notice `console output only — N output route(s) in the show are ignored` is removed.

---

## 6. Implementation steps

Each step follows TDD: write the listed tests first, then make them pass.

0. **Preconditions.** Phase 1 is green (pytest, ruff, mypy).
1. **Read the standard, then spike.**
   - Read E1.31's data packet, source processing (rate limit, null START code transmission), Stream_Terminated, sequence numbering and data-loss sections. Confirm the constants in decisions 4–5 and the §3 table. Write down any difference here before coding. In particular, confirm the termination packet count (3) and the keep-alive window (800–1000 ms).
   - Spike in the scratchpad: send one packet out of a named interface with `ip_mreqn`. Receive it on the same host with a socket that joins `239.255.0.1` on that interface (loopback is on). Check it in Wireshark (`udp.port == 5568`; the E1.31 dissector decodes every field).

     *Fallback:* if `ip_mreqn` is refused, use the interface's IPv4 address and record that in decision 7.

   → *verify:* the packet arrives and Wireshark shows no malformed fields.
2. **Packet.** → *verify:* `test_sacn.py`:
   - the first 126 bytes for a fixed CID, name, priority and universe equal a **golden written by hand**, field by field, as commented `bytes` literals taken from the §3 table. They are never produced by running the code;
   - `tests/sacn_receiver.py` parses every field at its own offsets with `struct`. It checks a 63-byte UTF-8 name with multi-byte characters (NUL-padded, last byte NUL), priorities 0 and 200, and universes 1 and 63999;
   - the multicast groups of universes 1, 256 and 63999.
3. **Sequences and send policy.** → *verify:*
   - `test_sacn.py`: each universe counts 0…255 then wraps to 0. Two universes are independent. Two routes on one universe interleave consecutive numbers.
   - `test_sacn_policy.py`, table-driven on a 44 Hz fake clock with one change and then 10 s of static data:
     - sends at cycles 0, 1, 2 and 3, then every 40 cycles (0.909 s);
     - a change during suppression sends at once and re-arms the 3 repeats.
   - Hypothesis properties, over random change patterns and cycle gaps of 1/44 s ± jitter with occasional overrun gaps of up to 0.2 s:
     - every change is sent in its own cycle;
     - the 3 cycles after a change send;
     - while suppressed, consecutive sends are ≥ 0.9 s apart;
     - no gap without a send exceeds 0.9 s plus the largest cycle gap, which keeps every gap inside 0.8–1.0 s when cycles are regular;
     - there is at most one send per cycle.
4. **`SacnSender`.** All socket tests use localhost unicast on an ephemeral port. → *verify:* `test_sacn.py`:
   - open + send delivers one packet with the route's fields and data, sequence 0, options 0;
   - `close()` sends exactly 3 packets with options `0x40`, the last data and consecutive sequence numbers, then nothing more. A second `close()` and any later `send()` do nothing. Closing a route that never sent sends nothing;
   - `iface` `"lo"` and `"127.0.0.1"` both open. `"no-such-if0"` gives `ok = False` with a detail that lists the available interfaces. An unresolvable host fails to open;
   - a send to `255.255.255.255` without `SO_BROADCAST` fails with `PermissionError`. The failure is counted, `ok` becomes `False` with the error as detail, and nothing is raised. With a stub socket, the next successful send restores `ok`;
   - **opt-in:** when `BUSK_TEST_IFACE` is set, a multicast packet sent on that interface is received by a socket that joined the group there. The test is skipped otherwise.
5. **Validation rule** (§5.7). → *verify:* `test_validate.py` gets new cases with the exact `(severity, path)`:
   - a conflict on the same `universe` is an error;
   - the same `universe` and the same `universeId` (multicast plus unicast) is clean;
   - a disabled conflicting route is clean.

   Appendix A and the demo still give 0 errors and 0 warnings.
6. **Driver protocol, scheduler, console sink.** → *verify:* `test_output_scheduler.py`, with fake drivers that record their calls, a `FakeClock`, and `service(now)` called directly:
   - nothing is sent before the first frame;
   - the first frame flags every universe as changed;
   - the same `Frame` object or equal bytes flag nothing;
   - a new frame flags exactly the universes that changed;
   - each route gets its own universe's row;
   - a driver that raises gets `faults` counted, and the other routes and the console still run;
   - `run` services at `OUTPUT_HZ` (the moved Phase 0 test), makes a final pass after `stop`, and closes every driver exactly once, even if one `close()` raises;
   - a stalled engine (`latest` frozen) keeps the routes being called with `changed=False`, so they send keep-alives of the last frame.

   `test_console_output.py` keeps its line-format and print-on-change cases unchanged, apart from the constructor.
7. **CLI.** Add `offline(show)` and `localhost_route(show, port)` to `builders.py`. → *verify:* `test_cli.py`:
   - The Phase 1 `run` tests run on `offline` copies with `--console`, and their golden lines are unchanged. Without `--console`, no frame lines are printed.
   - **End to end** (the done criterion): a `localhost_route` copy of the demo, run with `SACN_PORT` monkeypatched to a receiver's port and `--values … --duration 0.3`, delivers exactly 7 packets:
     - 4 data packets whose data equals the bytes of `DEMO_LINE`;
     - then 3 Stream_Terminated packets;
     - sequence numbers 0–6;
     - the show's CID, source name, priority and universe in every packet.

     The run prints the route line and `sACN r1: 7 packets, 0 errors`, and exits 0. (A 0.3 s run ends before the first keep-alive is due, so the count is exact.)
   - A route with `iface: "no-such-if0"` prints the open failure on stderr, and the run still exits 0. An Art-Net route is reported as ignored, and a disabled route as disabled.
   - Two runs with the same values produce identical data packets.
8. **Benchmark** (`test_perf.py`, `-m perf`). 64 unicast routes to one bound localhost socket, every universe changed on every cycle. → *verify:* the median `service` time is < 5 ms (a cycle lasts 22.7 ms), with p99 reported. If it is over budget, profile it before changing anything.
9. **Documentation.**
   - README: the status, usage with `--console` and the route lines, how to pick the interface (`ip -br link`), the test table, the layout, an "Output" paragraph under *How it works*, decisions beyond the plan, and *Next* → Phase 2.
   - The CLI and `output/__init__.py` docstrings.
   - The `pyproject.toml` description.
10. **Full verification pass** (§8), including the hardware checklist.

---

## 7. Acceptance tests (summary)

| Test file | Proves |
|---|---|
| `test_sacn.py` | E1.31 layout against a hand-written golden; field parsing; multicast groups; per-universe sequences; open, send, termination and error handling over real sockets |
| `test_sacn_policy.py` | Send on change, 3 repeats, keep-alive inside 0.8–1.0 s, ≤ 1 packet per cycle (table-driven and hypothesis) |
| `test_output_scheduler.py` | Change detection per universe, route isolation, final pass and close on stop, hold last frame, 44 Hz |
| `test_console_output.py` (updated) | The Phase 0 line format and print-on-change, now as a sink |
| `test_validate.py` (extended) | The sACN universe conflict rule |
| `test_cli.py` (updated) | **The done criterion:** `run` over localhost delivers the golden bytes, then termination; `--console`; route lines and failures |
| `test_perf.py` (`-m perf`) | One output cycle for 64 universes takes < 5 ms |

---

## 8. Verification

```bash
uv run pytest                                          # all green; no packets leave the machine
uv run pytest -m perf -s                               # output cycle < 5 ms; conversion still < 1 ms
uv run ruff check . && uv run ruff format --check . && uv run mypy
BUSK_TEST_IFACE=enp5s0 uv run pytest tests/test_sacn.py -k multicast   # your wired interface
uv run busk validate examples/phase1-demo.json         # → 0 errors, 0 warnings
uv run busk run examples/phase1-demo.json --values examples/phase1-values.json --console
    # → route line, the golden frame line once; Ctrl+C → stats, "sACN r1: N packets, 0 errors"
```

**Hardware checklist.** Set up the following:
- Run a wired Ethernet link from the machine to an sACN → DMX node, or to a fixture with native sACN, listening on universe 1.
- In a copy of the demo show, set the route's `iface` to that interface. To use unicast instead, set the destination to the node's IP address.
- Patch the DMX chain as in the demo:
  - MH-X25 #1 at 1 (12ch);
  - MH-X25 #2 at 13 (12ch);
  - ML-56 at 25 (4ch);
  - COLORband PiX at 29 (36ch).

  With other fixtures, substitute them as phase-1-plan §3 describes.
- Optionally, run sACNView or QLC+ on a second machine or the same one, and Wireshark with `udp.port == 5568`.

1. `busk run <copy> --values examples/phase1-values.json --console` prints the route line and the golden frame line, and no errors.
2. The viewer shows universe 1 from source "Busk Console" with the show's CID and priority 100. Its values equal the golden line.
3. Wireshark shows 4 packets in about 70 ms, then one keep-alive about every 0.91 s. The keep-alives are identical apart from the sequence number, and the sequence numbers are consecutive.
4. **MH-X25 #1:** full, red, gobo 3, at pan 90° / tilt −45° from centre. Check the direction and roughly the angle.
5. **MH-X25 #2:** pan mirrored (`invertPan`), strobing at about 5 Hz. Measure the rate with a slow-motion video: the strobe range is an estimate (README transcription notes).
6. **ML-56:** orange (red full, green half) at 80 %, white emitter off.
7. **COLORband PiX:** the 12 cells alternate red and blue at full.
8. Ctrl+C: the viewer shows the source as terminated immediately, and the node applies its data-loss behaviour at once rather than after 2.5 s.
9. For contrast, run again and `kill -9` the process: the node holds the look for about 2.5 s, then applies its data-loss behaviour.
10. Unplug the cable for a few seconds, then plug it back in. The look is back within a second of reconnecting (the next keep-alive). Whether stderr reports send failures meanwhile depends on how the OS handles the link loss.
11. Record any difference from the chart-derived expectations:
    - a transcription error → fix the profile, its golden and its `notes`, citing the chart;
    - a measured estimate (strobe Hz, gobo rotation) → update the profile and the README transcription notes.

The frame is static in Phase 1.5, so on the wire you see only the start-up burst and then keep-alives. Send-on-change under changing data is covered by the tests and first runs live in Phase 2.

---

## 9. Spec gaps found while planning

**Resolved by this plan** (the spec should adopt or amend these):
- §14.1's "send on change, otherwise resend periodically" omits E1.31's rules: three packets before suppression, and a keep-alive every 800–1000 ms (decision 4).
- §14.4's "per-universe sequence numbers" doesn't say how routes sharing an sACN universe interact. They share the counter, and two show universes on one sACN universe are an error (decision 3, §5.7).
- §14.5's `OutputDriver` is `async` and takes an `NDArray`. It is now synchronous and takes `bytes`, and `DriverStatus` carries counters instead of `packetsPerSec` (decision 6).
- The console printer is a `--console` sink, not a route protocol (decision 9, closing phase-0-plan §8).
- The roadmap puts sACN termination in Phase 6. It moves here, because hardware checks need receivers to release promptly.

**Still open:**
- **`holdLastFrameOnEngineStall: false`** is undefined. After how long without a new frame does the engine count as stalled, and what is sent then: the base image, zeros, or a termination? Decide with the Phase 7 watchdog.
- **`MulticastDestination.iface`** is a name, which is platform-specific (`ip_mreqn` is Linux). An IPv4 address works everywhere. The schema could say which forms it accepts, and whether an empty string means "the OS default route".
- **No TTL or slot-count fields.** Phase 1.5 uses TTL 1 and always sends 512 slots. Routed lighting networks or slow DMX refresh (§14.2's "fewer slots") would need fields.
- **Receivers that misbehave under suppression.** Some older nodes may expect a continuous stream. If one is found during the checklist, record the model. The fix belongs in the receiver, but a per-route "no suppression" option could be added if it matters in practice.

---

## 10. Effect on the Phase 2 plan and later phases

- **Phase 2:**
  - Step 9 (sACN + output scheduler) is dropped, as its step 0 anticipates.
  - Decision 13 is superseded: send-on-change, keep-alive and termination are already in place.
  - Decisions 14 and 15 and §5.9–§5.10 are implemented as written, apart from the deviations in decisions 4–6 here.
  - The spike in step 1(b) has been done (step 1 here).
  - Its CLI (§5.12) keeps the route lines and `--console` from this phase. It adds its own status line and `commands N, command errors M` to the summary.
  - With the resolver changing the frame, the wire carries change bursts while faders move and keep-alives when idle, with no further output work.
- **Phase 3:** route reconciliation on show edits compares routes by id. It `close()`s removed or disabled routes, which sends their termination, and builds new ones with `build_routes`.
- **Phase 6:** only universe discovery (every 10 s, universe 64214), universe synchronisation, Art-Net and DMX USB remain. `SendPolicy` can serve Art-Net's keep-alive.
- **Phase 7:** auto-reconnect for routes that failed to open or were lost, `holdLastFrameOnEngineStall: false`, and the process split, which keeps output running if the UI dies.
