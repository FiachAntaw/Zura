"""Generate the original Zortrax M200 and M300 machines, their quality profiles and bundled Z-Suite configs.

Input:  Z-Suite 2.32 "classic" configurations dumped with tools/dotnet (ZC_PRINTER=M200|M300 zcref configs <dir>),
        default /tmp/claude-0/m200cfg and /tmp/claude-0/m300cfg (index.json + one JSON per combination).
        Once copied, plugins/ZortraxM/zsuite_profiles_<m200|m300>/ is the source and the dump is optional.
Output, per machine (zortrax_m200, zortrax_m300):
        plugins/ZortraxM/zsuite_profiles_<model>/*.json (0.4 mm nozzle, Standard infill, Zortrax materials)
        plugins/ZortraxM/resources/definitions/<machine>.def.json
        plugins/ZortraxM/resources/extruders/<machine>_extruder_0.def.json
        plugins/ZortraxM/resources/quality/<machine>/*.inst.cfg

Run: python3 tools/gen_classic_presets.py [m200|m300 dump_dir]
Material files are shared with the Plus printers: run tools/gen_presets.py first (it lists these machines in them).
"""
import copy
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_presets as G  # noqa: E402

# Zortrax filaments Z-Suite 2.32 offers for each printer (ids 129+ are its generic "-based filament" profiles).
CLASSIC = {
    "m200": {"machine": "zortrax_m200", "name": "Zortrax M200", "short": "M200", "hardware": 1, "size": 200,
             "height": 180, "platform": "zortrax_m200_plus_platform.stl", "preferred_material": "zortrax_z_abs",
             "materials": ("Z-ABS", "Z-ABS 2", "Z-ULTRAT", "Z-GLASS", "Z-HIPS", "Z-PCABS", "Z-PETG", "Z-ESD",
                           "Z-PLA Pro", "Z-ASA Pro")},
    "m300": {"machine": "zortrax_m300", "name": "Zortrax M300", "short": "M300", "hardware": 20, "size": 300,
             "height": 300, "platform": "zortrax_m300_plus_platform.stl", "preferred_material": "zortrax_z_ultrat",
             "materials": ("Z-ULTRAT", "Z-GLASS", "Z-HIPS", "Z-PETG", "Z-ESD", "Z-PLA Pro", "Z-ASA Pro")},
}
QUALITY_FIX = {("Z-ULTRAT", "29"): "Normal"}  # Z-Suite labels it Normal (quality id 1, the only one at 0.29)

MODEL = MACHINE = PROFILES = Q_DIR = DEFINITION = EXTRUDER = MATERIALS = SPEC = None


def select(model: str) -> None:
    """Point the module-level paths at one classic printer."""
    global MODEL, MACHINE, PROFILES, Q_DIR, DEFINITION, EXTRUDER, MATERIALS, SPEC
    SPEC = CLASSIC[model]
    MODEL, MACHINE, MATERIALS = model, SPEC["machine"], SPEC["materials"]
    PROFILES = os.path.join(G.PLUGIN, f"zsuite_profiles_{model}")
    Q_DIR = os.path.join(G.RES, "quality", MACHINE)
    DEFINITION = os.path.join(G.RES, "definitions", f"{MACHINE}.def.json")
    EXTRUDER = os.path.join(G.RES, "extruders", f"{MACHINE}_extruder_0.def.json")


select("m200")


def import_dump(dump: str) -> None:
    with open(os.path.join(dump, "index.json")) as f:
        index = json.load(f)
    if os.path.isdir(PROFILES):
        shutil.rmtree(PROFILES)
    os.makedirs(PROFILES)
    out = []
    for p in index:
        if p["nozzle_id"] != "0" or p["infill"] != "Standard" or p["material"] not in MATERIALS:
            continue
        quality = QUALITY_FIX.get((p["material"], p["layer_id"]), p["quality"])
        name = f"{p['material'].replace(' ', '_')}_{p['layer_id']}_{quality}.json"
        with open(os.path.join(dump, p["file"])) as f:
            cfg = json.load(f)
        with open(os.path.join(PROFILES, name), "w") as f:
            json.dump(cfg, f, separators=(",", ":"))
        out.append({"file": name, "material": p["material"], "material_id": int(p["material_id"]),
                    "layer_id": p["layer_id"], "quality": quality, "quality_id": int(p["quality_id"]),
                    "infill_id": int(p["infill_id"]), "nozzle_id": int(p["nozzle_id"])})
    out.sort(key=lambda p: (p["material"], int(p["layer_id"]), G.QUALITY_RANK[p["quality"]]))
    with open(os.path.join(PROFILES, "index.json"), "w") as f:
        json.dump({"source": f"Z-Suite 2.32.0 ({SPEC['name']}, 0.4 mm nozzle, Standard infill)", "profiles": out}, f, indent=1)
    print(f"imported {len(out)} configurations")


