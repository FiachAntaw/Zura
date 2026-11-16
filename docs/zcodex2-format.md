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
- `ConfigurationData`: the full Z-Suite slicer `Configuration` object (about 300 fields: speeds, feeds, temperatures, raft, support, fan, linear advance…) serialized as JSON with Newtonsoft, then encrypted. Layout: `int32 total`, then `int32 len + RSA-OAEP(AES key)`, `int32 len + RSA-OAEP(AES IV)`, `int32 len + AES-CBC/PKCS7(JSON)`. RSA is 2048-bit, exponent AQAB. The **public** key is embedded in Z-Suite.dll (string id 75326), so we can produce valid ConfigurationData ourselves. We cannot decrypt Z-Suite's (the private key is on the printer side).
- `ZCodeData`: **not encrypted**, binary command stream (below).

## ZCodeData command stream (solved framing)

Each command: `[len:u8][opcode:u8][args: len-2 bytes][crc:u8]`. CRC is CRC-8, poly 0xD5, init 0, over `len + opcode + args`. Verified on all 6024 commands, which matches header `CommandCount`.

Integers are little-endian int32; distances in µm.

Command names recovered from Z-Suite.dll (`tools/dotnet/ZCodeDump.cs` decodes a file using Z-Suite's own classes; full cube listing in `docs/test-cube-decoded.txt`):

| Op | Name | Args |
| --- | --- | --- |
| 1 | PrintMove | moveType u8, axisMask u8, int32 per set axis (bit0 X, 1 Y, 2 Z, 3 E relative, 5 Fan2, others TBD) |
| 2 | SetFeedrate | int32 mm/min |
| 3 | SetAsZero | axis set |
| 4 | SetAsValue | axisMask + int32 values (G92 equivalent) |
| 5 | MoveToStart | axis set (homing) |
| 6 | MoveToEnd | axis set |
| 7 | SelectExtruder | u8 |
| 8 | SetExtruderTemperature | u8 extruder, int32 °C |
| 9 / 10 | SetAbsolute / SetRelativePositioning | axis set |
| 11 | ReportProgress | u8 percent |
| 12 | Sleep | uint32 |
| 13 | SetExtrudeRatio | moveType u8, float |
| 14 | SetBedTemperature | int32 |
| 15 | Pause | int32, int32 |
| 16 | Layer | int32 (raft layers negative) |
| 17 | MoveToSpecialPosition | enum |
| 18 | CustomData | bytes |
| 19 | PrintEnd | – |
| 20 | WaitForHeating | optional uint32 |
| 21 | CmdIgnoreHotendEncoders | flags |
| 22 | SetChamberTemperature | int32 |
| 26 | MetaData | u8 (e.g. RaftStart) |
| 27 | PrintJump | moveType, X/Y/Z (travel) |
| 28 | SetLinearAdvance | float K, u8 extruder |
| 29 | ScanPlatformDeformation | – |
| 30 | SetPlatformCompensationRange | int32 min, int32 max (µm) |

Move types tag every extrusion with a feature (ModelContour 0, VisibleInfill 1, InvisibleInfill 3, Support* 4–9, Raft 10–13, VisibleTopInfill 14, BridgeInfill 25, Brim 34, Seam 223, RetractionBack 253, RetractionForward 254, Jump 252…). Cura's `;TYPE:` comments map onto these.

Start sequence Z-Suite emits (M200 Plus): `SetAsValue E0, SetBedTemperature, SetExtruderTemperature, WaitForHeating, SetPlatformCompensationRange(330-1530), MoveToStart XY, MoveToStart Z, SetAsValue XYZ0, feed 180, PrintMove Z15000, SetLinearAdvance ×2, MetaData RaftStart, Layer…`. End: `RetractionBack, Jump Z, extruder 0 °C, MoveToStart XY, ReportProgress 100, PrintEnd`.

## Open questions

1. Which `ConfigurationData` fields the firmware actually uses. We can generate it, but must fill it sensibly (from Z-Suite's default profile for the chosen material).
2. Remaining PrintMove axis bits (4, 6, 7).
3. Firmware-side checks at `printFromStorage` (startPrintAdditionalInfo: corrupted file=1, wrong device=2…).

## Printer protocol notes from the first real print (M200 Plus, firmware 2.6.15)

- `printFromStorage` takes the **bare file name** (`"benchy.zcodex2"`), as Z-Suite sends `Path.GetFileName(file)`. With a leading `/` the printer answers `{"status":"3","startPrintAdditionalInfo":1}` ("corrupted file") even for Z-Suite's own files.
- `wakeUp` closes the connection without a reply; Z-Suite only sends it when `printerStatus` is `sleeping`.
- `printStatus` answers `{"status":"2"}` while idle, and on this printer also throughout a print. Z-Suite asks for it in its own request, only while printing.
- `printerStatus` values seen: `idling`, `preparing_for_print`, `heating`, `busy` (homing/calibration), `printing`, `failsafe` (this printer reports failsafe 55/5/5 at the end of every print, a known quirk).
- `version` replies with typed values: `protocol` 1, `firmware` "2.6.15", `software` 23727, `hardware` 24.
- FTP `MLSD` works; sizes are strings and `modify` is `YYYYMMDDHHMMSS.mmm`.

### Discovery (UDP 8001)

Z-Suite sends the ASCII probe `Zortrax` to each interface's subnet broadcast address (for example 192.168.1.255) on UDP port 8001 and reads replies into a 33-byte buffer. A real M200 Plus (firmware 2.6.15) answers from port 8001 with only 10 bytes: the hardware byte (0x18 = 24, M200 Plus) followed by the 9-character serial, with no padding. Parse the reply by length, not as a fixed 33-byte record.

### FTP delete quirk

The M200 Plus (firmware 2.6.15) answers `DELE` with `450 Can't delete file …` even though the file is removed. The client treats a 4xx reply as success when a directory listing shows the file is gone.

### Lights

Z-Suite 3.7 sends `setSetting` with `lights` = `off` / `white` / `dynamic`, but its printer Settings tab (the only place that calls it) is commented out. On the M200 Plus (firmware 2.6.15) the command returns status 1 while the lights stay unchanged and `getSetting` keeps reporting `off`, so Zura doesn't offer a lights control. The LAN client still verifies by read-back and reports a mismatch.
