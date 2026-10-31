import ast,json,sys,bpy,addon_utils
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'));addon_utils.enable('dcc_workflow_kit',default_set=True)
from dcc_workflow_kit import core,preferences
out={'direct_calls':0,'issues':[],'panel_rows':0}
for profile in ('MAX','MAYA'):
 preferences.get().profile=profile;core._pending=None;core.set_mode(profile,layout=False)
 base=R/'src/dcc_workflow_kit/providers'/profile.lower()
 def validate(op,props,file,line):
  try:
   mod,name=op.split('.');rna=getattr(getattr(bpy.ops,mod),name).get_rna_type()
  except Exception:
   out['issues'].append({'file':str(file.relative_to(R)),'line':line,'op':op,'error':'operator not registered'});return
  for key,value in props.items():
   p=rna.properties.get(key)
   err=None
   if p is None:err='unknown property '+key
   elif p.type=='ENUM' and isinstance(value,str) and p.enum_items and value not in p.enum_items.keys():err=f'{key}={value}: invalid enum'
   if err:out['issues'].append({'file':str(file.relative_to(R)),'line':line,'op':op,'error':err})
 for f in base.rglob('*.py'):
  tree=ast.parse(f.read_bytes())
  for node in ast.walk(tree):
   if not isinstance(node,ast.Call):continue
   fn=node.func
   if isinstance(fn,ast.Attribute) and isinstance(fn.value,ast.Attribute) and isinstance(fn.value.value,ast.Attribute) and isinstance(fn.value.value.value,ast.Name) and fn.value.value.value.id=='bpy' and fn.value.value.attr=='ops':
    props={}
    for k in node.keywords:
     if k.arg:
      try:props[k.arg]=ast.literal_eval(k.value)
      except:pass
    out['direct_calls']+=1;validate(fn.value.attr+'.'+fn.attr,props,f,node.lineno)
   if isinstance(fn,ast.Attribute) and fn.attr=='operator' and node.args:
    try:op=ast.literal_eval(node.args[0])
    except:op=None
    if isinstance(op,str) and '.' in op:
     out['direct_calls']+=1;validate(op,{},f,node.lineno)
   if profile=='MAYA' and f.name=='panel_menu_data.py' and isinstance(fn,ast.Name) and fn.id=='_run' and len(node.args)>1:
    try:op=ast.literal_eval(node.args[1])
    except:continue
    props={}
    for k in node.keywords:
     try:props[k.arg]=ast.literal_eval(k.value)
     except:pass
    out['panel_rows']+=1;validate(op,props,f,node.lineno)
 core.set_mode('BLENDER',layout=False)
(R/'test-results/full-api-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
