"""The built-in fixture profile and effect template libraries (spec §5.5,
§21 ``/library``).

``profiles/`` holds one :class:`~busk.model.profile.FixtureProfile` JSON
document per file. They are the hand-written profiles of Phases 0–1: the
spec's Appendix A generic spot and RGB par, and the three real fixtures
transcribed from their manuals in Phase 1 (Stairville MH-X25, Eurolite
LED ML-56 RGBW, Chauvet DJ COLORband PiX).

:class:`busk.session.library.ProfileLibrary` loads and validates them; the
operator console's ``fixture add`` embeds a library profile into the show
the first time a fixture uses it. GDTF and Open Fixture Library import
arrive in Phase 7.

``effects.json`` holds the built-in effect templates (phase-5-plan §5.12),
each with the console's defaults for its instances: Circle, Pulse, Wave,
Chase, Saw, Sweep, Flicker and Rainbow.
:class:`busk.session.library.EffectLibrary` loads and validates them; the
console's ``effect add`` embeds a template into the show the first time the
show uses it.
"""
