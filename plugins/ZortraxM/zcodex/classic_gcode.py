"""Translate Cura (Marlin-flavoured) G-code into a classic .zcode file for the original Zortrax M200.

Cura's moves are rewritten in the G-code dialect Z-Suite 2.32 generates for the M200 (see
``classic.py``) and compiled by the same rules Z-Suite uses, so the command stream has the same
shape as Z-Suite's own files:

  M190 / M109 T0 / M110, then Z-Suite's start G-code (home, G92 to zero, lift to Z15)
  M191 S<layer> before each layer, raft layers numbered -N..-1 and the model from 0
  G1 X Y E F ;<Area> for extrusion, with absolute E that Z-Suite resets (G92 E0) after every retraction
  G1 X Y F ;<Jump> for travel, never combining Z with X/Y (lift first, lower after)
  G1 B<0-255> for the part-cooling fan, moved 15 moves later like Z-Suite's FanCommandsMoverM200
  RetractionBack, a 0.2 mm lift and Z-Suite's end G-code (heater off, home X/Y, steppers off)

Progress records go before each layer (time based, from Cura's TIME_ELAPSED comments), with 0
first and 100 last as Z-Suite's RecalculateProgress does.
"""
import json
import math
import os
import re
import struct
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from . import classic
from . import commands as C

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
# The classic printers Z-Suite 2.32 supports (Zortrax.Classic.Printers M200Printer / M300Printer).
PRINTERS = {
    "zortrax_m200": {"profiles": "zsuite_profiles_m200", "hardware": 1, "base_fw": (0, 0, 8),
                     "steps": {"X": 640, "Y": 640, "Z": 800, "Z2": 791, "E": 960}},
    "zortrax_m300": {"profiles": "zsuite_profiles_m300", "hardware": 20, "base_fw": (1, 0, 3),
                     "steps": {"X": 640, "Y": 640, "Z": 800, "Z2": 800, "E": 960}},
}

TYPE_AREA = {
    "WALL-OUTER": "ModelContour",
    "WALL-INNER": "ModelInvisibleContour",
    "SKIN": "VisibleTopInfill",
    "FILL": "InvisibleInfill",
    "SUPPORT": "SupportInfill",
    "SUPPORT-INTERFACE": "SupportInterfaceInfill",
    "SKIRT": "Raft",
    "PRIME-TOWER": "WasteTowerModel",
}
FIRST_LAYER_AREA = {"ModelContour": "FirstLayerModelContour", "ModelInvisibleContour": "FirstLayerModelContour",
                    "SupportInfill": "FirstLayerSupport", "SupportInterfaceInfill": "FirstLayerSupport"}
MODEL_FILL = ("VisibleTopInfill", "InvisibleInfill")
START_GCODE = ["G21", "G90", "G28 X0 Y0", "G28 Z0", "G92 X0 Y0 Z0 E0", "G1 Z15.0 F180", "G92 E0"]
END_GCODE = ["M104 S0", "G91", "G28 X0 Y0", "M84", "G90"]
SAFE_Z = 15.0
FAN_DELAY_MOVES = 15

_WORD = re.compile(r"([A-Z])\s*(-?\d*\.?\d+)")


