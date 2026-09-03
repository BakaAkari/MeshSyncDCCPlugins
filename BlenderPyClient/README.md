# MeshSync BlenderPyClient — pure-Python Live Link (protocol v124)

Ground-up pure-Python replacement for the abandoned C++ Blender client
(`Plugins~/Src/MeshSyncClientBlender`). Targets Blender 5.2 LTS (2026) and newer;
Unity MeshSyncServer needs **zero changes** — we emit the same binary wire bytes.

## Layout

```
unity_mesh_sync/           installable Blender addon package (zip root)
unity_mesh_sync/meshsync/  engine-agnostic wire protocol + HTTP client (no bpy imports → reusable for Godot)
tests/                     unit tests + headless Blender chain tests
tools/build_addon_zip.py   builds dist/UnityMeshSync-Blender-<version>.zip (version from bl_info)
docs/                      PROTOCOL-NOTES.md — reverse-engineered wire contract (maintenance doc)
```

## Install

Download `UnityMeshSync-Blender-<version>.zip` from the GitHub Releases page, then
Blender → Edit → Preferences → Add-ons → Install from Disk → pick the zip → enable
"Unity Mesh Sync". Panel: View3D → Sidebar → MeshSync. Default port 18080 matches
the Unity MeshSync package out of the box.

## Status (2026-09-02)

VERIFIED (real tool output):
- 8/8 wire/protocol unit tests pass (`python3 tests/test_wire_protocol.py`)
- Blender 5.2.0 headless export + serialize + decode round-trips through an
  independent reader built from the C++ deserialize layouts:
  - cube (8 verts / 6 quads / 24 loops), UV sphere (114/128/480), Suzanne (507/500/1968)
  - normals and uv0 are per-loop and index-consistent (asserted)
- Hierarchy semantics verified: empty parent `/Rig` + child mesh `/Rig/Child` export as
  two entities, child transform is LOCAL (relative to parent), parent transform world
  — matching C++ msblenUtils::get_path + matrix_local extract_trs (tests/chain_headless.py)
- validation_hash algorithm matches C++ `Scene::hash()`/`vhash_impl<SharedVector>`
  (Unity parses via the SAME C++ SceneGraph in Runtime/Plugins mscore)
- addon register/unregister smoke passes inside Blender 5.2

NOT yet verified (requires live Unity):
- End-to-end sync into a running Unity MeshSyncServer. The default port in this fork is
  **18080** (the upstream default 8080 conflicts with a local MLX model server); no Unity
  editor is currently running. When testing, set the Unity MeshSyncServer's port to match
  the addon's (18080).
  Blocking uncertainties to watch on first live test:
  - Scene.validation_hash parity (unit-tested against C++ source, needs real server)
  - camera/light field semantics and energy conversions (approximated, documented)

## How to run

```bash
# unit tests
python3 tests/test_wire_protocol.py

# headless export+serialize+decode (needs Blender 5.2)
/Applications/Blender.app/Contents/MacOS/Blender --background --python tests/smoke_headless.py
/Applications/Blender.app/Contents/MacOS/Blender --background --python tests/chain_headless.py

# manual: install addon/ directory as a Blender addon, open 3D viewport sidebar
# → MeshSync → set host/port → Test Connection → Sync
```

## Live Unity acceptance checklist

1. Open/create a Unity project (2022.3 LTS), add MeshSync package from
   `~/code/MeshSync` (or a release), place a MeshSyncServer object in a scene.
2. Set the MeshSyncServer port to **18080** (must match the addon's default; edit the
   MeshSyncServer component or Project Settings → MeshSync).
3. Run the server in the editor (Play or edit mode; MeshSyncServer works in edit mode).
4. In Blender: connect to `host:port`, Test Connection, Sync, verify cube appears.
5. If the scene is rejected, most likely cause is Scene.validation_hash mismatch —
   capture the Unity console error and diff against `Scene::hash()` in msScene.cpp.

## Deviations from C++ client (documented, refine later)

- Normals: per-face normal broadcast per loop (custom split/smooth normals parity is a
  later milestone; Blender 4.1+ removed use_auto_smooth).
- Materials: only per-face material slot indices are sent (-1 when none); no material
  payloads yet — server shows default material. Requires the C++ material-id manager
  semantics for real material sync.
- No bones/armatures/blendshapes/curves/submeshes/bounds/scene-cache yet.
- Light energy conversion is a flat ×2 approximation; C++ uses per-type conversion.
- Camera orientation parity (Blender −Z → Unity +Z) is NOT applied yet — if the first
  live test shows flipped cameras, port `applyCorrectionIfNeeded` from msblenEntityHandler.
