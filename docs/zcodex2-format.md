# Zortrax .zcodex2 format (M200 Plus): working notes

Derived from `test-cube-20mm-20261113.zcodex2` (Z-Suite 3.7.0, Z-ABS, 0.2 mm, raft on) and the zsuite-mcp research notes. Use `tools/zcodex2_inspect.py` to dump any file.

## Container

| Offset | Content |
| --- | --- |
| 0 | `uint32 LE` length N of header JSON |
| 4 | header JSON (PrintId, ZCodexVersion 2.0.0.0, SoftwareVersion, MinFirmwareVersion 2.6.0, PrinterModelEnumId 24, Materials[], HeatbedTemperature, CommandCount, PrintTime s, NozzleDiameter, PrintBoundingBox in µm, LayerThickness, TotalLayersCount, Timestamp) |
| 4+N | `uint32 LE` preview image length M (0 in the sample) |
| 8+N | image bytes |
| 8+N+M | standard ZIP: `AdditionalMetadata`, `ZCodeData`, `ConfigurationData`, `UserSettingsData` |

- `AdditionalMetadata`: JSON, per-percent material usage, pauses.
- `UserSettingsData`: JSON report of the Z-Suite settings used (useful for preset porting).
- `ConfigurationData`: **encrypted**. Per the zsuite-mcp research, a fresh Rijndael key/IV per export, RSA-encrypted. Begins `1c 22 00 00 00 01 00 00`. Contents unknown.
- `ZCodeData`: **not encrypted**, binary command stream (below).

## ZCodeData command stream (solved framing)

Each command: `[len:u8][opcode:u8][args: len-2 bytes][crc:u8]`. CRC is CRC-8, poly 0xD5, init 0, over `len + opcode + args`. Verified on all 6024 commands, which matches header `CommandCount`.

Integers are little-endian int32; distances in µm.

| Opcode | Seen as | Best guess |
| --- | --- | --- |
| 0x01 | `flags, axes, int32 × popcount(axes)` | Move. Axes bit0 X, bit1 Y, bit2 Z, bit3 E (relative µm of filament), bit5 likely fan. Flags vary by feature (0x0a raft/infill, 0x0e perimeter, 0xfc/0xfd/0xfe travel/retract/prime, 0xff special) |
| 0x1b | same as 0x01 | Travel move (no extrusion) |
| 0x02 | int32 | Feed rate (values 180…12000, likely mm/min) |
| 0x10 | int32 | Layer index (raft starts at -8) |
| 0x0e | int32 | Heatbed temperature (80) |
| 0x04, 0x05, 0x07, 0x08, 0x0b, 0x13, 0x14, 0x15, 0x1a, 0x1c, 0x1e | small args | Start/end sequence, fan, waits, homing etc. To confirm against Z-Suite.dll |

## Open questions

1. Does the printer require a valid `ConfigurationData`? Encrypting it ourselves needs Zortrax's RSA public key (in Z-Suite.dll) plus the plaintext layout. Reusing one from a Z-Suite export may also work.
2. Exact meaning of the setup opcodes and flag bits, from decompiling Z-Suite.dll.
3. Firmware-side checks at `printFromStorage` (startPrintAdditionalInfo: corrupted file=1, wrong device=2…).