def _num(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


@dataclass
class Options:
    bed_temperature: int = 80
    nozzle_temperature: int = 275
    raft_surface_layers: int = 2
    raft_bottom_layers: int = 1   # Z-Suite's R2 layers (printed right after the base as RaftBottom)
    retract_mm: float = 0.8
    max_z_mm: float = 180.0
    steps: dict = field(default_factory=lambda: dict(classic.STEPS_M200))


@dataclass
class Result:
    commands: List[bytes]
    raft_layers: int
    model_layers: int
    filament_mm: float
    print_time_s: int
    bed_temperature: int
    nozzle_temperature: int
    pauses: List[int] = field(default_factory=list)


class Translator:
    def __init__(self, options: Options):
        self.o = options
        self.items: list = []        # G-code text, ("layer", cura_n) or ("cmd", bytes)
        self.x = self.y = 0.0
        self.z = 0.0
        self.e_in = 0.0             # Cura's E axis (absolute mode)
        self.e_out = 0.0            # E as written for the printer (absolute, reset after retractions)
        self.relative_e = False
        self.relative_xyz = False
        self.feed: Optional[int] = None
        self.written = {"F": None, "X": None, "Y": None, "Z": None}
        self.area = "Unknown"
        self.type_name = ""
        self.layer: Optional[int] = None
        self.layers: List[int] = []
        self.started = False
        self.bed = options.bed_temperature
        self.nozzle = options.nozzle_temperature
        self.print_bed = 0
        self.print_nozzle = 0
        self.fan = 0
        self.filament_mm = 0.0
        self.print_time_s = 0
        self.elapsed_s = 0.0
        self.layer_elapsed: List[float] = []   # elapsed time when each layer starts
        self.in_pause_block = False
        self.pause_pending = False
        self.pauses: List[int] = []
        self.retracted = False      # the printer's filament is retracted (a RetractionBack was written)

    # -- output ------------------------------------------------------------------
    def put(self, line: str) -> None:
        self.items.append(line)

    def g1(self, x=None, y=None, z=None, e=None, area="Unknown", fan=None) -> None:
        """Write a G1 the way Z-Suite's compressed writer does: unchanged X/Y/Z/F are left out."""
        words = []
        for k, v in (("X", x), ("Y", y), ("Z", z)):
            if v is not None and self.written[k] != _num(v):
                self.written[k] = _num(v)
                words.append(k + self.written[k])
        if e is not None:
            words.append("E" + _num(e))
        if fan is not None:
            words.append(f"B{int(fan)}")
        if not words:
            return
        if self.feed is not None and self.written["F"] != self.feed and fan is None:
            self.written["F"] = self.feed
            words.insert(0, f"F{self.feed}")
        self.put("G1 " + " ".join(words) + (f" ;<{area}>" if area != "Unknown" else ""))

    def _start(self) -> None:
        if self.started:
            return
        self.started = True
        self.put(f"M190 S{self.bed}")
        self.put(f"M109 S{self.nozzle} T0")
        self.put("M110")
        self.items.extend(START_GCODE)
        self.written.update({"X": "0", "Y": "0", "Z": _num(SAFE_Z), "F": 180})
        self.z = SAFE_Z
        self.e_out = 0.0

    # -- G-code handling ---------------------------------------------------------
    def comment(self, text: str) -> None:
        if "Pause at end of Preview Layer" in text:
            self.in_pause_block = True
            self.pause_pending = True
            return
        if "End of the Pause code" in text:
            self.in_pause_block = False
            return
        if text.startswith("TIME_ELAPSED:"):
            try:
                self.elapsed_s = float(text[13:])
            except ValueError:
                pass
        elif text.startswith("TIME:"):
            try:
                self.print_time_s = int(float(text[5:]))
            except ValueError:
                pass
        elif text.startswith("LAYER:"):
            self._start()
            n = int(text[6:])
            self.layer = n
            if n not in self.layers:
                self.layers.append(n)
                self.layer_elapsed.append(self.elapsed_s)
            self.items.append(("layer", n))
            if self.e_out:
                # Z-Suite's E stays small because it retracts (and resets E) at every layer change;
                # Cura may not retract, so reset here to keep E well inside the firmware's range.
                self.e_out = 0.0
                self.put("G92 E0")
            if self.pause_pending:
                self.pause_pending = False
                self.items.append(("pause", n))
            self._set_area()
        elif text.startswith("TYPE:"):
            self.type_name = text[5:].strip()
            self._set_area()

    def _set_area(self) -> None:
        n = self.layer
        if n is not None and n < 0:
            raft = sorted(l for l in self.layers if l < 0)
            # Cura doesn't number every raft layer up front; work out the position from the bottom.
            idx = raft.index(n) if n in raft else 0
            self.area = "raft:%d" % idx  # resolved in finish(), once the raft height is known
            return
        area = TYPE_AREA.get(self.type_name, "Unknown")
        if n == 0:
            area = FIRST_LAYER_AREA.get(area, "FirstLayerModelFill" if area in MODEL_FILL else area)
        self.area = area

    def line(self, raw: str) -> None:
        code, _, comment = raw.partition(";")
        if comment:
            self.comment(comment.strip())
        code = code.strip().upper()
        if not code or self.in_pause_block:
            return
        words = {k: float(v) for k, v in _WORD.findall(code)}
        head = code.split()[0]
        if head in ("G0", "G1"):
            self.move(head == "G0", words)
        elif head == "G92":
            if "E" in words:
                self.e_in = words["E"]
        elif head == "M82":
            self.relative_e = False
        elif head == "M83":
            self.relative_e = True
        elif head == "G90":
            self.relative_xyz = False
        elif head == "G91":
            self.relative_xyz = True
        elif head in ("M104", "M109") and "S" in words:
            t = int(words["S"])
            changed = t != self.nozzle
            self.nozzle = t
            self.print_nozzle = max(self.print_nozzle, t)
            if self.started and t != 0 and changed:
                self.put(f"M104 S{t} T0" if head == "M104" else f"M109 S{t} T0")
                if head == "M109":
                    self.put("M110")
        elif head in ("M140", "M190") and "S" in words:
            t = int(words["S"])
            changed = t != self.bed
            self.bed = t
            self.print_bed = max(self.print_bed, t)
            if self.started and t != 0 and changed:
                self.put(f"M190 S{t}")
        elif head in ("M0", "M1", "M25", "M601"):
            self.pause_pending = True
        elif head in ("M106", "M107"):
            speed = int(max(0, min(255, words.get("S", 255)))) if head == "M106" else 0
            if self.started and speed != self.fan:
                self.fan = speed
                self.g1(fan=speed)

    def move(self, rapid: bool, w: dict) -> None:
        if "F" in w:
            self.feed = int(round(w["F"]))
        if not any(k in w for k in "XYZE"):
            return
        nx = self.x + w.get("X", 0) if self.relative_xyz else w.get("X", self.x)
        ny = self.y + w.get("Y", 0) if self.relative_xyz else w.get("Y", self.y)
        nz = self.z + w.get("Z", 0) if self.relative_xyz else w.get("Z", self.z)
        de = 0.0
        if "E" in w:
            de = w["E"] if self.relative_e else w["E"] - self.e_in
            self.e_in = self.e_in + w["E"] if self.relative_e else w["E"]
        if not self.started:  # Cura's priming before the first layer: Z-Suite's start sequence replaces it
            self.x, self.y, self.z = nx, ny, nz
            return
        moved_xy = ("X" in w or "Y" in w) and (_num(nx) != _num(self.x) or _num(ny) != _num(self.y))
        moved_z = "Z" in w and _num(nz) != _num(self.z)
        old_z = self.z
        self.x, self.y, self.z = nx, ny, nz
        if de < 0:
            self._retract(-de)
            if moved_xy or moved_z:
                self._jump(nx, ny, nz, old_z, moved_xy, moved_z)
        elif de > 0 and not (moved_xy or moved_z):
            if self.retracted:  # Cura's retraction before the first layer was dropped, so is its prime
                self.retracted = False
                self.e_out += de
                self.g1(e=self.e_out, area="RetractionForward")
        elif de > 0:
            self.retracted = False
            self.e_out += de
            self.filament_mm += de
            self.g1(x=nx if moved_xy else None, y=ny if moved_xy else None,
                    z=nz if moved_z else None, e=self.e_out, area=self.area)
        elif moved_xy or moved_z:
            self._jump(nx, ny, nz, old_z, moved_xy, moved_z)

    def _retract(self, length: float) -> None:
        self.retracted = True
        self.e_out -= length
        self.g1(e=self.e_out, area="RetractionBack")
        self.e_out = 0.0
        self.put("G92 E0")

    def _jump(self, x, y, z, old_z, moved_xy, moved_z) -> None:
        rising = z > old_z
        if moved_z and rising:
            self.g1(z=z, area="Jump")
        if moved_xy:
            # Z-Suite's jumps always name both X and Y.
            self.written["X"] = self.written["Y"] = None
            self.g1(x=x, y=y, area="Jump")
        if moved_z and not rising:
            self.g1(z=z, area="Jump")

    # -- finishing ---------------------------------------------------------------
    def finish(self) -> Result:
        self._start()
        if not self.retracted:
            self._retract(self.o.retract_mm)
        self.feed = None
        self.g1(z=min(self.o.max_z_mm, self.z + 0.2))
        if self.fan:
            self.g1(fan=0)
        self.items.extend(END_GCODE)

        raft = sorted(l for l in self.layers if l < 0)
        model = sorted(l for l in self.layers if l >= 0)
        number = {n: i - len(raft) for i, n in enumerate(raft)}
        number.update({n: n for n in model})
        raft_area = {}
        for i in range(len(raft)):
            if i == 0:
                raft_area[i] = "Raft"
            elif i >= len(raft) - self.o.raft_surface_layers:
                raft_area[i] = "RaftInterface"
            elif i <= self.o.raft_bottom_layers:
                raft_area[i] = "RaftBottom"
            else:
                raft_area[i] = "RaftBottomSmall"

        total = float(self.print_time_s or (self.layer_elapsed[-1] if self.layer_elapsed else 0)) or 1.0
        start_of = dict(zip(self.layers, self.layer_elapsed))
        cmds: List[bytes] = [C.report_progress(0)]
        progress = 0
        seen = set()
        for item in self.items:
            if isinstance(item, tuple):
                kind, n = item
                if kind == "layer":
                    if n not in seen:
                        seen.add(n)
                        pct = int(start_of.get(n, 0) / total * 100)
                        if progress < pct < 100:
                            progress = pct
                            cmds.append(C.report_progress(pct))
                    cmds.append(C.layer(number[n]))
                elif kind == "pause":
                    cmds.append(C.pause(number[n], int(self.z_at_layer(n))))
                    self.pauses.append(number[n])
                continue
            if ";<raft:" in item:
                idx = int(item.split(";<raft:")[1].rstrip(">"))
                item = item.split(";<raft:")[0] + f";<{raft_area.get(idx, 'Raft')}>"
            cmds.extend(classic.compile_line(item, self.o.steps))
        cmds = move_fan_commands(cmds)
        cmds.append(C.report_progress(100))
        return Result(commands=cmds, raft_layers=len(raft), model_layers=len(model),
                      filament_mm=self.filament_mm, print_time_s=self.print_time_s,
                      bed_temperature=self.print_bed or self.o.bed_temperature,
                      nozzle_temperature=self.print_nozzle or self.o.nozzle_temperature,
                      pauses=self.pauses)

    def z_at_layer(self, n: int) -> float:
        """Z of the first move after layer n starts (Z-Suite stores the pause height as whole mm)."""
        found = False
        z = self.z
        for item in self.items:
            if item == ("layer", n):
                found = True
            elif found and isinstance(item, str) and " Z" in item:
                m = re.search(r" Z(-?[\d.]+)", item)
                if m:
                    return float(m.group(1))
        return z


def move_fan_commands(cmds: List[bytes]) -> List[bytes]:
    """Z-Suite's FanCommandsMoverM200: each fan change goes after the 15th following move."""
    def fan_only(c):
        return c[1] == C.Op.PRINT_MOVE and c[3] & 0x30 and not c[3] & 0x0F

    def moves(c):
        return c[1] == C.Op.PRINT_MOVE and c[3] & 0x0F

    out = list(cmds)
    i = len(out) - 1
    while i >= 0:
        if fan_only(out[i]):
            j, count = i, 0
            while count < FAN_DELAY_MOVES and j + 1 < len(out):
                j += 1
                if moves(out[j]):
                    count += 1
            if j > i:
                out.insert(j, out.pop(i))  # j shifts down by one once i is removed
        i -= 1
    return out


def translate(lines: Iterable[str], options: Optional[Options] = None) -> Result:
    t = Translator(options or Options())
    for raw in lines:
        for part in raw.splitlines():
            t.line(part)
    return t.finish()


# -- profiles and the complete file ------------------------------------------------
def load_index(machine: str = "zortrax_m200") -> list:
    with open(os.path.join(PLUGIN_DIR, PRINTERS[machine]["profiles"], "index.json")) as f:
        return json.load(f)["profiles"]


def load_profile(material: str, layer_id: str, quality: str, machine: str = "zortrax_m200"):
    """(index entry, Configuration) for the closest bundled Z-Suite 2.32 profile."""
    index = load_index(machine)
    candidates = [p for p in index if p["material"] == material] or [p for p in index if p["material"] == index[0]["material"]]
    candidates.sort(key=lambda p: (abs(int(p["layer_id"]) - int(layer_id)), p["quality"] != quality))
    entry = candidates[0]
    with open(os.path.join(PLUGIN_DIR, PRINTERS[machine]["profiles"], entry["file"])) as f:
        return entry, json.load(f, object_pairs_hook=OrderedDict)


def min_firmware(material_id: int, machine: str = "zortrax_m200") -> tuple:
    """Z-Suite 2.32's FirmwareControl: M200 0.0.8 / M300 1.0.3, Z-ESD 1.0.6, Z-PLA Pro / Z-ASA Pro 1.1.1."""
    if material_id in (11, 12):
        return (1, 1, 1)
    if material_id == 8:
        return max((1, 0, 6), PRINTERS[machine]["base_fw"])
    return PRINTERS[machine]["base_fw"]


def build(gcode: Iterable[str], *, material: str = "Z-ABS", layer_id: str = "19", quality: str = "High",
          support_angle: Optional[float] = None, max_z_mm: float = 180.0, machine: str = "zortrax_m200") -> bytes:
    """Cura G-code -> complete .zcode bytes. support_angle is Z-Suite's angle (None = no supports)."""
    printer = PRINTERS[machine]
    entry, cfg = load_profile(material, layer_id, quality, machine)
    opts = Options(bed_temperature=cfg["TempBed"], nozzle_temperature=cfg["TempExtruder"],
                   raft_surface_layers=cfg.get("RS_Quantity", 2), raft_bottom_layers=cfg.get("R2_Quantity", 1),
                   retract_mm=float(cfg.get("R_Back", 0.8)),
                   max_z_mm=max_z_mm, steps=dict(printer["steps"]))
    result = translate(gcode, opts)
    cfg["TempExtruder"] = result.nozzle_temperature
    cfg["TempBed"] = result.bed_temperature
    cfg["EnableRaft"] = result.raft_layers > 0
    cfg["EnableSupport"] = support_angle is not None
    header = classic.Header(
        command_count=len(result.commands),
        print_time=result.print_time_s,
        min_fw=min_firmware(entry["material_id"], machine),
        steps=dict(printer["steps"]),
        hardware_version=printer["hardware"],
        printing_profile=entry["material_id"],
        layer_thickness=int(entry["layer_id"]),
        quality=entry["quality_id"],
        infill=entry["infill_id"],
        support_angle=100 if support_angle is None else max(0, min(99, int(round(support_angle)))),
        raft_layers=max(0, result.raft_layers - 1),
        material_length=int(round(result.filament_mm)),
        nozzle_diameter=entry["nozzle_id"],
    )
    return header.to_bytes() + b"".join(result.commands) + b"".join(classic.config_records(cfg))
