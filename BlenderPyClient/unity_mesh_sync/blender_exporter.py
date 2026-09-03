"""addon.blender_exporter — build protocol Scene objects from a bpy scene.

Mirrors the C++ client (msblenContext.cpp) semantics:
- Hierarchy preserved: every visible eligible object (and its ancestors) becomes an
  entity whose path is the ancestor chain "/Root/Child/Name" (same as
  msblenUtils::get_path).
- Transform = LOCAL matrix TRS (relative to parent), matching C++ extractTransformData
  with BakeTransform=false (matrix_local). Unity rebuilds the hierarchy from paths and
  composes transforms.
- Mesh vertices stay in object-local space (C++ doExtractMeshData reads mesh co
  directly); faces are sent as per-loop indices + per-face counts (NOT triangulated),
  normals/uv per-loop.
- Scene declared RightZUp (handedness=3), scale_factor=1; Unity server converts.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix


def _decompose(m: Matrix):
    """Return (pos3, quat4(x,y,z,w), scale3). matrix_local.decompose() matches
    C++ mu::extract_trs semantics closely (T * R * S)."""
    loc, rot, scl = m.decompose()
    # mathutils Quaternion exposes .x/.y/.z/.w (rotation component order in the
    # protocol is x,y,z,w — same quatf memory layout used by C++).
    return (loc.x, loc.y, loc.z), (rot.x, rot.y, rot.z, rot.w), (scl.x, scl.y, scl.z)


def _hierarchy_path(obj: bpy.types.Object) -> str:
    """Ancestor chain path like C++ msblenUtils::get_path: /Parent/Child/Name."""
    parts = []
    cur = obj
    while cur:
        parts.append(cur.name)
        cur = cur.parent
    return "/" + "/".join(reversed(parts))


def _fill_transform(ent, obj: bpy.types.Object) -> None:
    p, r, s = _decompose(obj.matrix_local)
    ent.position = p
    ent.rotation = r
    ent.scale = s
    ent.extra_flags = 0  # position+rotation+scale only (default td_flags)


def _mesh_to_entity(obj: bpy.types.Object, sync_materials: bool) -> "object":
    """Extract mesh data into a protocol Mesh. MVP sends raw (non-evaluated) mesh
    data like the C++ default (BakeModifiers=false): obj.data vertices untouched,
    faces as polygons (not triangulated), per-loop normals via split normals, uv0
    per-loop. Materials: we export per-face material indices only when the face
    actually has a slot; actual material payloads are a later milestone — without a
    material manager the server shows the default material, which is acceptable MVP."""

    from .meshsync import protocol as P

    mesh = P.Mesh()
    mesh.path = _hierarchy_path(obj)
    _fill_transform(mesh, obj)

    data = obj.data
    if data is None:
        return mesh

    # Vertex coordinates (object-local)
    n_verts = len(data.vertices)
    co = [0.0] * (n_verts * 3)
    data.vertices.foreach_get("co", co)
    mesh.points = [(co[i], co[i + 1], co[i + 2]) for i in range(0, n_verts * 3, 3)]

    # Polygons → counts + per-loop indices + per-face material id
    n_polys = len(data.polygons)
    n_loops_total = sum(p.loop_total for p in data.polygons)
    counts = [0] * n_polys
    loop_start = [0] * n_polys
    loop_total = [0] * n_polys
    mat_idx = [0] * n_polys
    data.polygons.foreach_get("loop_start", loop_start)
    data.polygons.foreach_get("loop_total", loop_total)
    data.polygons.foreach_get("material_index", mat_idx)

    indices = [0] * n_loops_total
    data.loops.foreach_get("vertex_index", indices)

    out_counts: list[int] = []
    out_material_ids: list[int] = []
    for pi in range(n_polys):
        out_counts.append(loop_total[pi])
        # C++ clamps material_index then maps through a material id table. Without a
        # material manager we send -1 for no-slot, else raw index (Unity uses default
        # material unless a matching material asset is registered later).
        mid = mat_idx[pi]
        out_material_ids.append(mid if mid >= 0 and data.materials else -1)

    mesh.counts = out_counts
    mesh.indices = indices
    mesh.material_ids = [i for i in out_material_ids] if any(i != -1 for i in out_material_ids) else []
    # Per-loop normals — MVP: per-face normal broadcast to each loop of the face.
    # (Blender 4.1+ removed use_auto_smooth; custom split normals parity is a later
    # milestone. Face normals are correct for flat-shaded / cube-like geometry.)
    mesh.normals = []
    for pi in range(n_polys):
        pn = data.polygons[pi].normal
        for _ in range(loop_total[pi]):
            mesh.normals.append((pn.x, pn.y, pn.z))

    # uv0 per-loop
    uv_layer = None
    if data.uv_layers:
        uv_layer = data.uv_layers.active.data
    if uv_layer is not None:
        uv = [0.0] * (n_loops_total * 2)
        uv_layer.foreach_get("uv", uv)
        mesh.uv0 = [(uv[i], uv[i + 1]) for i in range(0, n_loops_total * 2, 2)]

    return mesh


def _camera_to_entity(obj: bpy.types.Object) -> "object":
    from .meshsync import protocol as P

    ent = P.Camera()
    ent.path = _hierarchy_path(obj)
    _fill_transform(ent, obj)

    cam = obj.data
    ent.is_ortho = cam.type == "ORTHO"
    if cam.type == "ORTHO":
        ent.fov_or_ortho_size = cam.ortho_scale
    else:
        # Blender FOV is derived from lens+sensor. C++ uses the vertical FOV via the
        # sensor fit. mirror extractCameraData: fov = 2*atan(sensor/(2*lens)).
        if cam.sensor_fit == "VERTICAL":
            sensor = cam.sensor_height
        else:  # AUTO/HORIZONTAL default to width-based
            sensor = cam.sensor_width
        ent.fov_or_ortho_size = 2.0 * math.atan(sensor / (2.0 * cam.lens))
    ent.send_fov = True
    ent.near_plane = cam.clip_start
    ent.far_plane = cam.clip_end
    ent.send_near = True
    ent.send_far = True
    return ent


def _light_to_entity(obj: bpy.types.Object) -> "object":
    from .meshsync import protocol as P

    ent = P.Light()
    ent.path = _hierarchy_path(obj)
    _fill_transform(ent, obj)

    light = obj.data
    if light.type == "SUN":
        ent.light_type = P.LIGHT_DIRECTIONAL
        ent.intensity = light.energy
    elif light.type == "SPOT":
        ent.light_type = P.LIGHT_SPOT
        ent.spot_angle = math.degrees(light.spot_size)
        ent.send_spot_angle = True
        ent.intensity = light.energy
        ent.range = light.cutoff_distance if light.use_custom_distance else 0.0
    else:  # POINT / AREA
        ent.light_type = P.LIGHT_POINT if light.type == "POINT" else P.LIGHT_AREA
        ent.intensity = light.energy
        ent.range = light.cutoff_distance if light.use_custom_distance else 10.0

    # Rough Blender energy → Unity intensity approximation (documented; C++ uses a
    # per-light-type conversion table that we approximate with a flat factor).
    ent.intensity = ent.intensity * 2.0
    c = light.color
    ent.color = (c.r, c.g, c.b, 1.0)
    return ent


def export_scene(context=None, sync_meshes=True, sync_cameras=True,
                 sync_lights=True, sync_empties=True) -> "object":
    """Build a Scene from visible objects in the active view layer.

    Mirrors C++ exportObject semantics: every ancestor of an exported object is itself
    exported as a Transform (so Unity can rebuild the hierarchy from paths), and each
    eligible leaf is exported with its type-specific entity. Order is parent-first.
    """
    from .meshsync import protocol as P

    ctx = context or bpy.context
    scene = P.Scene()

    def kind_of(obj: bpy.types.Object) -> str | None:
        if obj.type == "MESH" and sync_meshes:
            return "mesh"
        if obj.type == "CAMERA" and sync_cameras:
            return "camera"
        if obj.type == "LIGHT" and sync_lights:
            return "light"
        if obj.type == "EMPTY" and sync_empties:
            return "empty"
        return None

    # 1) every visible object that carries syncable content is a seed
    seeds: list[bpy.types.Object] = [
        o for o in ctx.view_layer.objects
        if o.visible_get() and kind_of(o) in ("mesh", "camera", "light")
    ]

    # 2) ancestors of seeds must be exported too (parents anchor hierarchy paths)
    need: dict[str, bpy.types.Object] = {}
    for seed in seeds:
        cur: bpy.types.Object | None = seed
        while cur is not None:
            need[cur.name] = cur
            cur = cur.parent

    # 3) export by increasing depth so parents come before children (C++ order)
    def depth(obj: bpy.types.Object) -> int:
        d = 0
        cur = obj.parent
        while cur is not None:
            d += 1
            cur = cur.parent
        return d

    ordered = sorted(need.values(), key=lambda o: (depth(o), o.name))
    entities: list = []
    for obj in ordered:
        kind = kind_of(obj)
        if kind == "mesh":
            ent = _mesh_to_entity(obj, False)
        elif kind == "camera":
            ent = _camera_to_entity(obj)
        elif kind == "light":
            ent = _light_to_entity(obj)
        else:
            ent = P.Transform()
            ent.path = _hierarchy_path(obj)
            _fill_transform(ent, obj)
        entities.append(ent)

    scene.entities = entities
    return scene
