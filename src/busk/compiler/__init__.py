"""Compilation: from show data to flat engine structures (spec §6).

Show data is optimised for editing and references; the engine needs flat
arrays. The compiler runs whenever show data changes and never inside the
real-time tick:

``compile``      the entry point, :func:`~busk.compiler.compile.compile_show`
``rig``          fixtures resolved against their profiles; element analysis
``slots``        the slot table, lanes and the default logical frame (§6.1–§6.2)
``lanes``        encoding attribute values into lanes
``channels``     one pre-resolved record per slot-driven DMX channel (§13)
``cues``         cue entries expanded into lane arrays (§6.3)
``playbacks``    playbacks, the pages and masters as the engine runs them
``limitations``  the show features this build ignores, for ``busk run``
``values``       base logical frames from a values file
"""
