"""Inspect a Zortrax .zcodex2 file: header JSON, ZIP entries and decoded ZCodeData commands.

Usage: python3 zcodex2_inspect.py FILE.zcodex2 [--commands N]
"""
import argparse, json, struct, zipfile

def crc8_d5(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def read_header(data: bytes):
    n = struct.unpack_from("<I", data, 0)[0]
    meta = json.loads(data[4:4 + n])
    img = struct.unpack_from("<I", data, 4 + n)[0]
    return meta, data[8 + n:8 + n + img]

def iter_commands(zc: bytes):
    """Each record: [len][opcode, args... (len-1 bytes)][crc8 poly 0xD5 over len+body]."""
    i = 0
    while i < len(zc):
        length = zc[i]
        body = zc[i + 1:i + length]
        crc = zc[i + length]
        if crc8_d5(bytes([length]) + body) != crc:
            raise ValueError(f"CRC mismatch at offset {i}")
        yield body
        i += 1 + length

def describe(body: bytes) -> str:
    op = body[0]
    if op in (0x01, 0x1B) and len(body) >= 3:
        vals = struct.unpack("<%di" % ((len(body) - 3) // 4), body[3:])
        return f"{op:#04x} flags={body[1]:#04x} axes={body[2]:06b} {vals}"
    if len(body) > 1 and (len(body) - 1) % 4 == 0:
        return f"{op:#04x} {struct.unpack('<%di' % ((len(body) - 1) // 4), body[1:])}"
    return f"{op:#04x} {body[1:].hex(' ')}"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--commands", type=int, default=40)
    a = ap.parse_args()
    data = open(a.file, "rb").read()
    meta, image = read_header(data)
    print(json.dumps(meta, indent=1)); print("preview image bytes:", len(image))
    with zipfile.ZipFile(a.file) as z:
        for info in z.infolist(): print("entry", info.filename, info.file_size)
        cmds = list(iter_commands(z.read("ZCodeData")))
    print("commands:", len(cmds), "(header CommandCount:", meta.get("CommandCount"), ")")
    for body in cmds[:a.commands]: print(describe(body))
