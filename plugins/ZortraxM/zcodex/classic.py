"""Legacy .zcode files for the original Zortrax M200 (Z-Suite 2.x "classic" path).

A .zcode file is:

  header   127 bytes + CRC-8          (see ``Header``)
  commands [len][op][args][crc8] ...  (same framing as ZCodeData in .zcodex2)
  config   the encrypted Z-Suite Configuration, split into CUSTOM_DATA (18) records

Unlike .zcodex2, distances are motor steps (X/Y 640, Z 800, E 960 steps per mm on
the M200) and Z-Suite builds the stream from its own G-code dialect, which this
module compiles the same way Z-Suite 2.32's ``CmdBase.FromGCodeLine`` does:

  G1 X Y Z E F A B   print move (A/B = fan 1/2, 0-255), F emits SET_FEEDRATE first
  G4 P               sleep (ms)
  G28 X0 Y0 Z0 E0    move to start (home) on the named axes
  G90 / G91          absolute / relative positioning (all axes if none named)
  G92 X Y Z E        set position
  G101 T F           move to special position
  G21                ignored (metric)
  M2                 print end
  M104/M109 S T      extruder temperature
  M110               wait for heating
  M190 S             bed temperature
  M191 S             layer number
  M84                ignored
  T<n>               select extruder

A trailing ``;<AreaName>`` comment sets the move's printing area (PrintingArea enum).
"""
import json
import re
import struct
from typing import Iterable, List, Optional

from . import commands as C
from .config_crypto import encrypt_configuration

STEPS_M200 = {"X": 640, "Y": 640, "Z": 800, "Z2": 791, "E": 960}

# Zortrax.Classic.ZCode.Enums.PrintingArea
AREA = {
    "ModelContour": 0, "VisibleInfill": 1, "ModelInvisibleContour": 2, "InvisibleInfill": 3,
    "SupportContour": 4, "SupportInfill": 5, "SupportInterfaceContour": 6, "SupportInterfaceInfill": 7,
    "SupportSmallContour": 8, "SupportSmallInfill": 9, "Raft": 10, "RaftBottom": 11, "RaftBottomSmall": 12,
    "RaftInterface": 13, "VisibleTopInfill": 14, "VisibleBottomInfill": 15, "VisibleInfillContour": 16,
    "VisibleTopInfillContour": 17, "VisibleBottomInfillContour": 18, "InvisibleInfillContour": 19,
    "ModelContourEntrance": 20, "ModelContourExit": 21, "FirstLayerModelContour": 22,
    "FirstLayerModelFill": 23, "FirstLayerSupport": 24, "BridgeInfill": 25, "BridgeInfillContour": 26,
    "VisibleSmallInfill": 27, "VisibleSmallContour": 28, "WasteTowerModel": 29, "WasteTowerSupport": 30,
    "WasteTowerRaft": 31, "SupportBottomInfill": 32, "VisibleSmallTopInfill": 33, "Seam": 223, "Pause": 224,
    "RetractionSupportBack": 233, "RetractionSupportForward": 234, "RetractionModelBack": 243,
    "RetractionModelForward": 244, "JumpPath": 251, "Jump": 252, "RetractionBack": 253,
    "RetractionForward": 254, "Unknown": 255,
}

_WORD = re.compile(r"([GXYZABFEMSTP])(\S+)")
_AREA_TAG = re.compile(r"<(\w+?)>")


def _trunc(v: float) -> int:
    """C#'s (int) cast: truncate toward zero."""
    return int(v)


class GCodeError(ValueError):
    pass


def parse_line(line: str):
    """Split one Z-Suite G-code line into ({letter: str}, area) like ZCodeLine(string)."""
    parts = re.split(r"//|;", line, maxsplit=1)
    area = 255
    if len(parts) > 1:
        m = _AREA_TAG.search(parts[1])
        if m and m.group(1) in AREA:
            area = AREA[m.group(1)]
    words = {}
    for m in _WORD.finditer(parts[0]):
        words.setdefault(m.group(1), m.group(2))
    return words, area


