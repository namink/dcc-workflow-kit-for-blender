# SPDX-License-Identifier: GPL-3.0-or-later
"""Register / unregister a list of sub-modules all or nothing (#198 #199).

A module whose ``register()`` raised used to leave every module before it registered (the Maya menu bar, the
Status Line, the menus) while the modules after it (the tear-off operator, the keymap ...) were missing, and the
switch back to Blender then unregistered nothing. ``register_all`` rolls back what it registered and re-raises;
``unregister_all`` takes back exactly what was recorded, carrying on past a module that raises.
"""

import traceback

PREFIX = "Maya Workflow Kit:"


def _name(mod):
    return getattr(mod, "__name__", repr(mod)).rsplit(".", 1)[-1]


def register_all(modules, done):
    """Register ``modules`` in order, appending each one to ``done`` once it registered. On an exception the failing
    module is unregistered as far as it goes, then ``done`` in reverse, and the exception is raised again."""
    for mod in modules:
        try:
            mod.register()
        except Exception as ex:
            print(PREFIX, f"registering '{_name(mod)}' failed; taking back what was registered")
            if not getattr(ex, "_allset_printed", False):    # a nested list printed it already
                traceback.print_exc()
                try:
                    ex._allset_printed = True
                except AttributeError:
                    pass
            try:
                mod.unregister()          # whatever part of it did register
            except Exception:
                pass
            unregister_all(done, quiet=True)
            raise
        done.append(mod)


def unregister_all(done, quiet=False):
    """Unregister the modules in ``done`` in reverse and empty it. A module that raises is reported (unless
    ``quiet``) and the rest still go. Returns the names of the modules that raised."""
    failed = []
    while done:
        mod = done.pop()
        try:
            mod.unregister()
        except Exception:
            failed.append(_name(mod))
            if not quiet:
                print(PREFIX, f"unregistering '{_name(mod)}' failed; the others still go")
                traceback.print_exc()
    return failed


def reregister_panel(cls, kids, poll, raw):
    """Unregister panel ``cls`` (another add-on's or Blender's) with its child panels ``kids``, give it ``poll``
    (None = no own poll) and register them again. If Blender refuses at any point the panel gets its original poll
    ``raw`` back, whatever was unregistered is registered again where Blender lets it, and False is returned: one
    foreign panel must not stop the kit."""
    try:
        for kid in reversed(kids):
            if kid.is_registered:
                _unregister_class(kid)
        if cls.is_registered:
            _unregister_class(cls)
        _set_poll(cls, poll)
        _register_class(cls)
        for kid in kids:
            _register_class(kid)
        return True
    except Exception as ex:
        print(PREFIX, f"left panel '{getattr(cls, '__name__', cls)}' as it was ({ex})")
        _set_poll(cls, raw)
        for c in (cls, *kids):
            if not c.is_registered:
                try:
                    _register_class(c)
                except Exception:
                    pass
        return False


def _subclasses(base):
    out, todo = [], list(base.__subclasses__())
    while todo:
        cls = todo.pop()
        if cls not in out:
            out.append(cls)
            todo += cls.__subclasses__()
    return out


def _depth(cls, by_id):
    depth, seen = 0, set()
    while getattr(cls, "bl_parent_id", "") and cls not in seen:
        seen.add(cls)
        cls = by_id.get(cls.bl_parent_id)
        depth += 1
        if cls is None:
            break
    return depth


def own_panels(prefixes):
    """The kit's Panel classes defined in the modules under ``prefixes``, parents before children."""
    import bpy
    found = [c for c in _subclasses(bpy.types.Panel) if c.__module__.startswith(prefixes)]
    by_id = {getattr(c, "bl_idname", c.__name__): c for c in found}
    return sorted(found, key=lambda c: _depth(c, by_id))


def release_panels(panels):
    """Unregister those of the kit's ``panels`` that are registered while the kit's modules are not: another add-on
    that had taken them out of the sidebar's Tool tab put them back on its own (#423). Children first."""
    for cls in reversed(panels):
        if cls.is_registered:
            try:
                _unregister_class(cls)
            except RuntimeError:
                pass


def restore_panels(panels):
    """Register again those of the kit's ``panels`` another add-on unregistered while the kit had them on (#423), so
    the kit's modules take them back normally. Parents first."""
    for cls in panels:
        if not cls.is_registered:
            try:
                _register_class(cls)
            except (RuntimeError, ValueError):
                pass


def blender_class(name):
    """Blender's own UI class ``name`` (``VIEW3D_PT_active_tool`` ...): the one in ``bpy.types``, else the same class
    from its ``bl_ui`` module while another add-on has unregistered it for a time (one that clears the sidebar's Tool
    tab, #423). Draw functions appended to it stay with the class and draw again once it is registered again."""
    import bpy
    cls = getattr(bpy.types, name, None)
    if cls is not None:
        return cls
    for base in (bpy.types.Panel, bpy.types.Menu, bpy.types.Header):
        for sub in _subclasses(base):
            if sub.__name__ == name and sub.__module__.startswith("bl_ui."):
                return sub
    raise AttributeError(f"no Blender UI class {name}")


def _set_poll(cls, poll):
    if poll is not None:
        cls.poll = poll
    elif "poll" in cls.__dict__:
        del cls.poll


def _register_class(cls):
    import bpy
    bpy.utils.register_class(cls)


def _unregister_class(cls):
    import bpy
    bpy.utils.unregister_class(cls)