def classic_values(cfg: dict) -> dict:
    """Map a Z-Suite 2.32 (classic) M200 Configuration onto Cura settings."""
    layer_mm = cfg["SliceThickness"]
    v = {
        "layer_height": layer_mm,
        "material_print_temperature": cfg["TempExtruder"],
        "material_bed_temperature": cfg["TempBed"],
        # Classic Z-Suite prints the outer contour (SL_) and one inner contour (IV_Contour*), outer first.
        "wall_line_count": 2,
        "speed_wall_0": G.mms(cfg["SL_ContourSpeed"]),
        "speed_wall_x": G.mms(cfg["IV_ContourSpeed"]),
        "inset_direction": "inside_out" if cfg.get("IsSecondContourFirst") else "outside_in",
        "speed_infill": G.mms(cfg["IV_InfillSpeed"]),
        "speed_topbottom": G.mms(cfg["VT_InfillSpeed"]),
        "speed_roofing": G.mms(cfg["VT_InfillSpeed"]),
        "top_layers": cfg["VT_Quantity"],
        "bottom_layers": cfg["VB_Quantity"],
        "infill_sparse_density": 20,
        "infill_pattern": "grid",
        "speed_travel": G.mms(cfg["IdleMoveSpeed"]),
        "retraction_amount": round(float(cfg["R_Back"]), 2),
        "retraction_speed": G.mms(cfg["R_BackSpeed"]),
        "retraction_prime_speed": G.mms(cfg["R_ForwardSpeed"]),
        "retract_at_layer_change": bool(cfg.get("R_ForceOnZChange", True)),
        "retraction_hop_enabled": bool(cfg.get("R_LiftZEnable", True)),
        "retraction_hop": cfg.get("R_LiftZHeight", 0.2),
        "retraction_min_travel": cfg.get("R_MinLenght", 2.0),
        "retraction_combing": "infill",
        # The classic M200 always prints on a raft, so the first model layer uses the FL_ speeds.
        "speed_layer_0": G.mms(cfg["FL_ContourSpeed"]),
        "speed_print_layer_0": G.mms(cfg["FL_InfillSpeed"]),
        "adhesion_type": "raft" if cfg.get("EnableRaft", True) else "none",
        "raft_airgap": round(float(cfg["FL_ModelSpace"]), 3),
        "layer_0_z_overlap": round(float(cfg["FL_SecondLayerLower"]), 4),
        "raft_interface_thickness": cfg["RB_RaftDefaultHeight"],
        "raft_surface_thickness": cfg["RB_RaftDefaultHeight"],
        "raft_base_thickness": cfg["RB_Height"],
        # Z-Suite lays the base layer very heavy (RB_Feed, filament mm per mm) so it squashes into the
        # perforated plate; Cura's default 0.8 mm base line at RB_Height carries far less.
        "raft_base_flow": round(100 * cfg["RB_Feed"] / (0.8 * cfg["RB_Height"] / G.FILAMENT_AREA)),
        "raft_base_speed": G.mms(cfg["RB_Speed"]),
        "raft_interface_speed": G.mms(cfg["RG_Speed"]),
        "raft_surface_speed": G.mms(cfg["RS_Speed"]),
        "raft_interface_layers": cfg["RG_Quantity"] + cfg["R2_Quantity"],
        "raft_surface_layers": cfg["RS_Quantity"],
        "raft_surface_line_spacing": cfg["RS_Increment"],
        "raft_interface_line_spacing": cfg["RG_Increment"],
        "raft_base_line_spacing": cfg["RB_Increment"],
        "raft_margin": cfg.get("RS_ContourOffset", 5.0),
        "raft_surface_margin": cfg.get("RS_ContourOffset", 5.0),
        "support_angle": round(90 - float(cfg.get("SB_Angle", 20)), 1),
        "support_xy_distance": 0.16,
        "support_z_distance": round(int(cfg.get("SB_VerticalSpaceTop", 1)) * layer_mm, 3),
        "support_line_distance": cfg["SB_Increment"],
        "speed_support": G.mms(cfg["SB_Speed"]),
        "support_interface_enable": True,
        "support_interface_height": round(cfg.get("SB_VerticalSpaceTop", 1) * layer_mm * 3, 3),
        "speed_support_interface": G.mms(cfg["SS_Speed"]),
        "bridge_settings_enabled": bool(cfg.get("EnableBridge", True)),
        "z_seam_type": "sharpest_corner",
        "cool_min_layer_time": cfg.get("SL_LayerMinimalTime", 5),
    }
    # Fan: Z-Suite runs it at 20% (51/255) for the first layers and then either keeps it at
    # ADDITIONAL_FAN_SPEED (autofan off, 0 for every Zortrax M200 profile), a fixed speed, or a ramp
    # from 100% (layers faster than AutofanMinTime) down to 20% (slower than AutofanMaxTime).
    if cfg.get("AutofanEnable"):
        if cfg.get("AutofanFixedEnabled"):
            lo = hi = round(100 * float(cfg["AutofanFixedSpeed"]))
        else:
            lo, hi = 20, 100
        v["cool_min_layer_time_fan_speed_max"] = cfg.get("AutofanMaxTime", 60.0)
    else:
        lo = hi = round(100 * cfg.get("ADDITIONAL_FAN_SPEED", 0) / 255)
    v.update({"cool_fan_enabled": True, "cool_fan_speed_min": lo, "cool_fan_speed_max": hi,
              "cool_fan_speed_0": 20, "cool_fan_full_layer": 4,
              "raft_fan_speed": round(100 * cfg.get("RAFT_FAN_SPEED", 76) / 255)})
    nominal = 0.4 * layer_mm / G.FILAMENT_AREA
    v["wall_0_material_flow"] = round(100 * cfg["SL_ContourFeed"] / nominal)
    v["wall_x_material_flow"] = round(100 * cfg["IV_ContourFeed"] / nominal)
    v["infill_line_width"] = round(0.4 * cfg["IV_InfillFeed"] / nominal, 2)
    # Z-Suite prints the first model layer on the raft deliberately starved (FL_*Feed, with
    # FL_InfillIncrement line spacing) so it bonds only lightly and the raft peels off.
    # Cura would otherwise lay a full-flow first layer straight onto the raft.
    fl_fill = (cfg["FL_InfillFeed"] / cfg["FL_InfillIncrement"]) / (nominal / 0.4)
    v["material_flow_layer_0"] = round(100 * fl_fill)
    v["skin_material_flow_layer_0"] = round(100 * fl_fill)
    # Cura multiplies these by the walls' normal flow, so they are relative to SL_/IV_ContourFeed.
    v["wall_0_material_flow_layer_0"] = round(100 * cfg["FL_ContourFeed"] / cfg["SL_ContourFeed"])
    v["wall_x_material_flow_layer_0"] = round(100 * cfg["FL_ContourFeed"] / cfg["IV_ContourFeed"])
    return v


