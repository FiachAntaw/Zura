# Zura: Zortrax M-series support for Cura

Cura plugin for the Zortrax M200 Plus (other M-series to follow). Targets Cura 5.14 (SDK 8.13).

## What works
- **Machine**: Zortrax M200 Plus definition (200 × 200 × 180 mm, 0.4 mm nozzle, 1.75 mm filament).
- **Presets**: 15 Zortrax materials and 92 quality profiles generated from Z-Suite 3.7.0's own configurations (`tools/gen_presets.py`).
- **Output**: native `.zcodex2` writer. Cura's G-code is translated into Zortrax's binary command stream, with Z-Suite's start/end sequence, feature tags, progress reports and an encrypted `ConfigurationData` entry. See `docs/zcodex2-format.md`.
- **LAN printing**: Connect dialog (discovery or IP), send & print over FTP, Monitor tab with camera snapshot, temperatures, progress, pause/resume/abort and lights.
- Verified headless in Cura 5.14: add printer, slice, save `.zcodex2` (parses cleanly with Z-Suite's own command classes), and the whole network flow against `tests/fake_printer`.

## Not yet
- Printer acceptance test on real hardware.
- Real-hardware check of the network panel.
- M300 Plus / other models, Z-SEMIFLEX profile.

## Install (macOS)
```sh
./install_mac.sh
```
Then restart Cura and add **Zortrax M200 Plus**. To connect: Preferences → Printers → Connect via Network. Save files with "Save to Disk" (format: Zortrax ZCodex2).

## Develop
```sh
python3 tests/test_zcodex.py           # unit tests (needs `cryptography` only for tests)
python3 tools/gen_presets.py           # regenerate materials/quality from zsuite_profiles
python3 tools/zcodex2_inspect.py FILE  # dump a .zcodex2
```
