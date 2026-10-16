"""Generate the loader's own menu label assets; no game fonts or models bundled."""

import json
import struct


MENU_SCRIPT = "assets/scripts/entities/3d/MainMenu.lua"

# Original 5 x 7 pixel glyphs. Rows run from top to bottom.
GLYPHS = {
    " ": [0, 0, 0, 0, 0, 0, 0],
    "-": [0, 0, 0, 31, 0, 0, 0],
    ".": [0, 0, 0, 0, 0, 12, 12],
    "|": [4, 4, 4, 4, 4, 4, 4],
    "c": [0, 0, 14, 16, 16, 16, 14],
    "p": [0, 0, 30, 17, 30, 16, 16],
    "m": [0, 0, 26, 21, 21, 17, 17],
    "o": [0, 0, 14, 17, 17, 17, 14],
    "d": [1, 1, 15, 17, 17, 17, 15],
    "l": [12, 4, 4, 4, 4, 4, 14],
    "a": [0, 0, 14, 1, 15, 17, 15],
    "e": [0, 0, 14, 17, 31, 16, 14],
    "r": [0, 0, 22, 25, 16, 16, 16],
    "s": [0, 0, 15, 16, 14, 1, 30],
    "v": [0, 0, 17, 17, 17, 10, 4],
    "0": [14, 17, 19, 21, 25, 17, 14],
    "1": [4, 12, 4, 4, 4, 4, 14],
    "2": [14, 17, 1, 2, 4, 8, 31],
    "3": [30, 1, 1, 14, 1, 1, 30],
    "4": [2, 6, 10, 18, 31, 2, 2],
    "5": [31, 16, 16, 30, 1, 1, 30],
    "6": [14, 16, 16, 30, 17, 17, 14],
    "7": [31, 1, 2, 4, 8, 8, 8],
    "8": [14, 17, 17, 14, 17, 17, 14],
    "9": [14, 17, 17, 15, 1, 1, 14],
}


def label(version: str, mod_count: int) -> str:
    return f"cpc-modloader v{version} | {mod_count} mod{'s' if mod_count != 1 else ''} loaded"


def quad() -> bytes:
    """A self-contained glTF binary with one two-sided quad."""
    vertices = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
    attributes = [
        ("POSITION", "VEC3", [c for v in vertices for c in v]),
        ("NORMAL", "VEC3", [0, 0, 1] * 4),
        ("TANGENT", "VEC4", [1, 0, 0, 1] * 4),
        ("TEXCOORD_0", "VEC2", [0, 0, 1, 0, 1, 1, 0, 1]),
    ]
    binary = b""
    views, accessors, indices = [], [], {}
    for name, kind, values in attributes:
        data = struct.pack(f"<{len(values)}f", *values)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": 34962})
        indices[name] = len(accessors)
        accessor = {"bufferView": len(views) - 1, "componentType": 5126, "count": 4, "type": kind}
        if name == "POSITION":
            accessor.update(min=[-1, -1, 0], max=[1, 1, 0])
        accessors.append(accessor)
        binary += data
    views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": 12, "target": 34963})
    accessors.append({"bufferView": len(views) - 1, "componentType": 5123, "count": 6, "type": "SCALAR"})
    binary += struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    document = {
        "asset": {"version": "2.0", "generator": "cpc-modloader"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "CPCModloaderOverlay", "mesh": 0}],
        "meshes": [{"name": "CPCModloaderOverlay", "primitives": [{"attributes": indices, "indices": len(accessors) - 1, "material": 0}]}],
        "materials": [{"doubleSided": True, "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0}}],
        "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": accessors,
    }
    header = json.dumps(document, separators=(",", ":")).encode()
    header += b" " * (-len(header) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(header) + len(binary))
            + struct.pack("<II", len(header), 0x4E4F534A) + header
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


VERTEX = """precision highp float;
layout(location = 0) in vec3 a_position;
out vec2 cpcUV;
void main() {
    cpcUV = a_position.xy * 0.5 + 0.5;
    gl_Position = vec4(a_position.xy, -0.99, 1.0);
}
"""


def assets(version: str, mod_count: int) -> dict[str, bytes]:
    text = label(version, mod_count)
    # One integer per pixel column; low bit is the top row.
    columns = []
    for character in text:
        rows = GLYPHS[character]
        columns.extend(sum(((row >> (4 - x)) & 1) << y for y, row in enumerate(rows)) for x in range(5))
        columns.append(0)
    fragment = """precision highp float;
in vec2 cpcUV;
layout(location = 0) out vec4 colorOut;
uniform float cpcScale;
const int width = WIDTH;
const int pixels[WIDTH] = int[](PIXELS);
bool ink(ivec2 p) {
    if (p.x < 0 || p.x >= width || p.y < 0 || p.y >= 7) return false;
    return (pixels[p.x] & (1 << p.y)) != 0;
}
void main() {
    // UV derivatives give the current viewport, including fullscreen and resizing.
    vec2 viewport = 1.0 / vec2(abs(dFdx(cpcUV.x)), abs(dFdy(cpcUV.y)));
    float scale = max(1.0, min(floor(cpcScale), floor((viewport.x - 16.0) / float(width))));
    ivec2 p = ivec2(floor((vec2(gl_FragCoord.x, viewport.y - gl_FragCoord.y) - 8.0) / scale));
    if (ink(p)) colorOut = vec4(1.0);
    else if (ink(p + ivec2(1, 0)) || ink(p - ivec2(1, 0)) ||
             ink(p + ivec2(0, 1)) || ink(p - ivec2(0, 1))) colorOut = vec4(0.0, 0.0, 0.0, 1.0);
    else discard;
}
""".replace("WIDTH", str(len(columns))).replace("PIXELS", ",".join(map(str, columns)))
    return {
        "assets/models/cpcmodloader_overlay.glb": quad(),
        "assets/shaders/cpcmodloader_overlay.vert": VERTEX.encode(),
        "assets/shaders/cpcmodloader_overlay.frag": fragment.encode(),
    }
