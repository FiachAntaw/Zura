"""Generate Cura material and quality profiles from extracted Z-Suite configurations.

Input:  plugins/ZortraxM/zsuite_profiles/*.json (Z-Suite 3.7.0 Configuration + UI settings)
Output: plugins/ZortraxM/resources/materials/*.xml.fdm_material
        plugins/ZortraxM/resources/quality/zortrax_m200_plus/*.inst.cfg

Run: python3 tools/gen_presets.py
"""
import json
import os
import uuid
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PLUGIN = os.path.join(ROOT, "plugins", "ZortraxM")
PROFILES = os.path.join(PLUGIN, "zsuite_profiles")
RES = os.path.join(PLUGIN, "resources")
MACHINE = "zortrax_m200_plus"
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

QUALITY_NAMES = {"10": "0.10 mm", "15": "0.15 mm", "20": "0.20 mm", "30": "0.30 mm"}


def material_id(name: str) -> str:
    return "zortrax_" + name.lower().replace(" ", "_").replace("-", "_")


def quality_type(layer_id: str, quality: str) -> str:
    return f"z{layer_id}" + ("" if quality == "High" else "_draft")


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
        "outer_inset_first": bool(cfg.get("SL_PrintContoursFromOutside", False)),
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
        "speed_layer_0": mms(cfg["FLNR_ContourSpeed"]),
        "speed_print_layer_0": mms(cfg["FLNR_InfillSpeed"]),
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
    if cfg.get("ShrinkageCompensation"):
        v["material_shrinkage_percentage_xy"] = round(100 + float(cfg["ShrinkageCompensation"]), 3)
    return v


def material_xml(name: str, cfg: dict, ui: dict) -> str:
    mtype, density, colour = MATERIALS.get(name, ("ABS", 1.04, "#ffffff"))
    guid = uuid.uuid5(NS, name)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Generated from Z-Suite 3.7.0 defaults for the Zortrax M200 Plus. -->
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
        <setting key="print temperature">{cfg['TempExtruder']}</setting>
        <setting key="heated bed temperature">{cfg['TempBed']}</setting>
        <setting key="retraction amount">{round(float(ui.get('RetractionDistance', 0.8)), 2)}</setting>
        <setting key="retraction speed">{mms(cfg['R_BackSpeed'])}</setting>
        <machine>
            <machine_identifier manufacturer="Zortrax" product="{MACHINE}" />
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
    body = "\n".join(f"{k} = {str(v) if not isinstance(v, bool) else ('True' if v else 'False')}" for k, v in sorted(values.items()))
    return f"[general]\ndefinition = {MACHINE}\nname = {name}\nversion = 4\n\n[metadata]\n" + "\n".join(meta) + f"\n\n[values]\n{body}\n"


def main():
    with open(os.path.join(PROFILES, "index.json")) as f:
        index = json.load(f)
    mat_dir = os.path.join(RES, "materials")
    q_dir = os.path.join(RES, "quality", MACHINE)
    os.makedirs(mat_dir, exist_ok=True)
    os.makedirs(q_dir, exist_ok=True)
    seen_materials, qtypes = set(), {}
    report = defaultdict(list)
    for p in index["profiles"]:
        with open(os.path.join(PROFILES, p["file"])) as f:
            prof = json.load(f)
        cfg, ui = prof["configuration"], prof["settings"]
        name, layer_id, quality = p["material"], p["layer_id"], p["quality"]
        layer_mm = int(layer_id) / 100.0
        mid = material_id(name)
        if name not in seen_materials:
            seen_materials.add(name)
            with open(os.path.join(mat_dir, f"{mid}.xml.fdm_material"), "w") as f:
                f.write(material_xml(name, cfg, ui))
        qt = quality_type(layer_id, quality)
        label = QUALITY_NAMES[layer_id] + ("" if quality == "High" else " Draft")
        weight = -int(layer_id) - (0 if quality == "High" else 1)
        qtypes[qt] = (label, weight, layer_mm)
        with open(os.path.join(q_dir, f"{MACHINE}_{mid}_{qt}.inst.cfg"), "w") as f:
            f.write(inst_cfg(label, qt, weight, cura_values(cfg, ui, layer_mm), material=mid))
        report[name].append(label)
    for qt, (label, weight, layer_mm) in qtypes.items():
        with open(os.path.join(q_dir, f"{MACHINE}_global_{qt}.inst.cfg"), "w") as f:
            f.write(inst_cfg(label, qt, weight, {"layer_height": layer_mm, "adhesion_type": "raft"}))
    for name, labels in sorted(report.items()):
        print(f"{name}: {', '.join(labels)}")


if __name__ == "__main__":
    main()
