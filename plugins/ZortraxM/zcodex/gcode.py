"""Translate Cura (Marlin-flavoured) G-code into Zortrax ZCodeData commands.

The translator replaces Cura's start/end G-code with the sequence Z-Suite emits
for the M200 Plus, so the machine definition's start/end G-code only needs to
carry temperatures (M104/M109/M140/M190) and Cura's usual comment markers.
"""
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from . import commands as C
from .commands import MoveType as T

# Cura ;TYPE: names -> Zortrax move types (Z-Suite tags every extrusion).
TYPE_MAP = {
    "WALL-OUTER": T.MODEL_CONTOUR,
    "WALL-INNER": T.MODEL_INVISIBLE_CONTOUR,
    "SKIN": T.VISIBLE_TOP_INFILL,
    "FILL": T.INVISIBLE_INFILL,
    "SUPPORT": T.SUPPORT_INFILL,
    "SUPPORT-INTERFACE": T.SUPPORT_INTERFACE_INFILL,
    "SKIRT": T.BRIM,
    "PRIME-TOWER": T.WASTE_TOWER_MODEL,
    "RAFT": T.RAFT,
}
RAFT_TYPES = {"base": T.RAFT_BOTTOM, "interface": T.RAFT_INTERFACE, "surface": T.RAFT_GRID}

_WORD = re.compile(r"([A-Z])\s*(-?\d*\.?\d+)")

def um(mm: float) -> int:
    return int(round(mm * 1000))


@dataclass
class Options:
    bed_temperature: int = 80
    nozzle_temperature: int = 275
    linear_advance_k: float = 0.0
    safe_z_mm: float = 15.0
    first_layer_z_um: int = 330
    compensation_span_um: int = 1200
    raft: bool = False
    end_lift_mm: float = 1.0
    max_z_mm: float = 180.0


@dataclass
class Result:
    data: bytes
    command_count: int
    bbox: List[int]
    layers: int
    min_layer: int
    max_layer: int
    filament_mm: float
    print_time_s: int
    progress_usage_mm: List[float] = field(default_factory=list)
    bed_temperature: int = 0
    nozzle_temperature: int = 0
    pauses: List[dict] = field(default_factory=list)


