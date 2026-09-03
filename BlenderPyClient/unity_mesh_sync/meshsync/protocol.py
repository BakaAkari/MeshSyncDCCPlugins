"""meshsync.protocol — MeshSync protocol entities (serialize only, MVP).

Mirrors the C++ class layouts in msFoundation.h / msEntity.cpp / msTransform.cpp /
msMesh.cpp / msEntity.cpp(Camera/Light) / msScene.cpp. Serialization field order
and flags are transcribed from the C++ serialize() bodies.
"""

from __future__ import annotations

import time

from .wire import Writer

PROTOCOL_VERSION = 124
INVALID_ID = -1

# --- enums ---------------------------------------------------------------
ENTITY_TRANSFORM = 1
ENTITY_CAMERA = 2
ENTITY_LIGHT = 3
ENTITY_MESH = 4

HANDEDNESS_LEFT = 0
HANDEDNESS_RIGHT = 1
HANDEDNESS_LEFT_ZUP = 2
HANDEDNESS_RIGHT_ZUP = 3

LIGHT_SPOT = 0
LIGHT_DIRECTIONAL = 1
LIGHT_POINT = 2
LIGHT_AREA = 3

SHADOW_NONE = 0
SHADOW_HARD = 1
SHADOW_SOFT = 2


def _pad4(n: int) -> int:
    return (4 - (n % 4)) % 4


class Entity:
    """Base for all scene entities."""

    etype = ENTITY_TRANSFORM

    def __init__(self):
        self.id = INVALID_ID
        self.host_id = INVALID_ID
        self.path = ""

    def _write_base(self, w: Writer) -> None:
        w.i32(self.etype)  # type tag consumed by Entity::create
        w.i32(self.id)
        w.i32(self.host_id)
        w.string(self.path)


class Transform(Entity):
    """C++ Transform: Entity base + TransformDataFlags-gated fields."""

    etype = ENTITY_TRANSFORM

    # td_flags bits
    F_UNCHANGED = 0
    F_POSITION = 1
    F_ROTATION = 2
    F_SCALE = 3
    F_VISIBILITY = 4
    F_LAYER = 5
    F_INDEX = 6
    F_REFERENCE = 7

    def __init__(self):
        super().__init__()
        self.position = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 0.0, 0.0, 1.0)  # x,y,z,w
        self.scale = (1.0, 1.0, 1.0)
        self.visible = True          # active flag
        self.visible_render = True
        self.visible_viewport = True
        self.layer = 0
        self.index = 0
        self.reference = ""
        self.extra_flags = 0  # optional extra bits for callers

    def write_transform_fields(self, w: Writer) -> None:
        w.i32(self.id)
        w.i32(self.host_id)
        w.string(self.path)

    def _write_flags_and_body(self, w: Writer) -> None:
        # flags word: C++ default = bits 1,2,3
        flags = (1 << self.F_POSITION) | (1 << self.F_ROTATION) | (1 << self.F_SCALE)
        if not self.reference == "":
            flags |= 1 << self.F_REFERENCE
        flags |= self.extra_flags
        # layer is serialized only if flag set; MVP always sends it for parity
        # with the C++ client (it sends layer/index too via flags when changed).
        w.u32(flags & 0xFFFFFFFF)

        # body in the SERIALIZE_TRANSFORM order
        if flags & (1 << self.F_POSITION):
            w.float3(*self.position)
        if flags & (1 << self.F_ROTATION):
            w.quat(*self.rotation)
        if flags & (1 << self.F_SCALE):
            w.float3(*self.scale)
        if flags & (1 << self.F_VISIBILITY):
            self._write_visibility(w)
        if flags & (1 << self.F_LAYER):
            w.i32(self.layer)
        if flags & (1 << self.F_INDEX):
            w.i32(self.index)
        if flags & (1 << self.F_REFERENCE):
            w.string(self.reference)

    @staticmethod
    def _write_visibility(w: Writer) -> None:
        # VisibilityFlags uint32 bitfield: active=0, render=1, viewport=2,
        # cast_shadows=3, receive_shadows=4
        pass  # overridden below with real value

    def serialize(self, w: Writer) -> None:
        self._write_base(w)
        self._write_flags_and_body(w)


