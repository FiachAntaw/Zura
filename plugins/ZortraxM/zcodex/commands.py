"""ZCodeData command encoding.

Each command is ``[len][opcode][args...][crc8]`` where ``len`` counts the length
byte, opcode and args (not the CRC). CRC-8 uses polynomial 0xD5, init 0.
Integers are little-endian; distances are micrometres.
"""
import struct
from enum import IntEnum

class Op(IntEnum):
    PRINT_MOVE = 1
    SET_FEEDRATE = 2
    SET_AS_ZERO = 3
    SET_AS_VALUE = 4
    MOVE_TO_START = 5
    MOVE_TO_END = 6
    SELECT_EXTRUDER = 7
    SET_EXTRUDER_TEMPERATURE = 8
    SET_ABSOLUTE_POSITIONING = 9
    SET_RELATIVE_POSITIONING = 10
    REPORT_PROGRESS = 11
    SLEEP = 12
    SET_EXTRUDE_RATIO = 13
    SET_BED_TEMPERATURE = 14
    PAUSE = 15
    LAYER = 16
    MOVE_TO_SPECIAL_POSITION = 17
    CUSTOM_DATA = 18
    PRINT_END = 19
    WAIT_FOR_HEATING = 20
    IGNORE_HOTEND_ENCODERS = 21
    SET_CHAMBER_TEMPERATURE = 22
    METADATA = 26
    PRINT_JUMP = 27
    SET_LINEAR_ADVANCE = 28
    SCAN_PLATFORM_DEFORMATION = 29
    SET_PLATFORM_COMPENSATION_RANGE = 30

class Axis(IntEnum):
    X = 0x01
    Y = 0x02
    Z = 0x04
    E = 0x08
    FAN1 = 0x10
    FAN2 = 0x20   # part-cooling fan, 0-255
    Z2 = 0x40
    TMP4 = 0x80

AXIS_ORDER = (Axis.X, Axis.Y, Axis.Z, Axis.E, Axis.FAN1, Axis.FAN2, Axis.Z2, Axis.TMP4)
AXIS_NAMES = {Axis.X: "X", Axis.Y: "Y", Axis.Z: "Z", Axis.E: "E", Axis.FAN1: "Fan1",
              Axis.FAN2: "Fan2", Axis.Z2: "Z2", Axis.TMP4: "Tmp4"}

class MoveType(IntEnum):
    MODEL_CONTOUR = 0
    VISIBLE_INFILL = 1
    MODEL_INVISIBLE_CONTOUR = 2
    INVISIBLE_INFILL = 3
    SUPPORT_CONTOUR = 4
    SUPPORT_INFILL = 5
    SUPPORT_INTERFACE_CONTOUR = 6
    SUPPORT_INTERFACE_INFILL = 7
    SUPPORT_SMALL_CONTOUR = 8
    SUPPORT_SMALL_INFILL = 9
    RAFT = 10
    RAFT_BOTTOM = 11
    RAFT_GRID = 12
    RAFT_INTERFACE = 13
    VISIBLE_TOP_INFILL = 14
    VISIBLE_BOTTOM_INFILL = 15
    VISIBLE_DEF_BOTTOM_CONTOUR = 16
    MODEL_CONTOUR_ENTRANCE = 20
    MODEL_CONTOUR_EXIT = 21
    FIRST_LAYER_MODEL_CONTOUR = 22
    FIRST_LAYER_MODEL_FILL = 23
    FIRST_LAYER_SUPPORT_BASE = 24
    BRIDGE_INFILL = 25
    WASTE_TOWER_MODEL = 29
    SUPPORT_BOTTOM_INFILL = 32
    BRIM = 34
    MODEL_CONTOUR_OUT = 36
    VISIBLE_DEF_TOP_INFILL = 45
    VISIBLE_DEF_BOTTOM_INFILL = 46
    SEAM = 223
    PAUSE = 224
    RETRACTION_MODEL_BACK = 243
    RETRACTION_MODEL_FORWARD = 244
    JUMP_PATH = 251
    JUMP = 252
    RETRACTION_BACK = 253
    RETRACTION_FORWARD = 254
    UNKNOWN = 255

