import bpy,addon_utils,sys,traceback
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
phase=0
def tick():
 global phase,d,window
 try:
  if phase==0:
   addon_utils.enable('dcc_workflow_kit',default_set=True)
   import dcc_workflow_kit as d
   assert addon_utils.check('dcc_workflow_kit')[1]
   bpy.context.preferences.view.show_splash = False
   d.preferences.get().profile='MAYA';d.core.request('MAYA')
  else:
   window=bpy.context.window_manager.windows[0]
   from dcc_workflow_kit.providers.maya.ui import four_view as fv
   print('SPACE TEST',phase,window.workspace.name,window.screen.show_fullscreen,len(fv.panes(window.screen)),flush=True)
   a=max(fv.panes(window.screen),key=lambda x:x.width*x.height)
   with bpy.context.temp_override(window=window,area=a,region=next(r for r in a.regions if r.type=='WINDOW')):
    if phase==1:
     assert bpy.ops.allset.toggle_quad_view()=={'FINISHED'}
    elif phase in (2,4,6,8):
     assert fv.is_four(window.screen),(phase,len(fv.panes(window.screen)))
     assert bpy.ops.allset.toggle_quad_view()=={'FINISHED'}
    elif phase in (3,5,7):
     assert window.screen.show_fullscreen,phase
     assert bpy.ops.allset.toggle_quad_view()=={'FINISHED'}
    else:
     assert window.screen.show_fullscreen
     (root/'result.txt').write_text('PASS Blender 4.2.9: single -> four -> single -> four, repeated 4 times')
     bpy.ops.wm.quit_blender()
     return None
  phase+=1
  return 2.5
 except Exception:
  (root/'result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender()
bpy.app.timers.register(tick,first_interval=1)

