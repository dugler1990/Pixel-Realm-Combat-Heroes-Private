"""Where is the neck? Narrowest horizontal cross-section between the shoulders and the skull."""
import bpy, json
import numpy as np
GLB = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_wingweights.glb"
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=GLB)
arm=[o for o in bpy.data.objects if o.type=='ARMATURE'][0]
mesh=[o for o in bpy.data.objects if o.type=='MESH'][0]
R=json.load(open(ROLE))
gi={vg.index: vg.name for vg in mesh.vertex_groups}
head_bone=R["neck"]          # bone_13, the mislabelled head
mw=mesh.matrix_world
P=[]
for v in mesh.data.vertices:
    gs={gi.get(g.group): g.weight for g in v.groups if g.weight>0.001}
    if not gs: continue
    if max(gs,key=gs.get)==head_bone:
        P.append(mw@v.co)
P=np.array([[p.x,p.y,p.z] for p in P])
print("bone_13-dominant verts:", len(P), "z %.3f .. %.3f" % (P[:,2].min(), P[:,2].max()), flush=True)
b13=arm.data.bones[head_bone]; b12=arm.data.bones[R["chest"]]
amw=arm.matrix_world
print("bone_12 tail z %.3f, bone_13 head z %.3f tail z %.3f" % (
    (amw@b12.tail_local).z, (amw@b13.head_local).z, (amw@b13.tail_local).z), flush=True)
lo,hi=P[:,2].min(),P[:,2].max()
print("\n   z      n    radius(p90 of sqrt(x^2+y^2) about the axis)", flush=True)
axis_x, axis_y = 0.002, -0.04
best=None
for i in range(28):
    z0=lo+(hi-lo)*i/28.0; z1=lo+(hi-lo)*(i+1)/28.0
    m=(P[:,2]>=z0)&(P[:,2]<z1)
    if m.sum()<40: continue
    r=np.sqrt((P[m,0]-axis_x)**2+(P[m,1]-axis_y)**2)
    rad=np.percentile(r,90)
    bar="#"*int(rad*260)
    print("%6.3f %6d   %6.3f %s" % ((z0+z1)/2, m.sum(), rad, bar), flush=True)
