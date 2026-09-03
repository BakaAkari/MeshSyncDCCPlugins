"""Full-chain headless validation: Blender export → serialize → independent decode.

Covers hierarchy semantics: an empty parent + child mesh must export as two entities
with ancestor-chain paths and LOCAL transform on the child.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background --python tests/chain_headless.py
"""

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "unity_mesh_sync"))
sys.path.insert(0, str(PKG / "tests"))

import bpy  # noqa: E402
from decode_set import read_message  # noqa: E402
from unity_mesh_sync.meshsync import protocol as P  # noqa: E402
from mathutils import Vector  # noqa: E402


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.camera_add(location=(5, -5, 5))
    bpy.ops.object.light_add(type="POINT", location=(3, 3, 3))

    # hierarchy: Empty "Rig" at (10,0,0) parent of cube "Child" at local (1,0,0)
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(10, 0, 0))
    rig = bpy.context.active_object
    rig.name = "Rig"
    bpy.ops.mesh.primitive_cube_add(size=2, location=(11, 0, 0))
    cube = bpy.context.active_object
    cube.name = "Child"
    cube.parent = rig
    cube.matrix_local = rig.matrix_world.inverted() @ cube.matrix_world  # recompute local
    bpy.context.view_layer.update()

    from unity_mesh_sync.blender_exporter import export_scene
    scene = export_scene(bpy.context)
    print(f"[chain] entities: {len(scene.entities)}")
    for e in scene.entities:
        print(f"  - {type(e).__name__} path={e.path} "
              f"pos={tuple(round(x, 3) for x in e.position)}")

    msg = P.SetMessage(scene, session_id=42)
    data = msg.serialize()
    d = read_message(data)
    ents = d["entities"]
    print(f"[chain] decoded {len(data)} bytes, {len(ents)} entities")

    by_path = {e["path"]: e for e in ents}
    assert "/Rig" in by_path, f"missing parent entity: {list(by_path)}"
    assert "/Rig/Child" in by_path, f"missing child entity: {list(by_path)}"
    assert "/Camera" in by_path
    assert "/Point" in by_path

    parent = by_path["/Rig"]
    child = by_path["/Rig/Child"]
    # parent transform is its own world (no parent)
    assert parent["position"] == (10.0, 0.0, 0.0), parent["position"]
    # child transform is LOCAL relative to parent (cube at world 11 = local 1)
    assert child["position"] == (1.0, 0.0, 0.0), child["position"]
    # mesh data on the child
    assert len(child["points"]) == 8
    assert len(child["indices"]) == 24 and len(child["counts"]) == 6
    cam = by_path["/Camera"]
    assert cam["is_ortho"] is False and cam["fov"] > 0
    print("[chain] OK: hierarchy paths + local transform verified")


if __name__ == "__main__":
    main()