def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def frame(opcode: int, args: bytes = b"") -> bytes:
    body = bytes([len(args) + 2, opcode]) + args
    if len(body) > 255:
        raise ValueError("command too long")
    return body + bytes([crc8(body)])

def _axes(values: dict) -> bytes:
    mask = 0
    payload = b""
    for axis in AXIS_ORDER:
        if axis in values and values[axis] is not None:
            mask |= axis
            payload += struct.pack("<i", int(values[axis]))
    return bytes([mask]) + payload

def print_move(move_type: int, **axes) -> bytes:
    """axes keyword names: x, y, z, e, fan1, fan2, z2, tmp4 (integers)."""
    values = {getattr(Axis, k.upper()): v for k, v in axes.items()}
    return frame(Op.PRINT_MOVE, bytes([move_type]) + _axes(values))

def print_jump(move_type: int = MoveType.JUMP, x=None, y=None, z=None) -> bytes:
    return frame(Op.PRINT_JUMP, bytes([move_type]) + _axes({Axis.X: x, Axis.Y: y, Axis.Z: z}))

def set_as_value(**axes) -> bytes:
    return frame(Op.SET_AS_VALUE, _axes({getattr(Axis, k.upper()): v for k, v in axes.items()}))

def axis_set(op: int, *names: str) -> bytes:
    mask = 0
    for n in names:
        mask |= getattr(Axis, n.upper())
    return frame(op, bytes([mask]))

def set_feedrate(mm_per_min: int) -> bytes:
    return frame(Op.SET_FEEDRATE, struct.pack("<i", int(mm_per_min)))

def layer(index: int) -> bytes:
    return frame(Op.LAYER, struct.pack("<i", index))

def set_bed_temperature(c: int) -> bytes:
    return frame(Op.SET_BED_TEMPERATURE, struct.pack("<i", c))

def set_extruder_temperature(c: int, extruder: int = 0) -> bytes:
    return frame(Op.SET_EXTRUDER_TEMPERATURE, struct.pack("<Bi", extruder, c))

def wait_for_heating() -> bytes:
    return frame(Op.WAIT_FOR_HEATING)

def report_progress(percent: int) -> bytes:
    return frame(Op.REPORT_PROGRESS, bytes([max(0, min(100, percent))]))

def select_extruder(i: int = 0) -> bytes:
    return frame(Op.SELECT_EXTRUDER, bytes([i]))

def set_linear_advance(k: float, extruder: int) -> bytes:
    return frame(Op.SET_LINEAR_ADVANCE, struct.pack("<fB", k, extruder))

def metadata(value: int) -> bytes:
    return frame(Op.METADATA, bytes([value]))

def ignore_hotend_encoders(flags: int) -> bytes:
    return frame(Op.IGNORE_HOTEND_ENCODERS, bytes([flags]))

def platform_compensation_range(z_min: int, z_max: int, extra: bytes = b"\x00\x00") -> bytes:
    return frame(Op.SET_PLATFORM_COMPENSATION_RANGE, struct.pack("<ii", z_min, z_max) + extra)

def print_end() -> bytes:
    return frame(Op.PRINT_END)

def iter_commands(data: bytes):
    """Yield (opcode, args) for every command, validating CRCs."""
    i = 0
    while i < len(data):
        n = data[i]
        if n < 2 or i + n >= len(data):
            raise ValueError(f"Truncated command at offset {i}")
        body = data[i:i + n]
        if crc8(body) != data[i + n]:
            raise ValueError(f"CRC mismatch at offset {i}")
        yield body[1], body[2:]
        i += n + 1

def decode_axes(args: bytes) -> dict:
    mask = args[0]
    out, pos = {}, 1
    for axis in AXIS_ORDER:
        if mask & axis:
            out[AXIS_NAMES[axis]] = struct.unpack_from("<i", args, pos)[0]
            pos += 4
    return out
