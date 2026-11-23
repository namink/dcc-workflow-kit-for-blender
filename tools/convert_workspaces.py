"""Run in Blender 4.5 to resave Max's 5.0 templates in the older blend format."""
from pathlib import Path
import bpy

assert bpy.app.version[:2] == (4, 5)
root = Path(__file__).resolve().parents[1] / 'src/dcc_workflow_kit/providers'
for path in (root / 'max/workspace.blend', root / 'max/editor_workspace.blend', root / 'maya/app_template/Maya_Workflow_Kit/startup.blend'):
    bpy.ops.wm.open_mainfile(filepath=str(path))
    for screen in bpy.data.screens:
        flags = {}
        for index, area in enumerate(screen.areas):
            if area.type == 'PROPERTIES':
                space = area.spaces.active
                flags[str(index)] = [p.identifier for p in space.bl_rna.properties
                                     if p.identifier.startswith('show_properties_') and getattr(space, p.identifier)]
        if flags:
            screen['dcc_properties_flags'] = flags
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True)
