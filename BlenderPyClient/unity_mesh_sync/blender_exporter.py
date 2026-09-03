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


def _mesh_to_entity(obj: bpy.types.Object, sync_materials: bool,
                    depsgraph=None, bake_modifiers: bool = False) -> "object":
    """Extract mesh data into a protocol Mesh. Mirrors the C++ client's two mesh
    paths: raw obj.data (BakeModifiers=false, the default) or the depsgraph-
    evaluated mesh (BakeModifiers=true — modifiers like Subsurf/Mirror are
    baked into the geometry Unity receives). Faces are sent as polygons (not
    triangulated); normals are true custom split normals per loop (matching
    doExtractNonEditMeshData), uv0 per-loop. Materials: per-face material
    indices only — actual material payloads are a later milestone."""

    from .meshsync import protocol as P

    mesh = P.Mesh()
    mesh.path = _hierarchy_path(obj)
    _fill_transform(mesh, obj)

    data = obj.data
    eval_obj = None
    tmp_mesh = None
    if getattr(data, "is_editmode", False) and not bake_modifiers:
        # Live edit-mode geometry: the C++ client does the same via its
        # doExtractEditMeshData path. Reading obj.data directly in edit mode
        # gives stale verts AND half-updated loop buffers (foreach_get length
        # mismatches). bmesh.from_edit_mesh gives the current bmesh contents,
        # including uncommitted edits.
        import bmesh
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            tmp_mesh = bpy.data.meshes.new("_meshsync_edit_tmp")
            bm.to_mesh(tmp_mesh)
            tmp_mesh.materials.clear()
            for m in obj.data.materials:
                tmp_mesh.materials.append(m)
            data = tmp_mesh
        except Exception:  # noqa: BLE001 — fall back to raw (stale but safe)
            if tmp_mesh is not None:
                bpy.data.meshes.remove(tmp_mesh)
            tmp_mesh = None
            data = obj.data
    if bake_modifiers and depsgraph is not None and data is not None:
        try:
            eval_obj = obj.evaluated_get(depsgraph)
            data = eval_obj.to_mesh()
        except Exception:  # noqa: BLE001 — fall back to raw mesh
            eval_obj = None
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
    # True custom split normals per loop (smooth shading, sharp edges, normal
    # modifiers all respected). Mirrors C++ doExtractNonEditMeshData which reads
    # the same loop-normal layer. Blender 4.1+ exposes this as the
    # corner_normals attribute collection (calc_normals_split is gone).
    try:
        nrm = [0.0] * (n_loops_total * 3)
        data.corner_normals.foreach_get("vector", nrm)
        mesh.normals = [(nrm[i], nrm[i + 1], nrm[i + 2]) for i in range(0, n_loops_total * 3, 3)]
    except Exception:  # noqa: BLE001 — degenerate meshes may lack normals
        mesh.normals = []

    # uv0 per-loop
    uv_layer = None
    if data.uv_layers:
        uv_layer = data.uv_layers.active.data
    if uv_layer is not None:
        uv = [0.0] * (n_loops_total * 2)
        uv_layer.foreach_get("uv", uv)
        mesh.uv0 = [(uv[i], uv[i + 1]) for i in range(0, n_loops_total * 2, 2)]

    if eval_obj is not None:
        eval_obj.to_mesh_clear()
    if tmp_mesh is not None:
        bpy.data.meshes.remove(tmp_mesh)
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
                 sync_lights=True, sync_empties=True, bake_modifiers=False,
                 only_paths=None) -> "object":
    """Build a Scene from visible objects in the active view layer.

    Mirrors C++ exportObject semantics: every ancestor of an exported object is itself
    exported as a Transform (so Unity can rebuild the hierarchy from paths), and each
    eligible leaf is exported with its type-specific entity. Order is parent-first.

    only_paths: when given (incremental sync), restrict full serialization to
    objects whose hierarchy path is in the set; their ancestors are still
    included so the server can anchor transforms. Mirrors the C++ client's
    dirty-object subset export driven by depsgraph updates.
    """
    from .meshsync import protocol as P

    ctx = context or bpy.context
    # Flush pending deletions/renames — view_layer.objects can hold dead
    # references right after bpy.data.objects.remove until the layer updates.
    ctx.view_layer.update()
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
    if only_paths is not None:
        seeds = [o for o in seeds if _hierarchy_path(o) in only_paths]

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
    depsgraph = ctx.evaluated_depsgraph_get() if bake_modifiers else None
    entities: list = []
    for obj in ordered:
        kind = kind_of(obj)
        if kind == "mesh":
            ent = _mesh_to_entity(obj, False, depsgraph=depsgraph,
                                  bake_modifiers=bake_modifiers)
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


def scan_paths(context, sync_meshes=True, sync_cameras=True,
               sync_lights=True, sync_empties=True) -> "frozenset[str]":
    """Cheap full-scene scan: hierarchy paths of every object that would be
    exported, WITHOUT serializing any geometry. Used by incremental sync to
    detect Blender-side deletions against the server's known state."""
    ctx = context or bpy.context
    ctx.view_layer.update()

    def kind_of(obj) -> str | None:
        if obj.type == "MESH" and sync_meshes:
            return "mesh"
        if obj.type == "CAMERA" and sync_cameras:
            return "camera"
        if obj.type == "LIGHT" and sync_lights:
            return "light"
        if obj.type == "EMPTY" and sync_empties:
            return "empty"
        return None

    paths: set[str] = set()
    for o in ctx.view_layer.objects:
        if not o.visible_get():
            continue
        if kind_of(o) in ("mesh", "camera", "light"):
            cur = o
            while cur is not None:
                paths.add(_hierarchy_path(cur))
                cur = cur.parent
    return frozenset(paths)
