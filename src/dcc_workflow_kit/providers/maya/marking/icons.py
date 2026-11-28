# SPDX-License-Identifier: GPL-3.0-or-later
"""Pictures of the marking menu items (#525): the kit's drawing of each item's command (``icon_data``) at the size
the menus draw them (16 px x UI scale), as GPU textures for ``draw.py``.

Drawing a picture takes a few milliseconds, so the pixels of every marking item picture are made ahead from a timer
(``BUDGET`` seconds per tick, after Maya mode turns on, and again when a menu is drawn at a new UI scale): an open
menu then only uploads them. A picture not made yet is drawn on the spot.
"""

import time

from . import icon_data

_pixels = {}        # (picture, n) -> (n, n, 4) float32, top row first
_todo = []
_size = [0]         # the size the timer makes
BUDGET = 0.02


def size():
    """Pixel size of an item picture: 16 px x UI scale."""
    import bpy
    return int(round(16 * (bpy.context.preferences.system.ui_scale or 1.0)))


def picture(pic, n):
    """(n, n, 4) RGBA (top row first) of an ``icon_data`` picture."""
    if pic[0] == "uvtk":
        from ..ui import uv_toolkit_icons
        return uv_toolkit_icons.picture(pic[1], n)
    if pic[0] == "mark":
        from ..ui import marking_drawings
        return marking_drawings.draw(pic[1], n)
    from ..ui import menu_icons
    return menu_icons.picture(pic, n)


def pixels(pic, n):
    key = (pic, n)
    px = _pixels.get(key)
    if px is None:
        import numpy as np
        px = _pixels[key] = np.asarray(picture(pic, n), dtype=np.float32)
    return px


def texture(pic, n, greyed=False):
    """GPU texture of ``pic`` at ``n`` px (greyed for a disabled item); needs a GPU context (a draw handler)."""
    from ..ui import shelf_icons
    return shelf_icons.texture_of(("marking",) + tuple(pic), lambda s: pixels(pic, s), greyed=greyed, size=n)


def _tick():
    try:
        n = size()
        if _size[0] != n:
            _size[0] = n
            for key in [k for k in _pixels if k[1] != n]:
                del _pixels[key]
            _todo[:] = sorted(set(icon_data.ICONS.values()), key=repr)
        t0 = time.perf_counter()
        while _todo and time.perf_counter() - t0 < BUDGET:
            pixels(_todo.pop(), n)
        return 0.05 if _todo else None
    except Exception:       # a timer that raises is dropped: pictures are then drawn when a menu first shows them
        _todo.clear()
        return None


def warm(n):
    """Make the pictures of size ``n`` ahead when they aren't (a menu drawn after a UI scale change)."""
    if _size[0] != n:
        _schedule(0.0)


def _schedule(first):
    import bpy
    if not bpy.app.background and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=first, persistent=True)


def register():
    _schedule(0.5)


def unregister():
    import bpy
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _todo.clear()
    _pixels.clear()
    _size[0] = 0
