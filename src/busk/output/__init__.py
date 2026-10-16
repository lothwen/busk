"""Output: getting engine frames out of the process (spec §14).

Output runs on its own thread, never on the engine thread, and only reads
the immutable frames the engine publishes:

``busk.output.scheduler``
    The output thread. At 44 Hz it offers each route the latest frame's
    universe, flagged when its bytes changed, then services the console
    sink. ``build_routes`` turns the show's routes into open drivers.
``busk.output.driver``
    The ``OutputDriver`` protocol (§14.5) and ``DriverStatus``.
``busk.output.sacn``
    sACN / E1.31 (§14.4): data packets, per-universe sequence numbers,
    send-on-change with keep-alive, Stream_Terminated on close.
``busk.output.artnet``
    Art-Net 4 (§14.3): ArtDmx packets, per-Port-Address sequence numbers,
    send-on-change with a one-second keep-alive, one shared socket.
``busk.output.dmxusb``
    DMX-USB (§14.2): the Enttec DMX USB Pro protocol over a serial device,
    for Enttec Pro and DMXking widgets; reopened after an unplug.
``busk.output.netif``
    Interface addresses and broadcast addresses (Linux ``ioctl``s), host
    and interface lookups shared by the network protocols.
``busk.output.console``
    The ``--console`` debug sink: prints universes when they change.
"""
