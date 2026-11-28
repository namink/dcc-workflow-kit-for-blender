# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw one Maya menu item: ``draw_item`` / ``draw_spec`` (operator, tool, 3D View run, Blender menu, check or
radio property, or greyed with its notice), ``_draw_boxed`` (an item with an option box), and kit subclasses of
Blender menus that hide their keymap shortcut (``register_proxies``). Operators: ``menu_item_ops``.
"""

import json

import bpy

from . import draw_safe, menu_map, notices
from .menu_item_ops import (ALLSET_OT_menu_item, ALLSET_OT_menu_run, ALLSET_OT_menu_set_value, ALLSET_OT_menu_tool,
                            ALLSET_OT_menu_unavailable, op_polls, prop_owner)
from .menu_option_box import ALLSET_MT_option_box


# --- items ---------------------------------------------------------------------

def draw_item(layout, path, label, icon_value=0, translate=True):
    """Draw one Maya menu item: its Blender action, or greyed out. An item with a "not in Blender" notice and an
    operator substitute runs through ``allset.menu_item``, whose tooltip carries the notice. So does a
    mapped item Blender's poll would grey out (component commands in object mode): Maya keeps its menu items
    enabled and runs or warns (``menu_map.OBJECT_MODE``). ``icon_value``: the item's kit icon
    (``menu_icons``), 0 = none. ``translate=False``: ``label`` is already in the interface language."""
    s = menu_map.spec(path)
    # Blender draws, right-aligned, a shortcut it finds in the keymaps for the very operator + properties of an
    # item (Increment and Save "Ctrl Alt S", Exit "Ctrl Q"): operator items go through ``allset.menu_item``, which
    # no key runs, so only the Maya hotkey drawn into the label shows.
    if s is not None and s[0] == "op" and path in menu_map.GREY_ON_POLL and not op_polls(s[1]):
        draw_spec(layout, label, s, path, icon_value=icon_value, translate=translate)  # Maya greys it here
        return
    if s is not None and (s[0] == "op" or s[0] in ("v3d", "tool") and (
            notices.notice(path) or not runs_directly(path, s) or _has_saved_options(path))):
        op = draw_safe.op(layout, ALLSET_OT_menu_item.bl_idname, text=label, icon_value=icon_value,
                          translate=translate)
        op.item, op.clicked = path, True
        return
    draw_spec(layout, label, s, path, icon_value=icon_value, translate=translate)


def _has_saved_options(path):
    from ..operators import option_windows
    w = option_windows.find_path(path)
    return w is not None and w.click_saved and option_windows.saved(w.key) is not None


def runs_directly(path, s):
    """False if the item must go through ``allset.menu_item`` to stay enabled the Maya way."""
    if path in menu_map.OBJECT_MODE and bpy.context.mode == 'OBJECT':
        return False
    if path in menu_map.EDIT_MODE and bpy.context.mode == 'EDIT_MESH':
        return False
    return s[0] != "op" or op_polls(s[1])


def draw_spec(layout, label, s, path, icon='NONE', icon_value=0, translate=True):
    """Draw a normalised action (``menu_map.normalize``); None = greyed out with
    ``path`` (the Maya menu path) in the tooltip. ``icon_value`` (a kit icon) wins over ``icon``.
    ``translate=False``: ``label`` is already in the interface language (Blender doesn't look it up again)."""
    iv = {"icon_value": icon_value} if icon_value else {"icon": icon}
    if not translate:
        iv["translate"] = False
    if s is None:
        draw_safe.op(layout, ALLSET_OT_menu_unavailable.bl_idname, text=label, **iv).item = path
        return
    kind, target, props = s
    if kind == "prop":
        draw_prop(layout, label, target, props, path, translate=translate)
    elif kind == "menu":
        layout.menu(proxy_menu(target), text=label, **iv)
    elif kind == "pie":
        draw_safe.op(layout, "wm.call_menu_pie", text=label + " ▸", **iv).name = target
    elif kind == "tool":
        op = draw_safe.op(layout, ALLSET_OT_menu_tool.bl_idname, text=label, **iv)
        op.tool = target
        op.edit = props["edit"]
        op.item = path              # Ctrl+Shift+click: to the shelf
    elif kind == "v3d":
        op = draw_safe.op(layout, ALLSET_OT_menu_run.bl_idname, text=label, **iv)
        op.op = target
        op.props = json.dumps(props)
        op.item = path
    else:
        if target == "wm.url_open" and "url" in props:     # the running Blender's manual / API pages
            from .. import compat
            props = dict(props, url=compat.docs_url(props["url"]))
        op = draw_safe.op(layout, target, text=label, **iv)
        for key, value in props.items():
            setattr(op, key, value)


def draw_prop(layout, label, target, props, path="", translate=True):
    """A Maya check item = Blender's check box; a radio choice = ``prop_enum`` for enums, else a radio-marked
    button that sets the value (``allset.menu_set_value``). Greyed with the notice when the property isn't
    there in this context (e.g. a Graph Editor setting drawn from another editor)."""
    owner, attr = prop_owner(bpy.context, target)
    tr = {} if translate else {"translate": False}
    if owner is None:
        draw_safe.op(layout, ALLSET_OT_menu_unavailable.bl_idname, text=label, **tr).item = path
        return
    if props.get("off_while"):
        # Maya greys this check item while another check is on (Enable IK Handle Snap under IK/FK control)
        o2, a2 = prop_owner(bpy.context, props["off_while"])
        if o2 is not None and getattr(o2, a2, False):
            layout = layout.row()
            layout.enabled = False
    if "value" not in props:
        from . import maya_dock
        current = getattr(owner, attr)
        if maya_dock.drawing_torn() and isinstance(current, bool):
            # a torn-off menu is a panel with menu emboss, where Blender drops a check box (Blender 5.2):
            # the check mark is drawn as the item's icon
            layout.prop(owner, attr, text=label, **tr, icon='CHECKBOX_HLT' if current else 'CHECKBOX_DEHLT')
            return
        layout.prop(owner, attr, text=label, **tr)
        return
    value = props["value"]
    rna = owner.bl_rna.properties.get(attr)
    if rna is not None and rna.type == 'ENUM':
        layout.prop_enum(owner, attr, value, text=label, **tr)
        return
    current = getattr(owner, attr)
    on = abs(current - value) < 1e-6 if isinstance(value, float) else current == value
    op = draw_safe.op(layout, ALLSET_OT_menu_set_value.bl_idname, text=label, **tr,
                      icon='RADIOBUT_ON' if on else 'RADIOBUT_OFF')
    op.target, op.value = target, repr(value)


def _draw_boxed(layout, path, text, icon_value=0):
    """An item with a Maya option box; ``text`` already ends with the box mark (``item_texts``) and is in the
    interface language."""
    s = menu_map.spec(path)
    if s is None or s[0] in ("menu", "pie"):
        draw_spec(layout, text, s, path, icon_value=icon_value, translate=False)
        return
    op = draw_safe.op_hold(layout, ALLSET_OT_menu_item.bl_idname, text=text, icon_value=icon_value, translate=False,
                           menu=ALLSET_MT_option_box.bl_idname)
    op.item, op.clicked = path, True


# Blender menus a Maya item opens (Recent Files = TOPBAR_MT_file_open_recent) are drawn through a kit subclass:
# for the original Blender prints the keymap shortcut of ``wm.call_menu`` ("Shift Ctrl O").
_proxies = {}          # Blender menu idname -> kit subclass idname
_PROXY_CLASSES = []


def proxy_menu(target):
    return _proxies.get(target, target)


def _menu_targets():
    out = set()
    for path in menu_map.MAP:
        s = menu_map.spec(path)
        if s is not None and s[0] == "menu" and not s[1].startswith("ALLSET_"):
            out.add(s[1])
    return sorted(out)


def register_proxies():
    for target in _menu_targets():
        base = getattr(bpy.types, target, None)
        if not (isinstance(base, type) and issubclass(base, bpy.types.Menu) and "draw" in base.__dict__):
            continue
        idname = "ALLSET_MT_proxy_" + target
        cls = type(idname, (base,), {"bl_idname": idname, "__doc__": base.__doc__ or base.bl_label})
        try:
            bpy.utils.register_class(cls)
        except (RuntimeError, ValueError):
            continue
        _proxies[target] = idname
        _PROXY_CLASSES.append(cls)


def unregister_proxies():
    for cls in reversed(_PROXY_CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    _PROXY_CLASSES.clear()
    _proxies.clear()