def material_file_keys() -> set:
    keys = set()
    mat_dir = os.path.join(G.RES, "materials")
    for name in os.listdir(mat_dir):
        with open(os.path.join(mat_dir, name)) as f:
            keys |= set(re.findall(r'<cura:setting key="(\w+)">', f.read()))
    return keys | set(G.XML_KEYS) | {"material_print_temperature", "material_bed_temperature"}


def write_definition(const: dict) -> None:
    with open(os.path.join(G.RES, "definitions", "zortrax_m200_plus.def.json")) as f:
        d = copy.deepcopy(json.load(f))
    o = d["overrides"]
    for k in d["metadata"].pop("zura_generated_overrides", []):
        o.pop(k, None)
    d["name"] = SPEC["name"]
    md = d["metadata"]
    md.update({
        "file_formats": "application/x-zortrax-zcode",
        "preferred_quality_type": "z19",
        "supported_actions": ["MachineSettingsAction"],  # no network on the original M200/M300: print from SD card
        "machine_extruder_trains": {"0": f"{MACHINE}_extruder_0"},
        "platform": SPEC["platform"],
        "preferred_material": SPEC["preferred_material"],
        "zortrax_printer_name": SPEC["short"],
        "zortrax_hardware_version": SPEC["hardware"],
        # Cura matches these as substrings of material container ids, so name the printer-specific containers
        # ("zortrax_z_pla" alone would also hide zortrax_z_pla_pro).
        "exclude_materials": sorted(f"{G.material_id(n)}_{MACHINE}" for n in G.MATERIALS if n not in MATERIALS),
    })
    for k in ("zortrax_printer_model_id", "zortrax_min_firmware"):
        md.pop(k, None)
    o["machine_name"] = {"default_value": SPEC["name"]}
    o["machine_width"] = {"default_value": SPEC["size"]}
    o["machine_depth"] = {"default_value": SPEC["size"]}
    o["machine_height"] = {"default_value": SPEC["height"]}
    o["machine_start_gcode"] = {"default_value": (
        "; The Zortrax start sequence (heating, homing) is added automatically when the print is saved as .zcode.\n"
        "; Only temperature (M104/M109/M140/M190) and fan (M106/M107) commands here are used.\n"
        "M140 S{material_bed_temperature_layer_0}\nM104 S{material_print_temperature_layer_0}\nM83\nG92 E0")}
    o["machine_end_gcode"] = {"default_value": (
        "; The Zortrax end sequence (lift, heater off, park) is added automatically.\nM107")}
    for k, v in sorted(const.items()):
        o[k] = {"value": f"'{v}'" if isinstance(v, str) else v}
    for k, expr in G.DEF_FORMULAS.items():
        o[k] = {"value": expr}
    md["zura_generated_overrides"] = sorted(set(const) | set(G.DEF_FORMULAS))
    with open(DEFINITION, "w") as f:
        json.dump(d, f, indent=4)
        f.write("\n")
    with open(EXTRUDER, "w") as f:
        json.dump({"version": 2, "name": "Extruder 1", "inherits": "fdmextruder",
                   "metadata": {"machine": MACHINE, "position": "0"},
                   "overrides": {"extruder_nr": {"default_value": 0},
                                 "machine_nozzle_size": {"default_value": 0.4},
                                 "material_diameter": {"default_value": 1.75}}}, f, indent=4)
        f.write("\n")


