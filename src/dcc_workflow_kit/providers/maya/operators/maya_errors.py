# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya's ``// Error:`` messages for commands run on a selection they don't take (step 258, #152).

Maya prints these as Errors in the Command Line / Help Line (Maya 2026,
with the step-258 additions there). A kit operator reports one with ``op.report({'ERROR'}, text)``;
code that runs a Blender operator for a Maya menu item raises ``MayaError`` before it, which the menu item turns into
the same Error report (``report_nested``) instead of Blender's Python error.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
WRONG_SELECTION = _dcc_source("Current selection doesn't match required selection type.")
NO_LIVE_SURFACE = _dcc_source('A live surface is required for conform.')
NO_CONFORM_SELECTION = _dcc_source('No components or objects selected for conform.')
MUST_SELECT_JOINT = _dcc_source('You must select at least one joint.')
SELECT_TO_BIND = _dcc_source('Select objects to bind.')
BINDABLE_IN_SELECTION = _dcc_source('Bindable objects must be part of the selection.')
NO_TARGETS = _dcc_source('Target list was empty or contained no valid targets.')
MOVE_IK_TO_FK = 'Must select an ik handle, joint or object that connected to IK/FK.'
REMESH_NOTHING = _dcc_source('This command requires at least 1 argument(s) to be specified or selected;  found 0.')
REDUCE_NOTHING = _dcc_source('Reduce requires that at least 1 object or group of faces be selected.')
NO_SHAPE = _dcc_source('No shape was selected.')

class MayaError(RuntimeError):
    """A Maya Error for the user (no traceback): ``str()`` is Blender's text for an operator's ERROR report."""

    def __init__(self, text):
        super().__init__(f'Error: {text}')
        self.text = text

def report_nested(op, ex):
    """Report a RuntimeError of a nested call on ``op``: an Error (an operator's ERROR report, a ``MayaError``) stays
    an Error with its text, anything else becomes a Warning with its last line (as before step 258)."""
    text = str(ex).strip()
    if text.startswith(_dcc_source('Error: ')) and _dcc_source('Traceback') not in text:
        op.report({'ERROR'}, _zh(text[len('Error: '):].strip(), 'MWK:operators/maya_errors.py:40'))
        return
    op.report({'WARNING'}, _zh(text.splitlines()[-1] if text else type(ex).__name__, 'MWK:operators/maya_errors.py:42'))
_NOTHING = {'REMESH': REMESH_NOTHING, 'DECIMATE': REDUCE_NOTHING}

def check_modifier(context, kind):
    """Raise ``MayaError`` (or a RuntimeError with a kit warning) when the Maya command behind ``object.modifier_add``
    of ``kind`` refuses this selection; return None when the modifier can be added."""
    ob = context.active_object
    nothing = context.mode == 'OBJECT' and (not context.selected_objects)
    if kind == 'SHRINKWRAP':
        if getattr(context.scene, 'allset_live', None) is None:
            raise MayaError(NO_LIVE_SURFACE)
        if nothing or ob is None:
            raise MayaError(NO_CONFORM_SELECTION)
        if ob.type != 'MESH':
            raise RuntimeError(_dcc_source('Conform: select a mesh to conform onto the live surface.'))
        return
    if kind in _NOTHING:
        if nothing or ob is None:
            raise MayaError(_NOTHING[kind])
        if ob.type != 'MESH':
            raise MayaError(WRONG_SELECTION)
        return

def wrong_type_warning(kind):
    """Kit warning for the other Maya commands the kit runs as a modifier (Triangulate, Smooth, Soft Body ...) when
    Blender has no such modifier for the active object type: no Maya text is known for those."""
    label = {'TRIANGULATE': _dcc_source('Triangulate'), 'SUBSURF': _dcc_source('Smooth'), 'DATA_TRANSFER': _dcc_source('Transfer Attributes'), 'OCEAN': _dcc_source('Ocean'), 'SOFT_BODY': _dcc_source('Soft Body')}.get(kind, str(kind).title())
    return f'{label}: select a mesh first.'
