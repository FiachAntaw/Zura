"""Generate Cura material and quality profiles from extracted Z-Suite configurations.

Input:  plugins/ZortraxM/zsuite_profiles/*.json (Z-Suite 3.7.0 Configuration + UI settings)
Output: plugins/ZortraxM/resources/materials/*.xml.fdm_material
        plugins/ZortraxM/resources/quality/zortrax_m200_plus/*.inst.cfg

Run: python3 tools/gen_presets.py
"""
import json
import os
import uuid
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PLUGIN = os.path.join(ROOT, "plugins", "ZortraxM")
PROFILES = os.path.join(PLUGIN, "zsuite_profiles")
RES = os.path.join(PLUGIN, "resources")
MACHINE = "zortrax_m200_plus"
# The M300 Plus uses the same Z-Suite profiles (only the unused waste-tower position differs), so it shares
# the M200 Plus quality profiles via quality_definition and is listed in every material file.
MATERIAL_MACHINES = ("zortrax_m200_plus", "zortrax_m300_plus", "zortrax_m200")
SETTING_VERSION = 27  # Cura 5.14
NS = uuid.UUID("6f1b9a4e-2a1d-4c3e-9b0e-5a7d3c2e1f00")

# material name -> (cura material type, density g/cm3, colour)
MATERIALS = {
    "Z-ABS": ("ABS", 1.04, "#f2f2f2"), "Z-ABS 2": ("ABS", 1.04, "#f2f2f2"),
    "Z-ULTRAT": ("ABS", 1.04, "#e8e8e8"), "Z-GLASS": ("PETG", 1.27, "#cfe8f0"),
    "Z-HIPS": ("HIPS", 1.04, "#f5f5dc"), "Z-PCABS": ("PC/ABS", 1.15, "#404040"),
    "Z-PETG": ("PETG", 1.27, "#d0d0d0"), "Z-ESD": ("ABS", 1.05, "#202020"),
    "Z-PLA": ("PLA", 1.24, "#ffffff"), "Z-PLA Pro": ("PLA", 1.24, "#ffffff"),
    "Z-ASA Pro": ("ASA", 1.07, "#e0e0e0"), "Z-FLEX": ("TPU", 1.2, "#303030"),
    "Z-SEMIFLEX": ("TPU", 1.2, "#303030"), "Z-NYLON": ("Nylon", 1.14, "#f0f0e0"),
    "BASF Ultrafuse ABS": ("ABS", 1.05, "#f2f2f2"), "Nanovia PC-ABS V0": ("PC/ABS", 1.15, "#202020"),
}

FILAMENT_AREA = 3.14159265 * 0.875 ** 2  # 1.75 mm filament, mm2
QUALITY_NAMES = {"10": "0.10 mm", "15": "0.15 mm", "20": "0.20 mm", "30": "0.30 mm"}


def material_id(name: str) -> str:
    return "zortrax_" + name.lower().replace(" ", "_").replace("-", "_")


QUALITY_SUFFIX = {"High": "", "Normal": "_normal", "Draft": "_draft"}
QUALITY_RANK = {"High": 0, "Normal": 1, "Draft": 2}


def quality_type(layer_id: str, quality: str) -> str:
    return f"z{layer_id}" + QUALITY_SUFFIX[quality]


def mms(v):  # Z-Suite speeds are mm/min
    return round(v / 60.0, 1)


