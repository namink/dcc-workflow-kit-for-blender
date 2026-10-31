# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 168 Maya option windows of the Modify menu: Convert > Geometry to Bounding Box ❒.

Same spec as operators/option_windows.py (``F`` fields, ``Window`` = one ``allset.opt_<key>`` operator;
option_windows._extend appends ``WINDOWS``). Title, labels, button and factory values from Maya 2022's
Modify > Convert > Geometry to Bounding Box Options window.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from bpy.props import StringProperty
from .option_windows import F, Window
from .option_windows_display import FColor

class FString(F):
    """A Maya text field."""

    def __init__(self, name, label, default=''):
        super().__init__(name, label, 'string', default)

    def prop(self):
        return StringProperty(name=_zh_native(self.label.rstrip(':'), 'MWK:operators/option_windows_modify.py:24'), default=self.default, translation_context='MWK:operators/option_windows_modify.py:24')
HIERARCHY = (_dcc_source('One bounding box'), _dcc_source('One bounding box per shape'))

def _run_bbox(context, v):
    return bpy.ops.allset.geometry_to_bbox('EXEC_DEFAULT', name=v['name'], suffix=v['suffix'], per_shape=v['hierarchy'] == HIERARCHY[1], colour=tuple(v['colour']), keep_original=v['keep_original'])
WINDOWS = [Window('geom_to_bbox', _dcc_source('Convert Geometry to Bounding Box Options'), _dcc_source('Convert'), ('allset.geometry_to_bbox', {}), [FString('name', _dcc_source('Name')), FString('suffix', _dcc_source('Name suffix'), '_BBox'), F('hierarchy', _dcc_source('Represent hierarchy as:'), 'enum', HIERARCHY[0], items=HIERARCHY, translation_context='MWK:operators/option_windows_modify.py:40'), FColor('colour', _dcc_source('Color'), default=(0.5, 0.5, 0.5)), F('keep_original', '', 'bool', False, text=_zh_native('Keep original', 'MWK:operators/option_windows_modify.py:42'), translation_context='MWK:operators/option_windows_modify.py:42')], _run_bbox, paths=('Modify/Convert/Geometry to Bounding Box',), missing=(_dcc_source('Combine resulting bounding boxes (per shape)'), _dcc_source('Bake Animation: Time range, Sample by')), translation_context='MWK:operators/option_windows_modify.py:37')]
