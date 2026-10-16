"""Show files, autosave and crash recovery (spec §17, §18).

``show_file``    ``.show`` ZIP and ``.json`` show files: loading, atomic saves,
                 rolling backups, the ``busk new`` template
``autosave``     the autosave worker (show and ``session.json``) and the
                 crash-recovery decision
``paths``        the state directory and the installation's sACN CID
``eventlog``     the event log (§15.5): records, causes, the rotating
                 writer and the reader that ``busk replay`` uses
``values_file``  static values files (``busk run --values``)
"""