def compile_line(line: str, steps=STEPS_M200) -> List[bytes]:
    """Compile one G-code line into framed commands (CmdBase.FromGCodeLine)."""
    w, area = parse_line(line)
    num = lambda k: float(w[k])
    out = []
    if "G" in w:
        g = int(w["G"])
        if g == 1:
            if "F" in w:
                out.append(C.set_feedrate(int(w["F"])))
            axes = {}
            if "X" in w:
                axes["x"] = _trunc(num("X") * steps["X"])
            if "Y" in w:
                axes["y"] = _trunc(num("Y") * steps["Y"])
            if "Z" in w:
                axes["z"] = _trunc(num("Z") * steps["Z"])
                if steps.get("Z2"):
                    axes["z2"] = _trunc(num("Z") * steps["Z2"])
            if "E" in w:
                axes["e"] = _trunc(num("E") * steps["E"])
            if "A" in w:
                axes["fan1"] = _trunc(num("A"))
            if "B" in w:
                axes["fan2"] = _trunc(num("B"))
            out.append(C.print_move(area, **axes))
        elif g == 4:
            if "P" not in w or int(w["P"]) < 0:
                raise GCodeError(f"G4 needs a positive P: {line!r}")
            out.append(C.frame(C.Op.SLEEP, struct.pack("<I", int(w["P"]))))
        elif g == 28:
            names = [a for a in "XYZE" if a in w]
            for a in names:
                if float(w[a]) != 0.0:
                    raise GCodeError(f"G28 only takes zero values: {line!r}")
            if names:
                out.append(C.axis_set(C.Op.MOVE_TO_START, *names))
        elif g in (90, 91):
            op = C.Op.SET_ABSOLUTE_POSITIONING if g == 90 else C.Op.SET_RELATIVE_POSITIONING
            named = [a for a in "XYZEAB" if a in w]
            if not named:
                out.append(C.frame(op, b"\xff"))
            else:
                mask = 0
                for a, bit in (("X", 1), ("Y", 2), ("Z", 4), ("E", 8), ("A", 0x10), ("B", 0x20)):
                    if a in w:
                        mask |= bit
                if "Z" in w:
                    mask |= 0x40
                out.append(C.frame(op, bytes([mask])))
        elif g == 92:
            axes = {}
            if "X" in w:
                axes["x"] = _trunc(num("X") * steps["X"])
            if "Y" in w:
                axes["y"] = _trunc(num("Y") * steps["Y"])
            if "Z" in w:
                axes["z"] = _trunc(num("Z") * steps["Z"])
                if steps.get("Z2"):
                    axes["z2"] = _trunc(num("Z") * steps["Z2"])
            if "E" in w:
                axes["e"] = _trunc(num("E") * steps["E"])
            out.append(C.set_as_value(**axes))
        elif g == 101:
            if "T" not in w:
                raise GCodeError(f"G101 needs T: {line!r}")
            if "F" in w:
                out.append(C.set_feedrate(int(w["F"])))
            out.append(C.frame(C.Op.MOVE_TO_SPECIAL_POSITION, bytes([int(w["T"])])))
        elif g == 21:
            pass
        else:
            raise GCodeError(f"Unknown command G{g}: {line!r}")
    elif "M" in w:
        m = int(w["M"])
        if m == 2:
            out.append(C.print_end())
        elif m in (104, 109):
            if "S" not in w:
                raise GCodeError(f"M{m} needs S: {line!r}")
            out.append(C.set_extruder_temperature(_trunc(num("S")), int(w.get("T", 0))))
        elif m == 110:
            out.append(C.wait_for_heating())
        elif m == 190:
            out.append(C.set_bed_temperature(_trunc(num("S"))))
        elif m == 191:
            out.append(C.layer(_trunc(num("S"))))
        elif m == 84:
            pass
        else:
            raise GCodeError(f"Unknown command M{m}: {line!r}")
    elif "T" in w:
        out.append(C.select_extruder(int(w["T"])))
    return out


