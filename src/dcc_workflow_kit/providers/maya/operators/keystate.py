# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Ask the OS whether a key is physically held.

Fallback for hold modals whose RELEASE event was eaten by another modal
(e.g. the transform modal while dragging). docs/steps/step_3.md 「계획」 1.

Windows only: a read-only ``user32.GetAsyncKeyState`` query through ctypes (no hook,
no other OS call). Elsewhere, or if the call fails, ``is_down`` returns None
("unknown"); every caller acts only on an explicit False, so the hold then ends on
Blender's RELEASE event alone (docs/distribution/listing.md, step 115).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
import sys
_VK = {chr(c): c for c in range(ord('A'), ord('Z') + 1)}
_VK.update({'INSERT': 45, 'DEL': 46, 'HOME': 36, 'END': 35, 'PAGE_UP': 33, 'PAGE_DOWN': 34, 'LEFT_ARROW': 37, 'UP_ARROW': 38, 'RIGHT_ARROW': 39, 'DOWN_ARROW': 40, 'SPACE': 32, 'TAB': 9, 'ACCENT_GRAVE': 192, 'BACK_SLASH': 220, 'LEFTMOUSE': 1, 'RIGHTMOUSE': 2, 'MIDDLEMOUSE': 4, 'LEFT_SHIFT': 160, 'RIGHT_SHIFT': 161, 'LEFT_CTRL': 162, 'RIGHT_CTRL': 163})
_user32 = None
if sys.platform == 'win32':
    try:
        import ctypes
        _user32 = ctypes.windll.user32
    except (ImportError, AttributeError, OSError):
        _user32 = None

def vk_code(event_type):
    return _VK.get(event_type)

def is_down(event_type):
    """True/False if the OS can tell, None if unknown (other OS or key)."""
    vk = _VK.get(event_type)
    if _user32 is None or vk is None:
        return None
    try:
        return bool(_user32.GetAsyncKeyState(vk) & 32768)
    except (OSError, AttributeError, ValueError):
        return None
