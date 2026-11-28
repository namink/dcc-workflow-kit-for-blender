# SPDX-License-Identifier: GPL-3.0-or-later
"""Other add-ons' entries in Blender's top bar, shown after the Maya menus: ``addon_menu_funcs`` (their draw
functions; the kit's own are skipped by module), ``addon_menus_width`` (their width, from a stand-in layout) and
``ALLSET_MT_addon_menus`` that draws them (``draw_addon_menus``). Used by ``menu_sets`` and ``status_line``.
"""

import bpy


class ALLSET_MT_addon_menus(bpy.types.Menu):
    """Menus other add-ons put in Blender's top bar"""
    bl_idname = "ALLSET_MT_addon_menus"
    bl_label = "Add-on Menus"

    def draw(self, context):
        for func in addon_menu_funcs(context):
            try:     # one broken add-on must not stop the rest, as in Blender's own menus
                func(self, context)
            except Exception:
                import traceback
                traceback.print_exc()


# Other add-ons append their own menus to Blender's top bar menu (TOPBAR_MT_editor_menus), where they follow Help.
# The Maya menu bar replaces that menu, so those entries follow the Maya menus instead (or sit at the end of the
# overflow menu when the bar is full). When the bar is fitted each add-on draw function is run on a measuring layout
# (``addon_menus_width``); a function whose drawing can't be sized keeps this much room.
ADDON_MENU_UNITS = 5.0
_KIT = __package__.rpartition(".")[0]


def addon_menu_funcs(context=None):
    """Draw functions other add-ons added to ``TOPBAR_MT_editor_menus`` (not Blender's own, not the kit's), with
    the workspace's add-on filter applied like Blender does."""
    draw = getattr(bpy.types, "TOPBAR_MT_editor_menus", None)
    funcs = getattr(getattr(draw, "draw", None), "_draw_funcs", None) or ()
    workspace = getattr(context, "workspace", None) if context is not None else None
    owners = None
    if workspace is not None and getattr(workspace, "use_filter_by_owner", False):
        owners = {o.name for o in workspace.owner_ids}
    out = []
    for func in funcs:
        if getattr(func, "__qualname__", "") == "TOPBAR_MT_editor_menus.draw":
            continue
        module = getattr(func, "__module__", "") or ""
        if module == _KIT or module.startswith(_KIT + "."):
            continue
        owner = getattr(func, "_owner", None)
        if owners is not None and owner is not None and owner not in owners:
            continue
        out.append(func)
    return out


class _Sink:
    """Operator properties of a sized button: whatever is set on them is dropped."""

    def __setattr__(self, name, value):
        pass


class _MeasureLayout:
    """Stands in for a header layout: adds up the width (in UI units, plus ``px``) of what a draw function puts
    in it, like a Blender header row does (a button = its text + 1.25 units, an icon one more unit, an icon-only
    button one unit). Anything it doesn't know raises, and the caller falls back to ``ADDON_MENU_UNITS``."""

    def __init__(self, text_px):
        self.units, self.items, self._text_px = 0.0, 0, text_px

    def _button(self, text, icon):
        has_icon = bool(icon) and icon != 'NONE'
        self.items += 1
        if not text:
            self.units += 1.0
            return
        self.units += self._text_px(text) + 1.25 + (1.0 if has_icon else 0.0)

    def menu(self, menu, text="", icon='NONE', icon_value=0, **_kw):
        if not text:
            cls = getattr(bpy.types, menu, None)
            text = getattr(cls, "bl_label", menu) if cls is not None else menu
        self._button(bpy.app.translations.pgettext_iface(text), icon if not icon_value else 'ICON')

    def operator(self, operator, text="", icon='NONE', icon_value=0, **_kw):
        if not text:
            mod, _, name = operator.partition(".")
            cls = getattr(getattr(bpy.ops, mod, None), name, None)
            rna = cls.get_rna_type() if cls is not None else None
            text = rna.name if rna is not None else operator
        self._button(bpy.app.translations.pgettext_iface(text), icon if not icon_value else 'ICON')
        return _Sink()

    def label(self, text="", icon='NONE', icon_value=0, **_kw):
        self._button(bpy.app.translations.pgettext_iface(text), icon if not icon_value else 'ICON')

    def popover(self, panel, text="", icon='NONE', icon_value=0, **_kw):
        self._button(bpy.app.translations.pgettext_iface(text), icon if not icon_value else 'ICON')

    def separator(self, factor=1.0, **_kw):
        self.units += 0.5 * factor

    def separator_spacer(self):
        pass

    def row(self, *_a, **_kw):
        return self

    column = row

    def __setattr__(self, name, value):
        if name in ("units", "items", "_text_px"):
            object.__setattr__(self, name, value)        # layout flags (enabled, alignment, scale ...) are ignored


def addon_menus_width(context, funcs=None):
    """Header width in px the other add-ons' top-bar entries take (``funcs`` default ``addon_menu_funcs``)."""
    import blf
    from types import SimpleNamespace
    from .toolbar_fit import spacing, unit
    prefs = context.preferences
    scale = prefs.system.ui_scale or 1.0
    u = unit(scale, prefs.system.pixel_size)
    blf.size(0, prefs.ui_styles[0].widget.points * scale)

    def text_units(text):
        return blf.dimensions(0, text)[0] / u
    total = 0
    for func in addon_menu_funcs(context) if funcs is None else funcs:
        probe = _MeasureLayout(text_units)
        try:
            func(SimpleNamespace(layout=probe, bl_idname="TOPBAR_MT_editor_menus"), context)
            total += int(probe.units * u) + probe.items * spacing(scale)
        except Exception:
            total += int(ADDON_MENU_UNITS * u)
    return total


def draw_addon_menus(layout, context):
    """Other add-ons' top-bar menus, in line (a header row or a menu)."""
    if addon_menu_funcs(context):
        layout.menu_contents(ALLSET_MT_addon_menus.bl_idname)
