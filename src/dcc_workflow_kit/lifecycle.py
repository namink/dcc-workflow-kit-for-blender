# SPDX-License-Identifier: GPL-3.0-or-later
"""Reversible registration transactions shared by both providers."""
_active = {}


def activate(owner, steps):
    if owner in _active:
        return
    done = _active[owner] = []
    try:
        for on, off in steps:
            # Record before calling so partially registered modules are cleaned up too.
            done.append(off)
            on()
    except Exception:
        try:
            deactivate(owner)
        except Exception as cleanup_error:
            print('DCC Workflow Kit registration cleanup:', cleanup_error)
        raise


def deactivate(owner):
    errors = []
    for off in reversed(_active.pop(owner, [])):
        try:
            off()
        except Exception as error:
            errors.append(f'{off.__module__}.{off.__name__}: {error}')
    if errors:
        raise RuntimeError('\n'.join(errors))


def owners():
    return tuple(_active)
