# SPDX-License-Identifier: GPL-3.0-or-later
"""The GPU and text calls of a POST_PIXEL draw, kept to be made again unchanged.

While a window is dragged or resized, every region of every window redraws at each step and a region whose size
stayed the same shows what it showed before (``window_motion``). A draw makes its state and drawing calls through
``call`` inside ``recording``; at such a redraw ``again`` makes the same calls in the same order (same batches,
colours, textures, text and positions) instead of working them out anew::

    if draw_replay.again(key, sig):
        return
    with draw_replay.recording(key, sig):
        ...  # draw_replay.call(batch.draw, shader), draw_replay.call(blf.draw, 0, text), ...

Calls that only return something (``blf.dimensions``) are made directly.
"""

from contextlib import contextmanager

from . import window_motion

_lists = []     # the call lists being recorded (innermost last)


def call(fn, *args):
    """``fn(*args)``, and kept in the recordings that are running."""
    fn(*args)
    for calls in _lists:
        calls.append((fn, args))


def again(key, sig):
    """True when the calls ``key``'s draw recorded for ``sig`` were made again (the draw only follows a window move or
    resize, ``window_motion.kept``). Call it at every draw of ``key``."""
    calls = window_motion.kept(key, sig)
    if calls is None:
        return False
    try:
        for fn, args in calls:
            fn(*args)
    except (ReferenceError, ValueError, TypeError, RuntimeError):
        window_motion.drop(key)
    return True


def _compact(calls):
    """``calls`` without a blend mode set that the next call sets again (nothing was drawn with it)."""
    import gpu
    blend = gpu.state.blend_set
    return [c for c, nxt in zip(calls, calls[1:] + [None]) if not (c[0] is blend and nxt is not None
                                                                  and nxt[0] is blend)]


@contextmanager
def recording(key, sig):
    """Record the ``call`` calls of the block for ``key`` / ``sig``; a block that raises keeps nothing."""
    calls = []
    _lists.append(calls)
    done = False
    try:
        yield calls
        done = True
    finally:
        for i in range(len(_lists) - 1, -1, -1):
            if _lists[i] is calls:
                del _lists[i]
                break
        if done:
            window_motion.keep(key, sig, _compact(calls))
        else:
            window_motion.drop(key)
