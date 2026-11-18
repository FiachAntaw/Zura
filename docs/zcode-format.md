# Classic .zcode (original Zortrax M200 and M300): working notes

The original M200 and M300 (no "Plus") print `.zcode` files from an SD card. Z-Suite 2.32.0 is the last release that writes them; everything below comes from its `Zortrax.Classic.ZCode` / `Zortrax.Classic.GCode` assemblies, and `zcodex/classic.py` reproduces its compiler byte for byte (`tests/fixtures/zsuite232-classic-cube20.zcode` was written by Z-Suite's own `BinaryZCodeFile` from `zsuite232-classic-cube20.gcode`).

## File layout

| Part | Contents |
| --- | --- |
| Header | 127 bytes + CRC-8 (same polynomial 0xD5 as ZCodeData): `"ZCode"` padded to 16, version 1.0, eight int32 steps per mm (X 640, Y 640, Z 800, E 960, Fan1 1, Fan2 1, Z2 791, 0), command count, print time (s), minimum firmware (3 bytes), hardware version (M200 = 1), material / layer / quality / infill ids, support angle (100 = no automatic support), support lite, Z-Suite version (2.32.0.0), raft layers, material and support length (mm), image size, support material, nozzle id (0 = 0.4 mm), 40 zero bytes. |
| Commands | `[len][op][args][crc8]`, the same framing and opcodes as ZCodeData, but distances in motor steps rather than micrometres. Every Z move also carries Z2 (791 steps/mm). No PRINT_JUMP: travel is a PRINT_MOVE tagged Jump (252). |
| Configuration | Z-Suite's Configuration as JSON, encrypted exactly like `.zcodex2`'s ConfigurationData, split into CUSTOM_DATA (18) records of 253 bytes after the counted commands. The printer stops at the command count; Z-Suite reads it back when the file is reopened. |

Minimum firmware: M200 0.0.8, M300 1.0.3; Z-ESD 1.0.6, Z-PLA Pro and Z-ASA Pro 1.1.1 (Z-Suite's FirmwareControl per printer).

The M300 differs only in the header and steps: hardware version 20, Z2 at 800 steps/mm (same as Z), 300 × 300 × 300 mm. Z-Suite generates its G-code with the same M200 code path (`M300GCodeOrder` derives from `M200GCodeOrder`, same fan mover), and its profiles match the M200's apart from a slower travel speed (66.7 vs 90 mm/s).

## Command stream

Z-Suite generates text G-code in its own dialect and compiles it (`CmdBase.FromGCodeLine`): values are multiplied by the steps per mm and truncated, and a trailing `;<AreaName>` sets the PrintingArea byte. Its writer leaves out X/Y/Z/F values that didn't change.

1. `M190 S<bed>`, `M109 S<nozzle> T0`, `M110` (wait), then the start G-code: `G21`, `G90`, `G28 X0 Y0`, `G28 Z0`, `G92 X0 Y0 Z0 E0`, `G1 Z15.0 F180`, `G92 E0`.
2. `M191 S<n>` before each layer; raft layers count up to -1 and the model starts at 0.
3. Extrusion `G1 X Y E F ;<Area>` with absolute E. Every retraction is `G1 E<e-0.8> ;<RetractionBack>` then `G92 E0`, so E stays small; the prime is `;<RetractionForward>`.
4. Travel is `G1 ;<Jump>` at IdleMoveSpeed, Z never combined with X/Y: lift, move, lower.
5. Fan: `G1 B<0-255>`. After compiling, FanCommandsMoverM200 moves each fan command after the 15th following move.
6. End: RetractionBack, `G1 Z<z+0.2>`, then `M104 S0`, `G91`, `G28 X0 Y0`, `M84`, `G90`.
7. RecalculateProgress puts REPORT_PROGRESS 0 first, time-based percentages through the print, and 100 last. There is no PRINT_END.

Pauses are a PAUSE command (layer number, height in whole mm) right after that layer's LAYER command.

## How Zura writes it

`zcodex/classic_gcode.py` rewrites Cura's G-code into that dialect (Cura's start/end G-code and priming are replaced by Z-Suite's sequence; Cura's ;TYPE becomes the area; Cura's raft layers become Raft, RaftBottom, RaftBottomSmall and RaftInterface like Z-Suite's), compiles it with `classic.py`, then adds progress (from Cura's TIME_ELAPSED comments) and moves the fan commands. Because Cura doesn't always retract between layers, Zura also resets E at every layer. The header ids and the embedded configuration come from the bundled Z-Suite 2.32 profile for the chosen material, layer and quality (`plugins/ZortraxM/zsuite_profiles_m200/` and `zsuite_profiles_m300/`).
