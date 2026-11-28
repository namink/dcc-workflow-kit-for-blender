# SPDX-License-Identifier: GPL-3.0-or-later
"""Wrap a function of Blender's UI (a class method or a module function) and take back only the kit's own change.

``wrap(owner, name, make)`` puts ``make(previous, on)`` in place of ``owner.<name>``: ``previous`` is what was there
(Blender's function or another add-on's wrapper of it), ``on()`` is True while Maya mode is on. ``unwrap`` turns
``on()`` off and puts ``previous`` back only while the kit's function is still the one in place. When another add-on
wrapped the kit's function in the meantime, its wrapper stays: the kit's function inside it does nothing of its own
any more and only calls ``previous``. If that add-on later puts back what it found (the kit's function), it is the
same: Blender's behaviour, or the earlier add-on's. Such a retired kit function found in place when Maya mode comes
back on is skipped: the new wrapper wraps what the retired one wrapped.
"""

_MISSING = object()
_live = {}      # (id(owner), name) -> (installed object, previous, state)
_retired = []   # [(retired kit object, what it wrapped)]


def _current(owner, name):
    return vars(owner).get(name, _MISSING)


def wrap(owner, name, make):
    """Install ``make(previous, on)`` as ``owner.<name>``; returns the installed object."""
    unwrap(owner, name)
    previous = _current(owner, name)
    while True:
        older = next((p for r, p in _retired if r is previous), None)
        if older is None:
            break
        previous = older        # a retired kit function only passes through: wrap what it wrapped
        if previous is not _MISSING:
            setattr(owner, name, previous)
        else:
            delattr(owner, name)
    state = {"on": True}
    new = make(previous, lambda: state["on"])
    setattr(owner, name, new)
    _live[(id(owner), name)] = (new, previous, state)
    return new


def unwrap(owner, name):
    """Turn the kit's wrapper off; put back what it replaced when nothing has wrapped it since."""
    got = _live.pop((id(owner), name), None)
    if got is None:
        return
    new, previous, state = got
    state["on"] = False
    if _current(owner, name) is not new:
        _retired.append((new, previous))
        return                  # another add-on's wrapper is on top: leave it
    if previous is _MISSING:
        delattr(owner, name)
    else:
        setattr(owner, name, previous)


def previous(owner, name):
    """What the kit's live wrapper of ``owner.<name>`` wraps (None when it isn't wrapped)."""
    got = _live.get((id(owner), name))
    return None if got is None or got[1] is _MISSING else got[1]


def is_wrapped(owner, name):
    return (id(owner), name) in _live
