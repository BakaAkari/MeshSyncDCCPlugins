# MeshSync wire protocol notes (protocol_version=124)

Source: reverse-engineered from unity3d-jp/MeshSync Plugin~/Src (C++), dev branch.
This document is the maintenance contract for the pure-Python client. All offsets/types
below were transcribed from C++ serialize() implementations.

## 1. Primitive encoding (msFoundation.h)

- Little-endian, raw struct memory layout. 4-byte alignment enforced.
- Scalar written raw with its C++ sizeof (int=4, float=4, double/uint64=8, float2=8,
  float3=12, float4=16, quatf=16, float4x4=64).
- bool: 1 byte then padded with 3 zero bytes (write_align).
- std::string: `uint32 len` + bytes + zero pad to 4-byte multiple of len.
- SharedVector<T> (big arrays): `uint32 count` + raw T[count] + pad to 4-byte multiple
  of (sizeof(T)*count). count is element count.
- std::vector<T>: `uint32 count` + each element serialized via write() (elements that
  are serializable write their type+data; plain structs written raw).
- std::vector<std::shared_ptr<T>> / object ptrs: `uint32 count` + each object serialize.
  A single shared_ptr<T> object: just serialize() — no length prefix, no null handling.
- Structs without msSerializable (Bounds, SubmeshData) are written raw via sizeof
  (no padding inside; field layout below).

## 2. EntityType (msEntityType.h) — int32

Unknown=0, Transform=1, Camera=2, Light=3, Mesh=4, Points=5, Curve=6

## 3. Entity base (msEntity.cpp)

```
int32 type              # EntityType value
int32 id                # default -1 (InvalidID)
int32 host_id           # default -1
string path             # hierarchy path e.g. "/Cube"
```

## 4. Message base (msProtocol.cpp)

```
int32  protocol_version = 124
int32  session_id       # -1 or per-session
int32  message_id
uint64 timestamp_send   # nanoseconds
```

## 5. Scene (msScene.cpp)

serialize():
```
uint64 validation_hash      # = hash(); server validates on read
uint32 data_flags           # bitfield SceneDataFlags
if flags.has_settings:        SceneSettings settings        # always true
if flags.has_assets:          vector<Asset> assets
if flags.has_entities:        vector<Transform> entities    # actual runtime type via EntityType int32 inside each
if flags.has_constraints:     vector<Constraint> constraints
if flags.has_instanceInfos:   vector<InstanceInfo> instanceInfos
if flags.has_propertyInfos:   vector<PropertyInfo> propertyInfos
if flags.has_instanceMeshes:  vector<Transform> instanceMeshes
```
SceneDataFlags bits (bitfield, LSB first): has_settings=0, has_assets=1,
has_entities=2, has_constraints=3, has_instanceInfos=4, has_propertyInfos=5,
has_instanceMeshes=6.

SceneSettings (msSceneSettings.h):
```
int32 handedness   # enum Handedness: Left=0, Right=1, LeftZUp=2, RightZUp=3
float scale_factor # default 1.0
```
Scene::hash() = sum over entities of entity.hash() (mesh geometry only contributes;
Transform/Camera/Light return 0 unless Mesh).

## 6. Transform (msTransform.cpp)

Entity base +:
```
uint32 td_flags
if unchanged(bit0): return
if has_position(1):    float3 position
if has_rotation(2):    quatf rotation
if has_scale(3):       float3 scale
if has_visibility(4):  uint32 visibility
if has_layer(5):       int32 layer
if has_index(6):       int32 index
if has_reference(7):   string reference
if has_user_properties(8): vector<Variant> user_properties
```
TransformDataFlags default constructor sets bits 1,2,3 (position+rotation+scale).

VisibilityFlags (uint32 bitfield): active=0, visible_in_render=1, visible_in_viewport=2,
cast_shadows=3, receive_shadows=4.
C++ VisibilityFlags() default ctor: active=1, visible_in_render=1, visible_in_viewport=1,
cast_shadows=1, receive_shadows=1 → value 0b11111 = 31.

## 7. Mesh (msMesh.cpp)

Entity base + Transform (as above: td_flags + transform fields) then:
```
uint32 md_flags
if unchanged(bit0): return
if has_refine_settings(2):  MeshRefineSettings
if has_indices(3):          SharedVector<int32> indices
if has_counts(4):           SharedVector<int32> counts
if has_points(5):           SharedVector<float3> points
if has_normals(6):          SharedVector<float3> normals
if has_tangents(7):         SharedVector<float4> tangents
if has_colors(10):          SharedVector<float4> colors
if has_velocities(11):      SharedVector<float3> velocities
if has_material_ids(12):    SharedVector<int32> material_ids
if has_root_bone(14):       string root_bone
if has_bones(15):           vector<BoneData> bones
if has_blendshapes(16):     vector<BlendShapeData> blendshapes
if has_submeshes(18):       vector<SubmeshData> submeshes   # raw structs, 16B each
if has_bounds(19):          Bounds                          # raw struct, 24B
uvs 24..31: each present → SharedVector<float2> m_uv[i]
```
MeshDataFlags bits: unchanged=0, topology_unchanged=1, has_refine_settings=2,
has_indices=3, has_counts=4, has_points=5, has_normals=6, has_tangents=7,
has_colors=10, has_velocities=11, has_material_ids=12, has_face_groups=13,
has_root_bone=14, has_bones=15, has_blendshapes=16, has_blendshape_weights=17,
has_submeshes=18, has_bounds=19, has_uv0..7=24..31.
NOTE md_flags serialization writes 4 bytes (uint32) — but MeshDataFlags is a struct
with a uint32 m_bitFlags member.

