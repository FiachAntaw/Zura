"""High-level: Cura G-code text -> complete .zcodex2 bytes."""
import json
import math
import os
from collections import OrderedDict
from typing import Iterable, Optional

from . import container
from .config_crypto import encrypt_configuration
from .gcode import Options, translate

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(os.path.dirname(HERE), "zsuite_profiles")

FILAMENT_DIAMETER_MM = 1.75
# Approximate densities (g/cm3) for weight estimates in the printer UI.
DENSITY = {"Z-PLA": 1.24, "Z-PLA Pro": 1.24, "Z-PETG": 1.27, "Z-GLASS": 1.27, "Z-NYLON": 1.14,
           "Z-FLEX": 1.2, "Z-SEMIFLEX": 1.2, "Z-ESD": 1.05}

# Z-Suite material ids for the M200 Plus (from Z-Suite 3.7.0).
MATERIAL_IDS = {"Z-ABS": 0, "Z-ULTRAT": 1, "Z-GLASS": 2, "Z-HIPS": 3, "Z-PCABS": 4, "Z-PETG": 5,
                "Z-ESD": 8, "Z-PLA": 10, "Z-PLA Pro": 11, "Z-ASA Pro": 12, "Z-SEMIFLEX": 14,
                "Z-FLEX": 15, "Z-NYLON": 16, "Z-ABS 2": 26, "BASF Ultrafuse ABS": 38,
                "Nanovia PC-ABS V0": 40}


def load_profile(material: str, layer_mm: float, quality: str = "High") -> dict:
    """Return {'configuration':…, 'settings':…} for the closest Z-Suite profile."""
    with open(os.path.join(PROFILE_DIR, "index.json")) as f:
        index = json.load(f)
    layer_id = str(int(round(layer_mm * 100)))
    candidates = [p for p in index["profiles"] if p["material"] == material]
    if not candidates:
        candidates = [p for p in index["profiles"] if p["material"] == "Z-ABS"]
    candidates.sort(key=lambda p: (abs(int(p["layer_id"]) - int(layer_id)), p["quality"] != quality))
    with open(os.path.join(PROFILE_DIR, candidates[0]["file"])) as f:
        return json.load(f)


def _grams(material: str, mm: float) -> float:
    area = math.pi * (FILAMENT_DIAMETER_MM / 2) ** 2
    return mm * area * DENSITY.get(material, 1.04) / 1000.0


def build(gcode: Iterable[str], *, material: str = "Z-ABS", layer_mm: float = 0.2,
          quality: str = "High", nozzle_mm: float = 0.4, raft: bool = False,
          nozzle_temperature: Optional[int] = None, bed_temperature: Optional[int] = None,
          printer_name: str = "M200 Plus", printer_model_id: int = 24, min_firmware: str = "2.6.0",
          max_z_mm: float = 180.0, preview_png: bytes = b"") -> bytes:
    profile = load_profile(material, layer_mm, quality)
    cfg = OrderedDict(profile["configuration"])
    opts = Options(
        bed_temperature=bed_temperature or cfg.get("TempBed", 80),
        nozzle_temperature=nozzle_temperature or cfg.get("TempExtruder", 250),
        linear_advance_k=float(cfg.get("LinearAdvanceKFactorModel", 0.0)),
        raft=raft,
        max_z_mm=max_z_mm,
    )
    result = translate(gcode, opts)

    cfg["TempExtruder"] = result.nozzle_temperature
    cfg["TempBed"] = result.bed_temperature
    cfg["SliceThickness"] = layer_mm
    cfg["NozzleDiameter"] = nozzle_mm
    cfg["EnableRaft"] = raft

    grams = _grams(material, result.filament_mm)
    mat_id = MATERIAL_IDS.get(material, 0)
    header = container.make_header(
        materials=[OrderedDict([("ExtruderType", "MAIN"), ("Id", mat_id), ("Name", material),
                                ("ShortName", None), ("Usage", int(round(result.filament_mm))),
                                ("UsageGrams", f"{grams:.2f}"),
                                ("Temperature", result.nozzle_temperature)])],
        bed_temperature=result.bed_temperature, command_count=result.command_count,
        print_time_s=result.print_time_s, nozzle_diameter=nozzle_mm, bbox=result.bbox,
        layer_thickness=layer_mm, total_layers=result.layers,
        printer_name=printer_name, printer_model_id=printer_model_id, min_firmware=min_firmware)

    usages = [OrderedDict([("Percentage", p), ("UsageGrams", f"{_grams(material, mm):.2f}"),
                           ("SupportUsage", "0.00")]) for p, mm in result.progress_usage_mm]
    additional = OrderedDict([("Name", "AdditionalMetadata"), ("Layers", None),
                              ("MaterialUsages", usages),
                              ("Pauses", [OrderedDict([("Time", p["Time"]), ("Material", p["Material"]),
                                                       ("LayerNumber", p["LayerNumber"])]) for p in result.pauses])])

    with open(os.path.join(HERE, "user_settings_template.json"), encoding="utf-8") as f:
        report = json.load(f, object_pairs_hook=OrderedDict)
    h, m = divmod(result.print_time_s // 60, 60)
    report.update({
        "MaxLayer": result.max_layer, "MinLayer": result.min_layer, "PrintTime": f"{h}h {m}m",
        "MaterialLength": f"{result.filament_mm / 1000:.2f}", "MaterialWeight": round(grams, 1),
        "MaterialVolume": round(grams, 1), "MaterialType": material, "MaterialId": str(mat_id),
        "LayerThickness": f"{layer_mm:.2f} mm", "NozzleDiameter": f"{nozzle_mm} mm",
        "ExtruderTemperature": result.nozzle_temperature,
        "PlatformTemperature": result.bed_temperature, "RaftEnabled": raft,
        "Quality": quality, "Printer": "Zortrax " + printer_name,
    })

    entries = {
        "AdditionalMetadata": container._dumps(additional),
        "ZCodeData": result.data,
        "ConfigurationData": encrypt_configuration(json.dumps(cfg, separators=(",", ":"))),
        "UserSettingsData": container._dumps(report),
    }
    # Every Z-Suite file carries a 320x180 PNG preview; the printer rejects files without one.
    return container.to_bytes(header, entries, preview_png or placeholder_png())


PREVIEW_SIZE = (320, 180)


def placeholder_png(width: int = PREVIEW_SIZE[0], height: int = PREVIEW_SIZE[1]) -> bytes:
    """A plain grey 320x180 PNG, used when Cura has no snapshot to offer."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = b"\x00" + b"\x80\x80\x80" * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height, 9)) + chunk(b"IEND", b""))