class Translator:
    def __init__(self, options: Options):
        self.o = options
        self.out: List[bytes] = []
        self.x = self.y = self.z = 0.0
        self.e_abs = 0.0
        self.relative_e = False
        self.relative_xyz = False
        self.feed: Optional[int] = None
        self.emitted_feed: Optional[int] = None
        self.type = T.UNKNOWN
        self.layer: Optional[int] = None
        self.min_layer = 0
        self.print_nozzle = 0
        self.print_bed = 0
        self.layers_seen = set()
        self.layer_count = 0
        self.retracted_mm = 0.0
        self.filament_mm = 0.0
        self.bbox = [math.inf, math.inf, math.inf, -math.inf, -math.inf, -math.inf]
        self.started = False
        self.progress = -1
        self.progress_usage: List[float] = []
        self.print_time_s = 0
        self.bed = options.bed_temperature
        self.nozzle = options.nozzle_temperature
        self.in_pause_block = False   # inside Cura's PauseAtHeight park/resume G-code
        self.pause_pending = False    # pause before the next layer
        self.pauses: List[dict] = []
        self.elapsed_s = 0.0
        self.encoders_on = False
        self.layer_frames: List[tuple] = []   # (index in out, Cura layer number)
        self.old_z = 0.0
        self.extruder_reselected = False

    # -- helpers -----------------------------------------------------------------
    def emit(self, cmd: bytes) -> None:
        self.out.append(cmd)

    def _feed(self) -> None:
        if self.feed is not None and self.feed != self.emitted_feed:
            self.emit(C.set_feedrate(self.feed))
            self.emitted_feed = self.feed

    def _report(self, percent: int) -> None:
        if percent > self.progress:
            self.progress = percent
            self.emit(C.report_progress(percent))
            self.progress_usage.append((percent, self.filament_mm))

    def _start(self) -> None:
        if self.started:
            return
        self.started = True
        o = self.o
        self.emit(C.set_as_value(e=0))
        self.emit(C.set_bed_temperature(self.bed))
        self.emit(C.set_extruder_temperature(self.nozzle))
        self.emit(C.wait_for_heating())
        self.emit(C.platform_compensation_range(o.first_layer_z_um, o.first_layer_z_um + o.compensation_span_um))
        self.emit(C.axis_set(C.Op.MOVE_TO_START, "x", "y"))
        self.emit(C.axis_set(C.Op.MOVE_TO_START, "z"))
        self.emit(C.set_as_value(x=0, y=0, z=0))
        self.emit(C.set_feedrate(180))
        self.emit(C.print_move(T.UNKNOWN, z=um(o.safe_z_mm)))
        self.emit(C.set_linear_advance(o.linear_advance_k, 0))
        self.emit(C.set_linear_advance(o.linear_advance_k, 1))
        if o.raft:
            self.emit(C.metadata(1))  # RaftStart
        self.emit(C.select_extruder(0))
        self.emit(C.ignore_hotend_encoders(3))
        self.emitted_feed = 180
        self.z = o.safe_z_mm
        self._report(0)

    def _layer_preamble(self, n: int) -> None:
        """Commands Z-Suite puts before particular layers (from Z-Suite 3.x output)."""
        raft_index = n - self.min_layer
        if not self.encoders_on and (n >= 0 or raft_index == 3):
            self.encoders_on = True
            self.emit(C.ignore_hotend_encoders(0))
        if not self.extruder_reselected and n >= -3:
            self.extruder_reselected = True
            self.emit(C.select_extruder(0))
        if n == 0 and self.o.raft:
            self.emit(C.metadata(101))  # RaftEnd
        if n >= 0:
            self.emit(C.set_as_value(e=0))  # Z-Suite resets E at every model layer

    def _grow_bbox(self, x, y, z) -> None:
        b = self.bbox
        b[0], b[1], b[2] = min(b[0], x), min(b[1], y), min(b[2], z)
        b[3], b[4], b[5] = max(b[3], x), max(b[4], y), max(b[5], z)

    # -- G-code handling ---------------------------------------------------------
    def comment(self, text: str) -> None:
        if "Pause at end of Preview Layer" in text:   # Cura PauseAtHeight block starts
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
            return
        if text.startswith("LAYER:"):
            self._start()
            n = int(text[6:])
            self.layer = n
            self.min_layer = min(self.min_layer, n)
            first_of_layer = n not in self.layers_seen
            self.layers_seen.add(n)
            if first_of_layer:
                self._layer_preamble(n)
            self.layer_frames.append((len(self.out), n))
            self.emit(C.layer(n))
            if self.pause_pending:
                self.pause_pending = False
                self.emit(C.pause(n, um(self.z)))  # Cura moves to the layer's Z before ;LAYER:
                self.pauses.append({"Time": int(self.elapsed_s), "Material": None, "LayerNumber": n})
            if self.layer_count:
                done = len([l for l in self.layers_seen if l >= 0]) - 1
                self._report(max(0, min(99, int(done * 100 / self.layer_count))))
        elif text.startswith("LAYER_COUNT:"):
            self.layer_count = int(text[12:])
        elif text.startswith("TYPE:"):
            name = text[5:].strip()
            self.type = TYPE_MAP.get(name, T.UNKNOWN)
            if self.layer is not None and self.layer < 0:
                self.type = T.RAFT_BOTTOM if self.layer == self.min_layer else T.RAFT
        elif text.startswith("RAFT_"):
            self.type = RAFT_TYPES.get(text[5:].strip().lower(), T.RAFT)
        elif text.startswith("TIME:"):
            try:
                self.print_time_s = int(float(text[5:]))
            except ValueError:
                pass

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
                self.e_abs = words["E"]
        elif head == "M82":
            self.relative_e = False
        elif head == "M83":
            self.relative_e = True
        elif head == "G90":
            self.relative_xyz = False
        elif head == "G91":
            self.relative_xyz = True
        elif head in ("M104", "M109") and "S" in words:
            changed = int(words["S"]) != self.nozzle
            self.nozzle = int(words["S"])
            self.print_nozzle = max(self.print_nozzle, self.nozzle)
            if self.started and self.nozzle != 0 and changed:
                self.emit(C.set_extruder_temperature(self.nozzle))
                if head == "M109":
                    self.emit(C.wait_for_heating())
        elif head in ("M140", "M190") and "S" in words:
            self.bed = int(words["S"])
            self.print_bed = max(self.print_bed, self.bed)
            if self.started and self.bed != 0:
                self.emit(C.set_bed_temperature(self.bed))
                if head == "M190":
                    self.emit(C.wait_for_heating())
        elif head in ("M0", "M1", "M25", "M601"):
            self.pause_pending = True  # a bare pause command: pause before the next layer
        elif head == "M106":
            if self.started:
                self.emit(C.print_move(T.UNKNOWN, fan2=int(max(0, min(255, words.get("S", 255))))))
        elif head == "M107":
            if self.started:
                self.emit(C.print_move(T.UNKNOWN, fan2=0))
        # Homing, G28/G29, M84 etc. are replaced by the Zortrax start/end sequence.

    def move(self, rapid: bool, w: dict) -> None:
        if "F" in w:
            self.feed = int(round(w["F"]))
        has_xyz = any(k in w for k in "XYZ")
        if not has_xyz and "E" not in w:
            return
        if not self.started:
            # Moves before the first layer belong to Cura's priming; skip them.
            self._track(w)
            return
        nx = self.x + w.get("X", 0) if self.relative_xyz else w.get("X", self.x)
        ny = self.y + w.get("Y", 0) if self.relative_xyz else w.get("Y", self.y)
        nz = self.z + w.get("Z", 0) if self.relative_xyz else w.get("Z", self.z)
        de = 0.0
        if "E" in w:
            de = w["E"] if self.relative_e else w["E"] - self.e_abs
            self.e_abs = self.e_abs + w["E"] if self.relative_e else w["E"]
        axes = {}
        if "X" in w and um(nx) != um(self.x):
            axes["x"] = um(nx)
        if "Y" in w and um(ny) != um(self.y):
            axes["y"] = um(ny)
        if "Z" in w and um(nz) != um(self.z):
            axes["z"] = um(nz)
        self.old_z = self.z
        self.x, self.y, self.z = nx, ny, nz
        self._feed()
        if de and not axes:
            kind = T.RETRACTION_BACK if de < 0 else T.RETRACTION_FORWARD
            self.retracted_mm += -de
            self.emit(C.print_move(kind, e=um(de)))
        elif de > 0:
            self.filament_mm += de
            self.emit(C.print_move(self.type, e=um(de), **axes))
            self._grow_bbox(nx, ny, nz)
        elif axes:
            if de < 0:  # retract while moving (wipe): Z-Suite only retracts in place, so split it
                self.retracted_mm += -de
                self.emit(C.print_move(T.RETRACTION_BACK, e=um(de)))
                self._jump(axes)
            else:
                self._jump(axes)

    def _jump(self, axes: dict) -> None:
        """Travel. Z-Suite never combines Z with X/Y in one jump: lift first, or lower after moving."""
        z = axes.pop("z", None)
        if axes:  # Z-Suite travels always carry both X and Y
            axes.setdefault("x", um(self.x))
            axes.setdefault("y", um(self.y))
        if z is None:
            if axes:
                self.emit(C.print_jump(T.JUMP, **axes))
            return
        rising = z > um(self.old_z)
        if rising:
            self.emit(C.print_jump(T.JUMP, z=z))
        if axes:
            self.emit(C.print_jump(T.JUMP, **axes))
        if not rising:
            self.emit(C.print_jump(T.JUMP, z=z))

    def _track(self, w: dict) -> None:
        if not self.relative_xyz:
            self.x, self.y, self.z = w.get("X", self.x), w.get("Y", self.y), w.get("Z", self.z)
        if "E" in w:
            self.e_abs = self.e_abs + w["E"] if self.relative_e else w["E"]

    def _renumber_layers(self) -> None:
        """Cura numbers raft layers -N-1..-2 and skips -1; the printer wants consecutive layer numbers
        (Z-Suite's raft layers run up to -1), so close the gap below layer 0."""
        negatives = sorted({n for _, n in self.layer_frames if n < 0})
        mapping = {n: i - len(negatives) for i, n in enumerate(negatives)}
        if all(k == v for k, v in mapping.items()):
            return
        for idx, n in self.layer_frames:
            if n in mapping:
                self.out[idx] = C.layer(mapping[n])
        self.layers_seen = {mapping.get(n, n) for n in self.layers_seen}

    def finish(self) -> Result:
        self._start()
        self._renumber_layers()
        lift = min(self.o.max_z_mm, self.z + self.o.end_lift_mm)
        self.emit(C.set_feedrate(4800))
        self.emit(C.print_move(T.JUMP, z=um(lift)))
        self.emit(C.set_extruder_temperature(0))
        self.emit(C.axis_set(C.Op.MOVE_TO_START, "x", "y"))
        self._report(100)
        self.emit(C.print_end())
        if math.isinf(self.bbox[0]):
            self.bbox = [0, 0, 0, 0, 0, 0]
        bbox = [um(v) for v in self.bbox]
        bbox[5] = max(bbox[5], um(lift))
        layers = sorted(self.layers_seen) or [0]
        return Result(
            data=b"".join(self.out), command_count=len(self.out), bbox=bbox,
            layers=len(layers), min_layer=layers[0], max_layer=layers[-1],
            filament_mm=self.filament_mm, print_time_s=self.print_time_s,
            progress_usage_mm=self.progress_usage,
            pauses=self.pauses,
            bed_temperature=self.print_bed or self.o.bed_temperature,
            nozzle_temperature=self.print_nozzle or self.o.nozzle_temperature)


def translate(lines: Iterable[str], options: Optional[Options] = None) -> Result:
    t = Translator(options or Options())
    for raw in lines:
        for part in raw.splitlines():
            t.line(part)
    return t.finish()