MeshRefineSettings (serialize order, conditional):
```
uint32 flags                 # MeshRefineFlags (default 0)
uint32 max_bone_influence    # default 255
float  scale_factor          # default 1.0
if split: uint32 split_unit                    # default 0xffffffff
if gen_normals_with_smooth_angle: float smooth_angle
if local2world: float4x4 local2world
if world2local: float4x4 world2local
if mirror_basis: float4x4 mirror_basis
if quadify||quadify_full_search: float quadify_threshold
```
MESH_DATA_FLAG_HAS_REFINE_SETTINGS is only set when flags != 0 or scale != 1. For a
minimal sync leave refine settings out (flag unset).

SubmeshData raw 16B: int32 index_count, int32 index_offset, int32 topology(enum
Topology: Points=0,Lines=1,Triangles=2,Quads=3), int32 material_id.
Bounds raw 24B: float3 center, float3 extents.

## 8. Camera (msEntity.cpp Camera region)

Entity + Transform then:
```
uint32 cd_flags
if unchanged: return
if has_is_ortho(1):        bool is_ortho
if has_fov_or_ortho_size(2): float
if has_near_plane(3):      float
if has_far_plane(4):       float
if has_focal_length(5):    float
if has_sensor_size(6):     float2
if has_lens_shift(7):      float2
if has_view_matrix(8):     float4x4
if has_proj_matrix(9):     float4x4
if has_layer_mask(10):     int32
```
CameraDataFlags default ctor: unchanged=0, has_is_ortho=1, all else 0.
(Camera ctor sets flags: is_ortho, near_plane=0.3? far=1000? — see C++ clear() if you
need exact defaults; from camera.h defaults set by code: is_ortho false etc.)

## 9. Light (msLight.cpp)

Entity + Transform then:
```
uint32 ld_flags
if unchanged(0): return
if has_light_type(1):   int32 light_type  # enum LightType: Unknown=-1,Spot=0,Directional=1,Point=2,Area=3
if has_shadow_type(2):  int32 shadow_type # enum ShadowType: Unknown=-1,None=0,Hard=1,Soft=2
if has_color(3):        float4 color
if has_intensity(4):    float intensity
if has_range(5):        float range
if has_spot_angle(6):   float spot_angle
if has_layer_mask(7):   int32 layer_mask
```
LightDataFlags default ctor sets bits 1..5 (type, shadow, color, intensity, range).

## 10. Message payload classes

SetMessage:  Message base + Scene.
DeleteMessage: Message base + vector<Identifier> entities + vector<Identifier> materials
  + vector<Identifier> instances. Identifier = string name + int32 id.
FenceMessage: Message base + int32 type (FenceType: Unknown=0, SceneBegin=1, SceneEnd=2)
  + string dcc_tool_name.

## 11. HTTP transport (msClient.cpp)

- Default server port 18080 (BakaAkari fork default; upstream was 8080).
  msClientSettings.h default also 8080 in upstream C++ client — our Python client uses 18080.
- POST /protocol_version → returns raw int32 protocol version? (GET request). Client queries
  with HTTPRequest GET "/protocol_version" and expects numeric response.
- set/delete/fence endpoints are HTTP POST with path "set"/"delete"/"fence",
  Content-Type application/octet-stream, body = serialized message, Expect: 100-continue.
- Response: HTTP 200 OK (empty body) on success.
- No zstd compression on these messages (serveBinary only used for file/text endpoints).

## 12. Blender source conventions (from MeshSyncDCCPlugins msblenContext.cpp)

- scene_settings.handedness = Handedness::RightZUp (3), scale_factor=1.
- Object path: paths.get_path(obj) builds "/" + ancestor names.
- Object transform: extractTransformData → position/rotation/scale from LOCAL matrix
  (or zero/identity/one when BakeTransform), world/local matrix stored separately.
  Camera/light correction: Blender cameras/lights face -Z; Unity +Z. C++ applies
  camera_correction matrix on world matrix when is_camera||is_light.
  For this Python MVP: bake object world matrix into transform (send position/rot/scale
  from world, identity local semantics) or replicate extract_trs on local matrix — decide
  in exporter; wire format itself is engine-agnostic.
- Mesh export (doExtractMeshData): points from mesh verts as-is (Z-up right-handed).
  indices/counts: per-polygon loops — counts[poly]=totloop, indices = loop vertex refs
  in poly order (NOT triangulated). material_ids per-face (mid_table lookup; faces w/o
  material → -1). normals per-index (per-loop), uv per-index (per-loop, m_uv[i]),
  colors per-index.
- Visible objects only; visibility flags: visible_in_collection/render/viewport.

## MVP scope (Phase 1)

Mesh (points, indices, counts, material_ids, per-index normals+uv0) + Transform +
Camera + Light. No blendshapes/bones/submeshes/bounds → leave those flags clear
(bounds needed only if server requires; test first without).