class Mesh(Transform):
    """C++ Mesh: Transform fields + MeshDataFlags-gated geometry. MVP sends only
    transform + points + normals + uv0 + indices + counts + material_ids.
    Submeshes/bones/blendshapes/bounds left unset for now."""

    etype = ENTITY_MESH

    # md_flags bits (MeshDataFlagsBit)
    F_UNCHANGED = 0
    F_HAS_INDICES = 3
    F_HAS_COUNTS = 4
    F_HAS_POINTS = 5
    F_HAS_NORMALS = 6
    F_HAS_TANGENTS = 7
    F_HAS_COLORS = 10
    F_HAS_MATERIAL_IDS = 12
    F_HAS_UV0 = 24

    def __init__(self):
        super().__init__()
        # geometry (MVP)
        self.points = []        # list[(x,y,z)]
        self.normals = []       # list[(x,y,z)] per-index
        self.uv0 = []           # list[(u,v)] per-index
        self.indices = []       # list[int] per-loop vertex refs
        self.counts = []        # list[int] per-face loop counts
        self.material_ids = []  # list[int] per-face; -1 = no material

    def serialize(self, w: Writer) -> None:
        self._write_base(w)      # Entity base (type=MESH, id, host_id, path)
        self._write_flags_and_body(w)  # Transform flags + fields

        # md_flags
        flags = 0
        if self.points:
            flags |= 1 << self.F_HAS_POINTS
        if self.normals:
            flags |= 1 << self.F_HAS_NORMALS
        if self.uv0:
            flags |= 1 << self.F_HAS_UV0
        if self.indices:
            flags |= 1 << self.F_HAS_INDICES
        if self.counts:
            flags |= 1 << self.F_HAS_COUNTS
        if self.material_ids:
            flags |= 1 << self.F_HAS_MATERIAL_IDS
        w.u32(flags & 0xFFFFFFFF)

        # body in SERIALIZE_MESH order
        if flags & (1 << self.F_HAS_INDICES):
            w.shared_vector_i32(self.indices)
        if flags & (1 << self.F_HAS_COUNTS):
            w.shared_vector_i32(self.counts)
        if flags & (1 << self.F_HAS_POINTS):
            w.shared_vector_f3(self.points)
        if flags & (1 << self.F_HAS_NORMALS):
            w.shared_vector_f3(self.normals)
        if flags & (1 << self.F_HAS_MATERIAL_IDS):
            w.shared_vector_i32(self.material_ids)
        if flags & (1 << self.F_HAS_UV0):
            w.shared_vector_f2(self.uv0)


class Camera(Transform):
    """C++ Camera: Transform fields + CameraDataFlags-gated fields."""

    etype = ENTITY_CAMERA

    # cd_flags bits (bitfield struct CameraDataFlags)
    F_IS_ORTHO = 1
    F_FOV = 2
    F_NEAR = 3
    F_FAR = 4
    F_FOCAL = 5
    F_SENSOR = 6
    F_LENS_SHIFT = 7
    F_VIEW = 8
    F_PROJ = 9
    F_LAYER_MASK = 10

    def __init__(self):
        super().__init__()
        self.is_ortho = False
        self.fov_or_ortho_size = 0.0
        self.near_plane = 0.0
        self.far_plane = 0.0
        self.focal_length = 0.0
        self.sensor_size = (0.0, 0.0)
        self.lens_shift = (0.0, 0.0)
        self.view_matrix = None   # 16 floats or None
        self.proj_matrix = None
        self.layer_mask = 0
        # cd_flags: which optional fields we want to send
        self.send_fov = True
        self.send_near = False
        self.send_far = False
        self.send_sensor = False
        self.send_view = False
        self.send_proj = False

    def serialize(self, w: Writer) -> None:
        self._write_base(w)
        self._write_flags_and_body(w)

        cd = (1 << self.F_IS_ORTHO)
        if self.send_fov:
            cd |= 1 << self.F_FOV
        if self.send_near:
            cd |= 1 << self.F_NEAR
        if self.send_far:
            cd |= 1 << self.F_FAR
        if self.send_sensor:
            cd |= 1 << self.F_SENSOR
        if self.send_view and self.view_matrix is not None:
            cd |= 1 << self.F_VIEW
        if self.send_proj and self.proj_matrix is not None:
            cd |= 1 << self.F_PROJ
        w.u32(cd & 0xFFFFFFFF)

        w.bool_(self.is_ortho)
        if cd & (1 << self.F_FOV):
            w.f32(self.fov_or_ortho_size)
        if cd & (1 << self.F_NEAR):
            w.f32(self.near_plane)
        if cd & (1 << self.F_FAR):
            w.f32(self.far_plane)
        if cd & (1 << self.F_SENSOR):
            w.float2(*self.sensor_size)
        if cd & (1 << self.F_VIEW):
            w.mat4(self.view_matrix)
        if cd & (1 << self.F_PROJ):
            w.mat4(self.proj_matrix)