def cura_values(cfg: dict, ui: dict, layer_mm: float) -> dict:
    """Map a Z-Suite Configuration onto Cura settings (only what CuraEngine can express)."""
    v = {
        "layer_height": layer_mm,
        "material_print_temperature": cfg["TempExtruder"],
        "material_print_temperature_layer_0": cfg["TempExtruder"],
        "material_initial_print_temperature": cfg["TempExtruder"],
        "material_final_print_temperature": cfg["TempExtruder"],
        "material_bed_temperature": cfg["TempBed"],
        "material_bed_temperature_layer_0": cfg["TempBed"],
        # walls
        "wall_line_count": cfg["SL_ContourQuantity"],
        "speed_wall_0": mms(cfg["SL_ContourSpeed"]),
        "speed_wall_x": mms(cfg["SL_InnerContourSpeed"]),
        "inset_direction": "outside_in" if cfg.get("SL_PrintContoursFromOutside", False) else "inside_out",
        # infill / skin
        "speed_infill": mms(cfg["IV_InfillSpeed"]),
        "speed_topbottom": mms(cfg["VT_InfillSpeed"]),
        "speed_roofing": mms(cfg["VT_InfillSpeed"]),
        "top_layers": cfg["VT_Quantity"],
        "bottom_layers": cfg["VB_Quantity"],
        "infill_sparse_density": 20,
        "infill_pattern": "grid",
        # travel / retraction
        "speed_travel": mms(cfg["R_IdleMoveSpeed"]),
        "retraction_amount": round(float(ui.get("RetractionDistance", 0.8)), 2),
        "retraction_speed": mms(cfg["R_BackSpeed"]),
        "retraction_prime_speed": mms(cfg["R_ForwardSpeed"]),
        "retract_at_layer_change": bool(cfg.get("R_ForceRetractionOnLayerChange", True)),
        # first layer (no raft)
        # FLNR_* is Z-Suite's "first layer without raft"; materials that need a raft
        # (Z-SEMIFLEX) leave it at 0, so fall back to the first-layer-on-raft speeds.
        "speed_layer_0": mms(cfg["FLNR_ContourSpeed"] or cfg["FL_ContourSpeed"]),
        "speed_print_layer_0": mms(cfg["FLNR_InfillSpeed"] or cfg["FL_InfillSpeed"]),
        # cooling: Z-Suite autofan ramps from AutofanMaxTimeSpeed (slow layers) to
        # AutofanMinTimeSpeed (fast layers) between AutofanMaxTime and AutofanMinTime seconds.
        "cool_fan_enabled": True,
        "cool_fan_speed_min": cfg.get("AutofanMaxTimeSpeed") or 20,
        "cool_fan_speed_max": cfg.get("AutofanMinTimeSpeed") or 100,
        "cool_min_layer_time_fan_speed_max": cfg.get("AutofanMaxTime", 20.0),
        "cool_min_layer_time": cfg.get("AutofanMinTime", 10.0),
        "cool_fan_speed_0": cfg.get("Raft_FanSpeed") or 0,
        # raft (Z-Suite default adhesion)
        "adhesion_type": "raft" if ui.get("RaftEnabled", True) else "none",
        # Z-Suite prints the first model layer FL_ModelSpace above the raft top (+ one layer) and the
        # second layer FL_SecondLayerLower lower than nominal; Cura's raft_airgap/layer_0_z_overlap are the same.
        # (RaftPlatformGap is the base layer's height above the platform, i.e. RB_Height, not this gap.)
        "raft_airgap": round(float(cfg.get("FL_ModelSpace", 0.16)), 3),
        "layer_0_z_overlap": round(float(cfg.get("FL_SecondLayerLower", 0.05)), 4),
        "raft_interface_thickness": cfg.get("RB_RaftDefaultHeight", 0.2),
        "raft_surface_thickness": cfg.get("RB_RaftDefaultHeight", 0.2),
        "raft_base_speed": mms(cfg["RB_Speed"]),
        "raft_interface_speed": mms(cfg["RG_Speed"]),
        "raft_surface_speed": mms(cfg["RS_Speed"]),
        "raft_interface_layers": cfg["RG_Quantity"] + cfg["R2_Quantity"],
        "raft_surface_layers": cfg["RS_Quantity"],
        "raft_surface_line_spacing": cfg["RS_Increment"],
        "raft_interface_line_spacing": cfg["RG_Increment"],
        "raft_base_line_spacing": cfg["RB_Increment"],
        "raft_base_thickness": cfg["RB_Height"],
        "raft_margin": cfg.get("RB_RG_Enlarge", 3),
        "raft_surface_margin": cfg.get("RS_Enlarge", 5.0),
        # support
        "support_angle": round(90 - float(cfg.get("SB_DefaultAngle", 30)), 1),
        "support_xy_distance": round(float(ui.get("XyGap", 0.16)), 2),
        "support_z_distance": round(int(ui.get("ZGap", 1)) * layer_mm, 3),
        "support_line_distance": cfg["SB_InfillIncrement"],
        "speed_support": mms(cfg["SB_Speed"]),
        "support_interface_enable": True,
        "support_interface_height": round(cfg.get("SB_VerticalSpaceTop", 1) * layer_mm * 3, 3),
        "speed_support_interface": mms(cfg["SS_InfillSpeed"]),
        # bridges
        "bridge_settings_enabled": bool(ui.get("Bridges", True)),
        # seam
        "z_seam_type": "random" if ui.get("RandomSeam") else "sharpest_corner",
    }
    # Z-Suite *_Feed values are mm of filament per mm of path. Cura extrudes line_width x layer_height
    # per mm, so express walls as flow % and infill as a wider line (Z-Suite prints thick, sparse infill).
    nominal = 0.4 * layer_mm / FILAMENT_AREA
    v["wall_0_material_flow"] = round(100 * cfg["SL_ContourFeed"] / nominal)
    v["wall_x_material_flow"] = round(100 * cfg["SL_InnerContourFeed"] / nominal)
    v["infill_line_width"] = round(0.4 * cfg["IV_InfillFeed"] / nominal, 2)
    # Z hop on travel (Z-Suite lifts on every travel longer than R_MinLength).
    v["retraction_hop_enabled"] = bool(cfg.get("R_LiftZEnable", True))
    v["retraction_hop"] = cfg.get("R_LiftZHeight", 0.2)
    v["retraction_min_travel"] = cfg.get("R_MinLength", 2.0)
    # Comb only through infill and retract (and lift) elsewhere: closest to Z-Suite's retraction count
    # on the test cube (combing "all" retracts ~1/layer, "off" ~3x as often as Z-Suite).
    v["retraction_combing"] = "infill"
    if cfg.get("ShrinkageCompensation"):
        v["material_shrinkage_percentage_xy"] = round(100 + float(cfg["ShrinkageCompensation"]), 3)
    return v


