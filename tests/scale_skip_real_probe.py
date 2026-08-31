"""Compare shared-scale reconnect against a no-frame-refresh edit on a file."""
from __future__ import annotations
import importlib, sys
from pathlib import Path
import bpy
from mathutils import Vector

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

def points(obj):
    bpy.context.view_layer.update()
    e = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    m = e.to_mesh()
    try: return tuple(v.co.copy() for v in m.vertices)
    finally: e.to_mesh_clear()

def frame(stage, d):
    names=("Chain Input Pivot","Chain Input Inverse X","Chain Input Inverse Y","Chain Input Inverse Z","Chain Output Offset","Chain Output X","Chain Output Y","Chain Output Z")
    return tuple(tuple(d.modifier_input(stage,n)) for n in names)

addon=importlib.import_module(PACKAGE)
for _entry in tuple(bpy.context.preferences.addons):
    if str(getattr(_entry, "module", "")).rsplit(".", 1)[-1] == PACKAGE:
        try: bpy.context.preferences.addons.remove(_entry)
        except Exception: pass
entry=bpy.context.preferences.addons.new(); entry.module=PACKAGE; addon.register()
d=importlib.import_module(f"{PACKAGE}.cage_deform"); ch=d.chain
try:
    target=bpy.data.objects.get("Deform Merge") or bpy.context.object
    stages=tuple(ch.chain_stages(target)); cs=tuple(d.find_controller(target,s) for s in stages)
    print('TARGET', target.name, len(stages), [c.name if c else None for c in cs])
    d.core.flush_pending_chain_updates(target)
    root=cs[0]; p=root.sdh_cage_deform
    before=points(target); bf=tuple(frame(s,d) for s in stages)
    old=ch.reconnect_chain
    try:
        ch.reconnect_chain=lambda *a,**k: 0
        p.top_scale=(1.37,0.71)
        skip=points(target); sf=tuple(frame(s,d) for s in stages)
    finally: ch.reconnect_chain=old
    # restore and full edit in a fresh value to compare
    p.top_scale=(1.0,1.0); d.core.flush_pending_chain_updates(target)
    p.top_scale=(1.37,0.71)
    full=points(target); ff=tuple(frame(s,d) for s in stages)
    print('ERR', max((a-b).length for a,b in zip(full,skip)), max((Vector(a)-Vector(b)).length for x,y in zip(ff,sf) for a,b in zip(x,y)))
    print('STAGE', [max((Vector(a)-Vector(b)).length for a,b in zip(x,y)) for x,y in zip(ff,sf)])
finally:
    try: addon.unregister()
    except Exception: pass
    try: bpy.context.preferences.addons.remove(entry)
    except Exception: pass
