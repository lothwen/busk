"""The web remote: a phone drives the show over Wi-Fi (spec §5.12, phase-6-plan §5.12).

``busk.web.websocket``
    The server side of RFC 6455 that the remote needs: the handshake,
    frames and :class:`~busk.web.websocket.WebSocket` connections with a
    writer thread each.
``busk.web.server``
    :class:`~busk.web.server.WebServer`: HTTP and WebSocket on one port, the
    access key and the origin check.
``busk.web.api``
    :class:`~busk.web.api.WebApi`: the JSON protocol (hello, show, state,
    commands, the stage) and the broadcaster;
    :class:`~busk.web.api.WebSurface`: one ``web`` surface in ``busk run``.
``busk.web.stage``
    :class:`~busk.web.stage.StageFeed`: the stage view's rig, from the show,
    and each fixture's look, from the engine's frames.
``static/index.html``
    The phone page: one file, vanilla JS and CSS, no external resources.
    ``static/commands.json`` lists the command types it sends.
``static/stage.html``
    The stage view: the rig in 3D, with three.js from jsDelivr (the one
    external resource, loaded only when the view is opened).

Standard library only (decision 19). The engine never imports this package:
the web surface reads published snapshots and submits commands, as the
console and the bindings do.
"""