# Settings Cura derives natively from another setting; dropped when the derivation gives the same value.
DERIVED = {
    "material_print_temperature_layer_0": "material_print_temperature",
    "material_bed_temperature_layer_0": "material_bed_temperature",
    "speed_roofing": "speed_topbottom",
    "retraction_prime_speed": "retraction_speed",
}
# Machine-definition formulas, applied when the relation holds for every profile.
DEF_FORMULAS = {
    "material_initial_print_temperature": "material_print_temperature",
    "material_final_print_temperature": "material_print_temperature",
}
# Material-file keys Cura's fdm_material format names itself (everything else goes in <cura:setting>).
XML_KEYS = {
    "default_material_print_temperature": "print temperature",
    "default_material_bed_temperature": "heated bed temperature",
    "retraction_amount": "retraction amount",
    "retraction_speed": "retraction speed",
}
DEFINITION = os.path.join(RES, "definitions", f"{MACHINE}.def.json")


def _fmt(v) -> str:
    return ("True" if v else "False") if isinstance(v, bool) else str(v)


def material_xml(name: str, settings: dict) -> str:
    mtype, density, colour = MATERIALS.get(name, ("ABS", 1.04, "#ffffff"))
    guid = uuid.uuid5(NS, name)
    lines = []
    for k, v in sorted(settings.items(), key=lambda kv: (kv[0] not in XML_KEYS, kv[0])):
        if k in XML_KEYS:
            lines.append(f'        <setting key="{XML_KEYS[k]}">{v}</setting>')
        else:
            text = ("yes" if v else "no") if isinstance(v, bool) else v
            lines.append(f'        <cura:setting key="{k}">{text}</cura:setting>')
    body = "\n".join(lines)
    MACHINE_IDS = "\n".join(f'            <machine_identifier manufacturer="Zortrax" product="{m}" />' for m in MATERIAL_MACHINES)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Generated by tools/gen_presets.py from Z-Suite 3.7.0 defaults for the Zortrax M200 Plus and M300 Plus.
     Holds the settings that depend only on the filament; layer-height-specific values are in the quality profiles. -->
<fdmmaterial xmlns="http://www.ultimaker.com/material" xmlns:cura="http://www.ultimaker.com/cura" version="1.3">
    <metadata>
        <name>
            <brand>Zortrax</brand>
            <material>{mtype}</material>
            <color>{name}</color>
            <label>{name}</label>
        </name>
        <GUID>{guid}</GUID>
        <version>1</version>
        <color_code>{colour}</color_code>
        <description>{name} by Zortrax. Settings ported from Z-Suite.</description>
    </metadata>
    <properties>
        <density>{density}</density>
        <diameter>1.75</diameter>
    </properties>
    <settings>
{body}
        <machine>
{MACHINE_IDS}
            <setting key="hardware compatible">yes</setting>
        </machine>
    </settings>