class Header:
    """BinaryZCodeFileHeader: 127 bytes + CRC-8."""

    def __init__(self, **kw):
        self.description = "ZCode"
        self.version, self.sub_version = 1, 0
        self.steps = dict(STEPS_M200)
        self.command_count = 0
        self.print_time = 0          # seconds
        self.min_fw = (0, 0, 8)
        self.hardware_version = 1    # M200_V01_and_V03_BallScrew
        self.printing_profile = 0    # material id
        self.layer_thickness = 19    # layer id (hundredths of a mm, as Z-Suite labels them)
        self.quality = 1
        self.infill = 1
        self.support_angle = 100     # 100 = no automatic support
        self.support_lite = 0
        self.software_version = (2, 32, 0, 0)
        self.raft_layers = 0
        self.material_length = 0     # mm of filament (Z-Suite: metres x 1000)
        self.support_length = 0
        self.image_data_size = 0
        self.support_material = 0
        self.nozzle_diameter = 0     # nozzle id: 0 = 0.4 mm, 1 = 0.3 mm, 2 = 0.6 mm
        for k, v in kw.items():
            if not hasattr(self, k):
                raise AttributeError(k)
            setattr(self, k, v)

    def to_bytes(self) -> bytes:
        s = self.steps
        body = self.description.encode("ascii")[:16].ljust(16, b"\0")
        body += struct.pack("<BB", self.version, self.sub_version)
        body += struct.pack("<8i", s["X"], s["Y"], s["Z"], s["E"], 1, 1, s.get("Z2", 0), 0)
        body += struct.pack("<ii", self.command_count, self.print_time)
        body += bytes(self.min_fw)
        body += bytes([self.hardware_version, self.printing_profile, self.layer_thickness,
                       self.quality, self.infill, self.support_angle, self.support_lite])
        body += bytes(self.software_version)
        body += bytes([self.raft_layers])
        body += struct.pack("<iii", self.material_length, self.support_length, self.image_data_size)
        body += bytes([self.support_material, self.nozzle_diameter])
        body += b"\0" * 40
        assert len(body) == 127, len(body)
        return body + bytes([C.crc8(body)])


def config_records(configuration) -> List[bytes]:
    """The encrypted Configuration as CUSTOM_DATA records of up to 253 bytes."""
    if configuration is None:
        return []
    text = configuration if isinstance(configuration, str) else json.dumps(configuration, separators=(",", ":"))
    blob = encrypt_configuration(text)
    return [C.frame(C.Op.CUSTOM_DATA, blob[i:i + 253]) for i in range(0, len(blob), 253)]


def build(lines: Iterable[str], header: Header, configuration=None, steps=STEPS_M200) -> bytes:
    """Compile Z-Suite G-code lines into a complete .zcode file (BinaryZCodeFile.Save)."""
    cmds: List[bytes] = []
    for line in lines:
        cmds.extend(compile_line(line, steps))
    header.command_count = len(cmds)
    return header.to_bytes() + b"".join(cmds) + b"".join(config_records(configuration))


def read(data: bytes):
    """(header fields, [(op, args)]) for a .zcode file, validating CRCs."""
    head = data[:128]
    if C.crc8(head[:127]) != head[127] or not head.startswith(b"ZCode"):
        raise ValueError("Not a .zcode file (bad header)")
    fields = {
        "version": head[16], "sub_version": head[17],
        "steps": struct.unpack_from("<8i", head, 18),
        "command_count": struct.unpack_from("<i", head, 50)[0],
        "print_time": struct.unpack_from("<i", head, 54)[0],
        "min_fw": tuple(head[58:61]), "hardware_version": head[61], "printing_profile": head[62],
        "layer_thickness": head[63], "quality": head[64], "infill": head[65], "support_angle": head[66],
        "support_lite": head[67], "software_version": tuple(head[68:72]), "raft_layers": head[72],
        "material_length": struct.unpack_from("<i", head, 73)[0],
        "support_length": struct.unpack_from("<i", head, 77)[0],
        "image_data_size": struct.unpack_from("<i", head, 81)[0],
        "support_material": head[85], "nozzle_diameter": head[86],
    }
    return fields, list(C.iter_commands(data[128:]))
