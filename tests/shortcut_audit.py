import bpy,sys,addon_utils,json,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
addon_utils.enable('dcc_workflow_kit',default_set=True)
from dcc_workflow_kit import core,preferences
report={}
for profile in ('MAX','MAYA'):
 preferences.get().profile=profile;core._pending=None;core.set_mode(profile,layout=False)
 rows=[];fail=[]
 kc=bpy.context.window_manager.keyconfigs.addon
 for km in kc.keymaps:
  for k in km.keymap_items:
   if not k.active or not k.idname:continue
   try:
    mod,name=k.idname.split('.');rna=getattr(getattr(bpy.ops,mod),name).get_rna_type()
    props={p.identifier:getattr(k.properties,p.identifier) for p in k.properties.bl_rna.properties if p.identifier!='rna_type' and k.properties.is_property_set(p.identifier)}
    for key,val in props.items():
     prop=rna.properties.get(key)
     assert prop is not None, 'missing property '+key
     if prop.type=='ENUM' and prop.enum_items and isinstance(val,str):
      assert val in prop.enum_items.keys(), f'{key}={val} not in {list(prop.enum_items.keys())}'
    rows.append({'map':km.name,'key':k.type,'ctrl':k.ctrl,'alt':k.alt,'shift':k.shift,'op':k.idname,'props':props})
   except Exception as e:fail.append({'map':km.name,'key':k.type,'op':k.idname,'error':str(e)})
 report[profile]={'checked':len(rows),'failures':fail,'bindings':rows}
 core.set_mode('BLENDER',layout=False)
out=ROOT/'test-results/shortcut-audit-4.5.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
for p,v in report.items():print(p,'CHECKED',v['checked'],'FAIL',len(v['failures']),json.dumps(v['failures'],ensure_ascii=False))
