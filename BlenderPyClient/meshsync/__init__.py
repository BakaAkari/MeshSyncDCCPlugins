"""meshsync — pure-Python MeshSync wire client (protocol v124).

No Blender imports in this package: it can back any DCC/exporter host (Blender,
later Godot) as long as the caller produces protocol objects.
"""

from .wire import Writer
from . import protocol  # noqa: F401  (re-export surface)

__all__ = ["Writer", "protocol"]
__version__ = "0.1.0"
