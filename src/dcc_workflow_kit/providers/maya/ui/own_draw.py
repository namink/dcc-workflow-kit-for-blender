# SPDX-License-Identifier: GPL-3.0-or-later
"""Swap only a Blender UI class's *own* draw function.

Blender keeps a header / panel / menu's draw functions in a list once anything is appended or prepended to it
(``bpy_types._GenericUI._dyn_ui_initialize``, the mechanism ``append`` / ``prepend`` use). Where the kit has to draw
*instead of* Blender's content in its own areas (Maya strip, Maya Outliner header, status bar, ...), it replaces only
Blender's own entry in that list, never the class's ``draw`` attribute: other add-ons' appended / prepended UI keeps
drawing, and ``restore`` puts Blender's function back at the same place even if others extended the class after us.
The kit function falls back to Blender's own draw (``original``) outside the kit's areas.

When another add-on has already put its own function in the place of Blender's draw, the kit leaves that function
alone: its function is added at the end of the list and draws only in the kit's areas (``original`` draws nothing),
and ``restore`` takes it out again, so the list is back as it was.

Kit draw functions are marked with ``@kit_draw(class name)``: one that another add-on keeps in its list after Maya
mode is off (it took the kit's function for Blender's) draws Blender's own content instead of the kit's.
"""

import functools

import bpy

_saved = {}   # (class name, kit function) -> what the kit function stands in for
_own = {}     # class name -> Blender's own draw, once found


def _nothing(self, context):
    return None


def _funcs(cls_name):
    return getattr(bpy.types, cls_name)._dyn_ui_initialize()


def _is_own(cls, f):
    """Blender's own draw: a function named ``draw`` defined in the module of the class (or of a class it inherits
    from). A wrapper an add-on puts in its place may copy the name, but its globals are the add-on's module."""
    g = getattr(f, "__globals__", None)
    if getattr(f, "__name__", "") != "draw" or g is None:
        return False
    return g.get("__name__") in {c.__module__ for c in cls.__mro__}


def kit_draw(cls_name):
    """Decorator for a kit function swapped in with ``swap``: while it is not swapped in (Maya mode off) it draws
    what ``original`` gives, never the kit's content (whose operators and properties are gone then)."""
    def deco(fn):
        @functools.wraps(fn)
        def draw(self, context):
            if (cls_name, draw) not in _saved:
                return original(cls_name, draw)(self, context)
            return fn(self, context)
        return draw
    return deco


def own_index(cls_name, funcs=None):
    """Index of Blender's own draw among the class's draw functions (something may have been prepended), or None
    when another add-on's function has taken its place."""
    cls = getattr(bpy.types, cls_name)
    for i, f in enumerate(_funcs(cls_name) if funcs is None else funcs):
        if _is_own(cls, f):
            return i
    return None


def swap(cls_name, fn):
    """Put ``fn`` where ``cls_name``'s own draw is; returns what ``fn`` draws outside the kit's areas (Blender's own
    draw, or nothing when another add-on's function has Blender's place)."""
    key = (cls_name, fn)
    funcs = _funcs(cls_name)
    if key in _saved and fn in funcs:
        return _saved[key]
    i = own_index(cls_name, funcs)
    if i is None:
        _saved[key] = _nothing
        funcs.append(fn)
    else:
        _saved[key] = _own[cls_name] = funcs[i]
        funcs[i] = fn
    return _saved[key]


def original(cls_name, fn):
    """What ``fn`` draws outside the kit's areas. After ``restore`` (a kit function another add-on kept in its own
    list) that is Blender's own draw."""
    got = _saved.get((cls_name, fn))
    if got is not None:
        return got
    return _own.get(cls_name, _nothing)


def restore(cls_name, fn):
    """Blender's own draw back in place of ``fn`` (wherever ``fn`` is now), or ``fn`` taken out when it was only
    added."""
    own = _saved.pop((cls_name, fn), None)
    if own is None:
        return
    funcs = _funcs(cls_name)
    if fn not in funcs:
        return
    if own is _nothing:
        funcs.remove(fn)
    else:
        funcs[funcs.index(fn)] = own