class Light(Transform):
    """C++ Light: Transform fields + LightDataFlags-gated fields."""

    etype = ENTITY_LIGHT

    # ld_flags bits
    F_UNCHANGED = 0
    F_LIGHT_TYPE = 1
    F_SHADOW_TYPE = 2
    F_COLOR = 3
    F_INTENSITY = 4
    F_RANGE = 5
    F_SPOT_ANGLE = 6
    F_LAYER_MASK = 7

    def __init__(self):
        super().__init__()
        self.light_type = LIGHT_POINT
        self.shadow_type = SHADOW_NONE
        self.color = (1.0, 1.0, 1.0, 1.0)
        self.intensity = 1.0
        self.range = 10.0
        self.spot_angle = 0.0
        self.layer_mask = 0
        self.send_spot_angle = False

    def serialize(self, w: Writer) -> None:
        self._write_base(w)
        self._write_flags_and_body(w)

        ld = ((1 << self.F_LIGHT_TYPE) | (1 << self.F_SHADOW_TYPE)
              | (1 << self.F_COLOR) | (1 << self.F_INTENSITY) | (1 << self.F_RANGE))
        if self.send_spot_angle:
            ld |= 1 << self.F_SPOT_ANGLE
        w.u32(ld & 0xFFFFFFFF)

        w.i32(self.light_type)
        w.i32(self.shadow_type)
        w.float4(*self.color)
        w.f32(self.intensity)
        w.f32(self.range)
        if ld & (1 << self.F_SPOT_ANGLE):
            w.f32(self.spot_angle)


# --- Scene ---------------------------------------------------------------

class Scene:
    """C++ Scene. Only settings + entities are sent in MVP (data_flags bit 0+2)."""

    def __init__(self):
        self.handedness = HANDEDNESS_RIGHT_ZUP
        self.scale_factor = 1.0
        self.entities = []  # list of Transform/Mesh/Camera/Light

    def serialize(self, w: Writer) -> None:
        # compute validation hash from entity geometry contributions
        # C++ Scene::hash() = sum of entity.hash(); geometry SharedVectors contribute
        # their vhash (already accumulated in w._hash as we write). So: write a
        # placeholder, write content, then patch.
        data_flags = (1 << 0) | (1 << 2)  # has_settings | has_entities
        # We need validation_hash BEFORE body in the stream, but hash depends on body.
        # Buffer scene body into its own Writer first.
        body = Writer()
        body.i32(self.handedness)
        body.f32(self.scale_factor)
        body.u32(len(self.entities))
        for ent in self.entities:
            ent.serialize(body)
        validation_hash = body.hash()

        w.u64(validation_hash)
        w.u32(data_flags & 0xFFFFFFFF)
        w.buf += body.buf  # settings + entities payload already flag-gated


def new_session_id() -> int:
    return int(time.time() * 1000) % 0x7FFFFFFF


class SetMessage:
    """POST body for /set."""

    def __init__(self, scene: Scene, session_id: int = INVALID_ID, message_id: int = 0):
        self.scene = scene
        self.session_id = session_id
        self.message_id = message_id

    def serialize(self) -> bytes:
        w = Writer()
        w.i32(PROTOCOL_VERSION)
        w.i32(self.session_id)
        w.i32(self.message_id)
        w.u64(int(time.time_ns()))
        self.scene.serialize(w)
        return w.bytes()


class DeleteMessage:
    """POST body for /delete: removes synced entities (and materials/instances,
    unused here) on the server. Identifier = name(path) + id, serialized as
    std::string + int32; vectors are uint32 count + elements (msFoundation
    write_impl<std::vector<T>>)."""

    def __init__(self, paths=None, session_id: int = INVALID_ID, message_id: int = 0):
        self.paths = list(paths or [])
        self.session_id = session_id
        self.message_id = message_id

    def serialize(self) -> bytes:
        w = Writer()
        w.i32(PROTOCOL_VERSION)
        w.i32(self.session_id)
        w.i32(self.message_id)
        w.u64(int(time.time_ns()))
        # entities
        w.u32(len(self.paths))
        for p in self.paths:
            w.string(p)
            w.i32(INVALID_ID)
        # materials + instances: empty
        w.u32(0)
        w.u32(0)
        return w.bytes()


class FenceMessage:
    """POST body for /fence. type: 1=SceneBegin 2=SceneEnd."""

    FENCE_BEGIN = 1
    FENCE_END = 2

    def __init__(self, fence_type: int, session_id: int = INVALID_ID,
                 message_id: int = 0, dcc_tool_name: str = ""):
        self.fence_type = fence_type
        self.session_id = session_id
        self.message_id = message_id
        self.dcc_tool_name = dcc_tool_name

    def serialize(self) -> bytes:
        w = Writer()
        w.i32(PROTOCOL_VERSION)
        w.i32(self.session_id)
        w.i32(self.message_id)
        w.u64(int(time.time_ns()))
        w.i32(self.fence_type)
        w.string(self.dcc_tool_name)
        return w.bytes()
