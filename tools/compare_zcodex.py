"""Compare two .zcodex2 files (e.g. Cura vs Z-Suite) by simulating their toolpaths.

Usage: python3 tools/compare_zcodex.py A.zcodex2 B.zcodex2 [--labels A B] [--png-dir DIR] [--json OUT]

Prints header and per-feature statistics; with --png-dir also renders layer views (needs Pillow).
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "ZortraxM"))
from zcodex import container  # noqa: E402
from zcodex.commands import Op, MoveType, iter_commands, decode_axes as _decode  # noqa: E402


def decode_axes(args):
    return {k.lower(): v for k, v in _decode(args).items()}

GROUPS = {  # move type -> report group
    "Raft": {10, 11, 12, 13},
    "Outer wall": {0, 22, 36, 20, 21},
    "Inner walls": {2},
    "Top/bottom skin": {1, 14, 15, 16, 45, 46},
    "Infill": {3, 23},
    "Support": {4, 5, 6, 7, 8, 9, 24, 32},
    "Bridges": {25},
    "Other extrusion": set(),
}
GROUP_OF = {t: g for g, ts in GROUPS.items() for t in ts}
COLOURS = {"Raft": (150, 150, 150), "Outer wall": (220, 50, 47), "Inner walls": (38, 139, 210),
           "Top/bottom skin": (211, 160, 0), "Infill": (133, 153, 0), "Support": (108, 113, 196),
           "Bridges": (203, 75, 22), "Other extrusion": (0, 0, 0)}


def simulate(path):
    header, _, entries = container.read(open(path, "rb").read())
    data = entries["ZCodeData"]
    x = y = z = 0
    feed = 0
    layer = None
    st = {"header": header, "layers": {}, "groups": defaultdict(lambda: {"len": 0.0, "e": 0.0, "time": 0.0, "fw": 0.0}),
          "travel_mm": 0.0, "travel_time": 0.0, "retractions": 0, "retract_mm": 0.0, "jumps": 0, "z_hops": 0,
          "commands": 0, "fan": [], "temps": [], "segments": defaultdict(list), "layer_z": {}}
    for op, args in iter_commands(data):
        st["commands"] += 1
        if op == Op.SET_FEEDRATE:
            feed = int.from_bytes(args[:4], "little", signed=True)
        elif op == Op.LAYER:
            layer = int.from_bytes(args[:4], "little", signed=True)
        elif op == Op.SET_AS_VALUE:
            a = decode_axes(args)
            x, y, z = a.get("x", x), a.get("y", y), a.get("z", z)
        elif op == Op.SET_EXTRUDER_TEMPERATURE:
            st["temps"].append(int.from_bytes(args[1:5], "little", signed=True))
        elif op in (Op.PRINT_MOVE, Op.PRINT_JUMP):
            mtype, a = args[0], decode_axes(args[1:])
            if "fan2" in a:
                st["fan"].append((layer, a["fan2"]))
            nx, ny, nz = a.get("x", x), a.get("y", y), a.get("z", z)
            d = math.dist((x, y, z), (nx, ny, nz)) / 1000.0
            t = d / (feed / 60.0) if feed else 0.0
            e = a.get("e", 0) / 1000.0
            if mtype in (MoveType.RETRACTION_BACK, MoveType.RETRACTION_MODEL_BACK) and e < 0:
                st["retractions"] += 1
                st["retract_mm"] += -e
            if e > 0 and mtype not in (MoveType.RETRACTION_FORWARD, MoveType.RETRACTION_MODEL_FORWARD) and d > 0:
                g = GROUP_OF.get(mtype, "Other extrusion")
                gs = st["groups"][g]
                gs["len"] += d
                gs["e"] += e
                gs["time"] += t
                gs["fw"] += feed / 60.0 * d
                if layer is not None:
                    st["layers"].setdefault(layer, defaultdict(float))[g] += d
                    st["layer_z"].setdefault(layer, nz)
                    st["segments"][layer].append((g, x, y, nx, ny))
            elif d > 0:
                st["travel_mm"] += d
                st["travel_time"] += t
                if mtype == MoveType.JUMP or op == Op.PRINT_JUMP:
                    st["jumps"] += 1
                    if nz != z and nx == x and ny == y:
                        st["z_hops"] += 1
            x, y, z = nx, ny, nz
    return st


def model_layers(st):
    return sorted(l for l, gs in st["layers"].items() if any(g != "Raft" for g in gs))


def raft_layers(st):
    return sorted(l for l, gs in st["layers"].items() if set(gs) == {"Raft"})


def summary(st):
    h = st["header"]
    ml, rl = model_layers(st), raft_layers(st)
    zs = [st["layer_z"][l] for l in ml]
    first_model_z = zs[0] / 1000 if zs else 0
    raft_top = st["layer_z"][rl[-1]] / 1000 if rl else 0
    out = {
        "Print time (slicer estimate)": f"{h['PrintTime'] // 3600}h {h['PrintTime'] % 3600 // 60}m",
        "Filament (header)": f"{h['Materials'][0]['Usage'] / 1000:.2f} m / {h['Materials'][0]['UsageGrams']} g",
        "Nozzle / bed temperature": f"{h['Materials'][0]['Temperature']} / {h['HeatbedTemperature']} °C",
        "Commands": st["commands"],
        "Raft layers": len(rl),
        "Raft top Z / first model layer Z": f"{raft_top:.2f} / {first_model_z:.2f} mm",
        "Model layers": len(ml),
        "Model top Z": f"{zs[-1] / 1000:.2f} mm" if zs else "-",
        "Bounding box XY": f"{(h['PrintBoundingBox']['MaxX'] - h['PrintBoundingBox']['MinX']) / 1000:.1f} x "
                           f"{(h['PrintBoundingBox']['MaxY'] - h['PrintBoundingBox']['MinY']) / 1000:.1f} mm",
        "Retractions": f"{st['retractions']} ({st['retract_mm'] / max(st['retractions'], 1):.2f} mm each)",
        "Travel": f"{st['travel_mm'] / 1000:.1f} m",
        "Z hops": st["z_hops"],
        "Simulated time (no accel.)": f"{(sum(g['time'] for g in st['groups'].values()) + st['travel_time']) / 60:.0f} min",
    }
    return out


def group_table(st):
    rows = {}
    for g in GROUPS:
        gs = st["groups"].get(g)
        if not gs or not gs["len"]:
            continue
        rows[g] = {"length_m": gs["len"] / 1000, "filament_m": gs["e"] / 1000,
                   "speed_mm_s": gs["fw"] / gs["len"], "time_min": gs["time"] / 60,
                   "e_per_mm": gs["e"] / gs["len"]}
    return rows


def render_layer(st, layer, size=520, bbox=None):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), "white")
    dr = ImageDraw.Draw(img)
    minx, miny, maxx, maxy = bbox
    span = max(maxx - minx, maxy - miny) or 1
    pad = 20
    k = (size - 2 * pad) / span

    def p(px, py):
        return pad + (px - minx) * k, size - pad - (py - miny) * k
    for g, x0, y0, x1, y1 in st["segments"].get(layer, []):
        dr.line([p(x0, y0), p(x1, y1)], fill=COLOURS[g], width=2)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"), ap.add_argument("b")
    ap.add_argument("--labels", nargs=2, default=["A", "B"])
    ap.add_argument("--png-dir")
    ap.add_argument("--json")
    args = ap.parse_args()
    sa, sb = simulate(args.a), simulate(args.b)
    la, lb = args.labels
    res = {"summary": {la: summary(sa), lb: summary(sb)}, "features": {la: group_table(sa), lb: group_table(sb)}}
    w = max(len(k) for k in res["summary"][la])
    print(f"{'':{w}}  {la:>24}  {lb:>24}")
    for k in res["summary"][la]:
        print(f"{k:{w}}  {str(res['summary'][la][k]):>24}  {str(res['summary'][lb][k]):>24}")
    print()
    print(f"{'Feature':18} {'':>6} {'path m':>7} {'fil. m':>7} {'mm/s':>6} {'min':>6} {'E/mm':>6}")
    for g in GROUPS:
        for lab in (la, lb):
            r = res["features"][lab].get(g)
            if r:
                print(f"{g:18} {lab:>6} {r['length_m']:7.2f} {r['filament_m']:7.3f} {r['speed_mm_s']:6.1f} "
                      f"{r['time_min']:6.1f} {r['e_per_mm']:6.3f}")
    if args.json:
        json.dump(res, open(args.json, "w"), indent=1, default=str)
    if args.png_dir:
        render_all(sa, sb, la, lb, args.png_dir)


def render_all(sa, sb, la, lb, out):
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(out, exist_ok=True)
    allx, ally = [], []
    for st in (sa, sb):
        for segs in st["segments"].values():
            for _, x0, y0, x1, y1 in segs:
                allx += [x0, x1]
                ally += [y0, y1]
    bbox = (min(allx), min(ally), max(allx), max(ally))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
        small = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        font = small = ImageFont.load_default()

    def pick(st):
        rl, ml = raft_layers(st), model_layers(st)
        return [("Raft base", rl[0] if rl else None), ("Raft top", rl[-1] if rl else None),
                ("First model layer", ml[0]), ("Mid-height", ml[len(ml) // 2]), ("Top layer", ml[-1])]
    rows = list(zip(pick(sa), pick(sb)))
    cell = 360
    W, H = 2 * cell + 200, len(rows) * (cell + 10) + 90
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    d.text((200 + cell // 2, 20), la, fill="black", font=font, anchor="mm")
    d.text((200 + cell + cell // 2, 20), lb, fill="black", font=font, anchor="mm")
    for i, ((name, l1), (_, l2)) in enumerate(rows):
        top = 40 + i * (cell + 10)
        d.text((10, top + cell // 2), name, fill="black", font=font, anchor="lm")
        for j, (st, l) in enumerate(((sa, l1), (sb, l2))):
            x0 = 200 + j * cell
            if l is None:
                d.text((x0 + cell // 2, top + cell // 2), "(none)", fill="grey", font=font, anchor="mm")
                continue
            sheet.paste(render_layer(st, l, cell, bbox), (x0, top))
            d.rectangle([x0, top, x0 + cell - 1, top + cell - 1], outline=(200, 200, 200))
            d.text((x0 + 8, top + 6), f"layer {l}, Z {st['layer_z'][l] / 1000:.2f} mm", fill="black", font=small)
    lx = 200
    for g, c in COLOURS.items():
        if g == "Other extrusion":
            continue
        d.rectangle([lx, H - 35, lx + 14, H - 21], fill=c)
        d.text((lx + 20, H - 28), g, fill="black", font=small, anchor="lm")
        lx += 30 + int(d.textlength(g, font=small))
    sheet.save(os.path.join(out, "cube-layers-cura-vs-zsuite.png"))


if __name__ == "__main__":
    main()
