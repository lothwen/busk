"""Logical → DMX conversion (spec §13).

``dmx``        the §13.1 byte split and the universe size
``curves``     dimmer curves (§13.2)
``plan``       compiled channels flattened into arrays
``converter``  the vectorised converter that runs every tick (stage 12)
"""
