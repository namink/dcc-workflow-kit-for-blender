# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit, non-destructive import of a Maya custom shelf JSON file."""
import json
from pathlib import Path
import bpy
from bpy_extras.io_utils import ImportHelper
from .identity import user_path
from .localization import CONTEXT, tr


def import_shelves(source):
    data = json.loads(Path(source).read_text(encoding='utf-8'))
    incoming = data.get('shelves') if isinstance(data, dict) else None
    if not isinstance(incoming, list) or not all(isinstance(s, dict) and isinstance(s.get('name'), str)
                                               and isinstance(s.get('buttons'), list) for s in incoming):
        raise ValueError('Not a Maya Workflow Kit shelves.json file')
    dest = Path(user_path()) / 'maya_shelves.json'
    current = json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {'shelves': []}
    if not isinstance(current.get('shelves'), list):
        raise ValueError('The existing shelf file is invalid; no file was changed')
    added = 0
    for shelf in incoming:
        if shelf in current['shelves']:
            continue
        entry = dict(shelf)
        names = {s.get('name') for s in current['shelves']}
        n = 2
        while entry['name'] in names:
            entry['name'] = f"{shelf['name']} ({n})"
            n += 1
        current['shelves'].append(entry)
        added += 1
    # Back up existing bytes before replacing, without touching the source file.
    if dest.exists():
        backup = dest.with_suffix('.json.backup')
        n = 2
        while backup.exists():
            backup = dest.with_suffix(f'.json.backup{n}')
            n += 1
        backup.write_bytes(dest.read_bytes())
    temp = dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(dest)
    from .providers.maya.ui import shelf as shelf_ui
    shelf_ui._user.clear()
    return added


class DCC_OT_import_shelves(bpy.types.Operator, ImportHelper):
    bl_idname = 'dcc_workflow.import_maya_shelves'
    bl_label = 'Import Maya Shelves'
    bl_description = 'Copy custom shelves from the original Maya Workflow Kit; keep existing shelves and source file'
    bl_translation_context = CONTEXT
    filename_ext = '.json'
    filter_glob: bpy.props.StringProperty(default='*.json', options={'HIDDEN'})

    def execute(self, context):
        try:
            count = import_shelves(self.filepath)
        except (OSError, ValueError, TypeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, tr('Imported shelves: ') + str(count))
        return {'FINISHED'}


register, unregister = bpy.utils.register_classes_factory((DCC_OT_import_shelves,))