</fdmmaterial>
"""


def inst_cfg(name: str, qtype: str, weight: int, values: dict, material: str = None) -> str:
    meta = [f"quality_type = {qtype}", f"setting_version = {SETTING_VERSION}", "type = quality", f"weight = {weight}"]
    if material:
        meta.insert(0, f"material = {material}")
    else:
        meta.insert(0, "global_quality = True")
    body = "\n".join(f"{k} = {_fmt(v)}" for k, v in sorted(values.items()))
    return f"[general]\ndefinition = {MACHINE}\nname = {name}\nversion = 4\n\n[metadata]\n" + "\n".join(meta) + f"\n\n[values]\n{body}\n"


def _mode(values):
    return Counter(map(repr, values)).most_common(1)[0][0]


def plan(table: dict):
    """Split {(material, quality_type): {setting: value}} into Cura's container levels.

    Each setting goes to one home: the machine definition (same everywhere), the material file
    (depends only on the filament), the global quality profile (depends only on layer height /
    quality) or, if it depends on both, whichever of material/global leaves fewer exceptions.
    Remaining exceptions go in the material-specific quality profile, which outranks both.
    """
    keys = sorted({k for vals in table.values() for k in vals})
    combos = sorted(table)
    definition, materials, globals_, exceptions = {}, defaultdict(dict), defaultdict(dict), defaultdict(dict)
    homes = {}
    for k in keys:
        col = {c: table[c][k] for c in combos}
        by_m, by_q = defaultdict(list), defaultdict(list)
        for (m, q), v in col.items():
            by_m[m].append(v)
            by_q[q].append(v)
        if len({repr(v) for v in col.values()}) == 1:
            homes[k] = "definition"
            definition[k] = next(iter(col.values()))
            continue
        base_m = {m: _mode(vs) for m, vs in by_m.items()}
        base_q = {q: _mode(vs) for q, vs in by_q.items()}
        exc_m = sum(repr(v) != base_m[m] for (m, q), v in col.items())
        exc_q = sum(repr(v) != base_q[q] for (m, q), v in col.items())
        home = "material" if exc_m <= exc_q else "quality"
        homes[k] = home if (exc_m if home == "material" else exc_q) == 0 else home + "+exceptions"
        for (m, q), v in col.items():
            base = base_m[m] if home == "material" else base_q[q]
            if repr(v) != base:
                exceptions[(m, q)][k] = v
            elif home == "material":
                materials[m][k] = v
            else:
                globals_[q][k] = v
    return homes, definition, materials, globals_, exceptions


def write_definition(const: dict) -> None:
    with open(DEFINITION) as f:
        d = json.load(f)
    o = d["overrides"]
    generated = set(d.get("metadata", {}).get("zura_generated_overrides", []))
    for k in generated:
        o.pop(k, None)
    for k, v in sorted(const.items()):
        o[k] = {"value": f"'{v}'" if isinstance(v, str) else v}
    for k, expr in DEF_FORMULAS.items():
        o[k] = {"value": expr}
    d["metadata"]["zura_generated_overrides"] = sorted(set(const) | set(DEF_FORMULAS))
    with open(DEFINITION, "w") as f:
        json.dump(d, f, indent=4)
        f.write("\n")


def main():
    with open(os.path.join(PROFILES, "index.json")) as f:
        index = json.load(f)
    mat_dir = os.path.join(RES, "materials")
    q_dir = os.path.join(RES, "quality", MACHINE)
    os.makedirs(mat_dir, exist_ok=True)
    os.makedirs(q_dir, exist_ok=True)
    for old in os.listdir(q_dir):
        if old.endswith(".inst.cfg"):
            os.remove(os.path.join(q_dir, old))
    table, qtypes, names = {}, {}, {}
    for p in index["profiles"]:
        with open(os.path.join(PROFILES, p["file"])) as f:
            prof = json.load(f)
        name, layer_id, quality = p["material"], p["layer_id"], p["quality"]
        layer_mm = prof["configuration"]["SliceThickness"]  # Z-SEMIFLEX labels 0.14 but slices at 0.15
        qt = quality_type(layer_id, quality)
        label = quality  # Cura appends the layer height, e.g. "High - 0.2mm"
        qtypes[qt] = (label, -int(layer_id) * 10 - QUALITY_RANK[quality])
        names[material_id(name)] = name
        table[(material_id(name), qt)] = cura_values(prof["configuration"], prof["settings"], layer_mm)
    for vals in table.values():
        for k, src in DERIVED.items():
            if k in vals and vals[k] == vals.get(src):
                del vals[k]
        for k, src in DEF_FORMULAS.items():
            if vals.get(k) == vals.get(src):
                vals.pop(k, None)
        vals["default_material_print_temperature"] = vals.pop("material_print_temperature")
        vals["default_material_bed_temperature"] = vals.pop("material_bed_temperature")
    homes, definition, materials, globals_, exceptions = plan(table)
    write_definition(definition)
    for mid, name in names.items():
        with open(os.path.join(mat_dir, f"{mid}.xml.fdm_material"), "w") as f:
            f.write(material_xml(name, materials[mid]))
    for qt, (label, weight) in qtypes.items():
        with open(os.path.join(q_dir, f"{MACHINE}_global_{qt}.inst.cfg"), "w") as f:
            f.write(inst_cfg(label, qt, weight, globals_[qt]))
    for (mid, qt) in table:
        label, weight = qtypes[qt]
        with open(os.path.join(q_dir, f"{MACHINE}_{mid}_{qt}.inst.cfg"), "w") as f:
            f.write(inst_cfg(label, qt, weight, exceptions.get((mid, qt), {}), material=mid))
    by_home = defaultdict(list)
    for k, h in homes.items():
        by_home[h].append(k)
    for h in ("definition", "material", "quality", "material+exceptions", "quality+exceptions"):
        print(f"{h}: {', '.join(sorted(by_home[h]))}")
    print(f"exceptions in material-specific profiles: {sum(len(v) for v in exceptions.values())} values")


if __name__ == "__main__":
    main()
