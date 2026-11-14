# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Workflow Kit: make Blender feel like Maya (keymap, interaction, UI, concepts).

Shipped as one Blender 4.2+ extension; Blender reads ``blender_manifest.toml``. The
legacy add-on zip gets its ``bl_info`` from ``tools/build.py`` (the extension build carries none, as the
extension guidelines recommend).

Each feature area is a sub-package with its own ``register()`` /
``unregister()``. Order matters: preferences first (others may read them),
keymap last (keymap items reference operators registered before it). ``CORE``
stays registered; ``MODE`` is Maya mode, switched on and off at run time by
``switch``.

Opt-in: Maya mode is off after install, so enabling registers only CORE. Nothing persistent:
no module writes Blender's preferences or files outside the extension's folders, and
``unregister()`` takes back everything ``register()`` added — there is nothing to restore on disable or Remove.
"""

from . import i18n, preferences, translations, settings_io, switch, welcome, operators, ui, command_line, marking, first_start, keymap


MODE = (operators, ui, command_line, marking, first_start, keymap)
