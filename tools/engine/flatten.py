import json,sys,math,os
R='/opt/cura/squashfs-root/share/cura/resources'
def load(path):
    d=json.load(open(path))
    if 'inherits' in d:
        base=d['inherits']
        for p in (f'{R}/definitions/{base}.def.json',f'{R}/extruders/{base}.def.json'):
            if os.path.exists(p): parent=load(p); break
    else: parent={}
    s=dict(parent)
    def walk(t):
        for k,v in t.items():
            s.setdefault(k,{}); s[k]=dict(s[k]); s[k].update({kk:vv for kk,vv in v.items() if kk!='children'})
            if 'children' in v: walk(v['children'])
    walk(d.get('settings',{}))
    for k,v in d.get('overrides',{}).items():
        s.setdefault(k,{}); s[k]=dict(s[k]); s[k].update(v)
    return s
s=load(sys.argv[1])
extra=json.loads(sys.argv[2]) if len(sys.argv)>2 else {}
vals={k:v.get('default_value') for k,v in s.items() if v.get('type')!='category'}
vals.update(extra)
class V(dict):
    def __missing__(self,k): raise KeyError(k)
env={'math':math,'min':min,'max':max,'round':round,'int':int,'float':float,'str':str,'len':len,'sum':sum,'any':any,'all':all,'abs':abs,'map':map,'list':list,'bool':bool,'sorted':sorted,'set':set,'tuple':tuple}
def fn(name): return lambda *a,**k: vals.get(a[-1] if isinstance(a[-1],str) else a[0]) if name!='extruderValues' else [vals.get(a[0])]
for f in ('extruderValue','resolveOrValue','defaultExtruderPosition','valueFromContainer','extruderValues','anyExtruderWithMaterial','anyExtruderNrWithOrDefault'):
    env[f]=fn(f)
env['defaultExtruderPosition']=lambda *a:'0'
env['anyExtruderWithMaterial']=lambda *a:'0'
env['anyExtruderNrWithOrDefault']=lambda *a:'0'
for it in range(8):
    for k,v in s.items():
        if 'value' in v and k not in extra and v.get('type')!='category':
            expr=v['value']
            if not isinstance(expr,str): vals[k]=expr; continue
            try: vals[k]=eval(expr,env,dict(vals))
            except Exception: pass
def fmt(v):
    if isinstance(v,bool): return 'true' if v else 'false'
    if isinstance(v,(list,dict)): return json.dumps(v)
    return str(v)
args=[]
for k,v in vals.items():
    if v is None: continue
    args+=['-s',f'{k}={fmt(v)}']
json.dump(args,open('flat_args.json','w'))
print(len(args)//2)
