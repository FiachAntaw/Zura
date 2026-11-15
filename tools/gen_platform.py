"""Generate a simple build-plate mesh for the Zortrax M200 Plus (binary STL, Z up, mm).

The perforated print plate sits on a slightly larger heated-bed carrier with a front handle.
Run: python3 tools/gen_platform.py
"""
import math
import os
import struct

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "ZortraxM", "resources", "meshes",
                   "zortrax_m200_plus_platform.stl")


def rounded_rect(w, d, r, seg=8, cx=0.0, cy=0.0):
    pts = []
    for qx, qy, a0 in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        ox, oy = cx + qx * (w / 2 - r), cy + qy * (d / 2 - r)
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    return pts


def prism(poly, z0, z1):
    """Triangles of a closed extruded convex polygon."""
    tris = []
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        tris.append(((cx, cy, z1), (a[0], a[1], z1), (b[0], b[1], z1)))      # top
        tris.append(((cx, cy, z0), (b[0], b[1], z0), (a[0], a[1], z0)))      # bottom
        tris.append(((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1)))  # side
        tris.append(((a[0], a[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)))
    return tris


def normal(t):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    l = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
    return nx / l, ny / l, nz / l


def main():
    tris = []
    tris += prism(rounded_rect(204, 204, 4), -3.0, -0.2)            # perforated print plate
    tris += prism(rounded_rect(222, 230, 6, cy=-2), -9.0, -3.0)     # heated-bed carrier
    tris += prism(rounded_rect(60, 14, 3, cy=-121), -7.5, -4.5)     # front handle
    for sx in (-1, 1):
        for sy in (-1, 1):                                          # plate clamps
            tris += prism(rounded_rect(10, 10, 5, 6, sx * 104, sy * 104), -3.0, -1.2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(b"Zura Zortrax M200 Plus platform".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<3f", *normal(t)))
            for v in t:
                f.write(struct.pack("<3f", *v))
            f.write(b"\0\0")
    print(f"{OUT}: {len(tris)} triangles")


if __name__ == "__main__":
    main()
