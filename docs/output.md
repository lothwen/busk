# Output: sACN, Art-Net and DMX-USB

A show sends its universes through **routes**, one per universe and protocol: sACN (ANSI
E1.31), Art-Net, or a USB DMX interface. Add them at the [console](console.md):

```
busk> route add 1 sacn 1                              # universe 1 → sACN universe 1, multicast
busk> route add 1 sacn 1 unicast 10.0.0.20            # … to one node
busk> route add 2 artnet 0.0.1                        # universe 2 → Art-Net Port-Address 0.0.1, broadcast
busk> route add 2 artnet 0.0.1 unicast 10.0.0.20      # … to one node (or: broadcast IF)
busk> route add 3 dmxusb enttecPro /dev/ttyUSB0 hz 40 # universe 3 → an Enttec DMX USB Pro
```

The output runs at 44 Hz, the DMX512 refresh ceiling, and sends a universe when its bytes
change, plus a keep-alive about once a second.

- [Choosing the network interface](#choosing-the-network-interface)
- [sACN](#sacn)
- [Art-Net](#art-net)
- [DMX-USB](#dmx-usb)
- [Route messages](#route-messages)
- [Reconnects](#reconnects)

## Choosing the network interface

An sACN multicast route sends out of the interface named by its `destination.iface`, and an
Art-Net broadcast route broadcasts on its interface's broadcast address. `route add` uses
the interface given to `busk run --iface` (default `eth0`). List your interfaces with
`ip -br link` (Linux) and use the wired one that reaches your nodes. In the show file:

```json
{ "id": "r1", "universeId": "u1", "enabled": true, "protocol": "sacn", "universe": 1,
  "priority": 100, "destination": { "kind": "multicast", "iface": "enp5s0" } }
```

`iface` may be an interface **name** (Linux only) or the interface's **IPv4 address** (any
platform). For unicast to one node, use `{ "kind": "unicast", "host": "10.0.0.20" }`; the
host is resolved once, when the run starts.

## sACN

- A change is sent at once and repeated on the next 3 output cycles; after that a
  keep-alive goes out about every 0.91 s, inside E1.31's 800–1000 ms and far inside
  receivers' 2.5 s timeout. A static look costs about one packet per second per universe.
- The multicast TTL is 1 (one subnet) and loopback stays on, so an sACN viewer on the same
  machine (sACNView, QLC+, OLA) sees the traffic.
- Every 10 s busk announces the universes it sends on E1.31's discovery universe (64214),
  out of the interfaces its multicast routes use.
- Two enabled routes on the same sACN universe must send the same show universe.
- The sender's CID is stored in the show: `busk new` copies the installation's, created once
  in the state directory.
- When the run stops, or the output is turned off (`output off`), each sACN route sends
  Stream_Terminated, so receivers release the universe at once.

To check what is on the wire, Wireshark with `udp.port == 5568` dissects E1.31 once
*Preferences → Protocols → ACN → Streaming DMX* is enabled.

## Art-Net

An Art-Net route names a Port-Address as `net.sub.universe` (`0.0.1`). It broadcasts on its
interface's broadcast address (`{ "kind": "broadcast", "iface": "eth0" }`) or sends to one
node (`unicast 10.0.0.20`). Packets go out on change and as a keep-alive once a second.

Every 2.5 s busk polls the network (ArtPoll). A node on the interface's network that
answers with an output on the route's Port-Address then gets that universe unicast instead
of the broadcast; a node silent for 10 s is forgotten (broadcast again). busk answers polls
too, as a controller named after the show's sACN source name. For this it listens on UDP
6454, but only while a broadcast route is open. A show whose Art-Net routes are all
unicast sends from another port and leaves 6454 free, so a receiver on the same machine (a
visualiser, say) can listen there, whichever program starts first; such a show answers no
polls. If another Art-Net program holds the port when a broadcast route needs it, busk
sends from another one, without discovery, and says so.

Art-Net nodes keep their last frame when busk stops or turns the output off.

## DMX-USB

A DMX-USB route names a serial device: `route add 3 dmxusb enttecPro /dev/ttyUSB0 [hz 40]`
for an **Enttec DMX USB Pro**, `dmxking` for a **DMXking ultraDMX**. The widget makes the
DMX signal itself, at the route's `refreshHz` (1–40); busk sends it a frame when the
universe changes and once a second otherwise.

- On Linux, opening `/dev/ttyUSB*` needs the `uucp` group (Arch) or `dialout` (Debian,
  Ubuntu).
- Pulled out, the route reports the error and tries to reopen the device once a second,
  so output resumes when it is plugged back in.
- An **Open DMX USB** (FTDI without a processor) needs breaks timed by the host and is not
  supported (`enttecOpen` routes are reported and ignored).
- Widgets keep their last frame when busk stops or turns the output off.

## Route messages

Route lines go to stdout, one per open route, saying where it sends:

```
sACN r1: U1 Stage → universe 1, multicast 239.255.0.1 via eth0, priority 100
Art-Net r2: U2 Bar → port address 0.0.1, broadcast 10.255.255.255 via eth0
DMX-USB r3: U3 Floor → Enttec DMX USB Pro on /dev/ttyUSB0 at 40 Hz
Art-Net: node 10.0.0.20 'Node 1' outputs 0.0.1
Art-Net: node 10.0.0.20 'Node 1' forgotten (no reply for 10 s)
```

plus `disabled` and `ignored (…)` notices (an `enttecOpen` interface, an unknown driver).
Routes that cannot open, send failures and recoveries go to stderr:

```
sACN r1: cannot open: no network interface 'eth0' (available: lo, enp6s0, wlp0s20f3)
sACN r1: send failed: [Errno 101] Network is unreachable
sACN r1: sending again
```

## Reconnects

Every route reconnects by itself. One that cannot open is tried again every 2 s, whatever
the reason, and prints its line again, ending in `(sending)`, once it opens. One whose
sends have failed for 1 s is closed and reopened on the same schedule, its interface,
address and broadcast address looked up again. So an interface that comes up late, a USB
network adapter plugged back in or a DMX-USB widget plugged in after the start are found
by themselves, and an outage prints once, not on every retry. Sequence numbers carry on
across reopens.

While the engine is stalled or restarting, the output holds the last frame (see
[the watchdog](running.md#processes-and-the-watchdog)). `output off` at the console stops
all DMX output until `output on` (see [Safety](safety.md#panic)).