def inst_cfg(name, qtype, weight, values, material=None) -> str:
    return G.inst_cfg(name, qtype, weight, values, material).replace(
        f"definition = {G.MACHINE}\n", f"definition = {MACHINE}\n", 1)


def main():
    dumps = {"m200": "/tmp/claude-0/m200cfg", "m300": "/tmp/claude-0/m300cfg"}
    if len(sys.argv) > 2:
        dumps = {sys.argv[1]: sys.argv[2]}
    for model in CLASSIC:
        select(model)
        if len(sys.argv) > 2 and model in dumps or not os.path.isdir(PROFILES):
            import_dump(dumps[model])
        generate()


def generate():
    with open(os.path.join(PROFILES, "index.json")) as f:
        index = json.load(f)["profiles"]
    os.makedirs(Q_DIR, exist_ok=True)
    for old in os.listdir(Q_DIR):
        if old.endswith(".inst.cfg"):
            os.remove(os.path.join(Q_DIR, old))
    table, qtypes = {}, {}
    for p in index:
        with open(os.path.join(PROFILES, p["file"])) as f:
            cfg = json.load(f)
        qt = G.quality_type(p["layer_id"], p["quality"])
        qtypes[qt] = (p["quality"], -int(p["layer_id"]) * 10 - G.QUALITY_RANK[p["quality"]])
        table[(G.material_id(p["material"]), qt)] = classic_values(cfg)
    # Everything that is the same for all profiles goes in the definition; the rest in the
    # material-specific quality profiles (they outrank the material files shared with the Plus printers).
    # Keys the shared material files set would override the definition, so they stay in the profiles.
    in_materials = material_file_keys()
    keys = sorted({k for v in table.values() for k in v} - in_materials)
    const = {k: next(iter(table.values()))[k] for k in keys
             if len({repr(v.get(k)) for v in table.values()}) == 1}
    write_definition(const)
    for qt, (label, weight) in qtypes.items():
        layer = next(v["layer_height"] for (m, q), v in table.items() if q == qt)
        with open(os.path.join(Q_DIR, f"{MACHINE}_global_{qt}.inst.cfg"), "w") as f:
            f.write(inst_cfg(label, qt, weight, {"layer_height": layer}))
    for (mid, qt), vals in table.items():
        label, weight = qtypes[qt]
        rest = {k: v for k, v in vals.items() if k not in const}
        with open(os.path.join(Q_DIR, f"{MACHINE}_{mid}_{qt}.inst.cfg"), "w") as f:
            f.write(inst_cfg(label, qt, weight, rest, material=mid))
    print(f"{MACHINE}: {len(table)} material profiles, {len(qtypes)} quality types; constant: {', '.join(sorted(const))}")


if __name__ == "__main__":
    main()
