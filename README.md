# Zura: Zortrax M-series support for Cura

Cura plugin for the Zortrax M200 Plus and M300 Plus. Targets Cura 5.14 (SDK 8.13).

## What works
- **Machines**: Zortrax M200 Plus (200 × 200 × 180 mm) and M300 Plus (300 × 300 × 300 mm), 0.4 mm nozzle, 1.75 mm filament, with build-plate meshes. The M300 Plus shares the M200 Plus presets because Z-Suite's profiles for the two are identical.
- **Presets**: 15 Zortrax materials and 92 quality profiles generated from Z-Suite 3.7.0's own configurations (`tools/gen_presets.py`), split Cura-style into printer defaults, filament settings and quality profiles (see `docs/presets.md`).
- **Output**: native `.zcodex2` writer. Cura's G-code is translated into Zortrax's binary command stream, with Z-Suite's start/end sequence, feature tags, progress reports and an encrypted `ConfigurationData` entry. See `docs/zcodex2-format.md`.
- **LAN printing**: printers on the network appear in Cura's Add printer screen (or add by IP), send & print over FTP, Monitor tab with camera snapshot, temperatures, progress, pause/resume/abort, lights, loaded-filament sync with a mismatch warning, and a list of files on the printer (print or delete).
- **Pause at height**: Cura's Pause at height script becomes a native Zortrax pause.
- **Verified on a real M200 Plus** (firmware 2.6.15): a Cura-sliced 3DBenchy in Z-ULTRAT printed start to finish from a Zura .zcodex2.
- Verified headless in Cura 5.14: add printer, slice, save `.zcodex2` (parses cleanly with Z-Suite's own command classes), and the whole network flow against `tests/fake_printer`.

## Not yet
- Real-hardware check of Cura's Print over network button and Monitor tab (the same client code started the first real print from a script).
- Live progress: firmware 2.6.15 answered printStatus with status 2 for a whole print, so the Monitor tab estimates progress from the slicer's print time for prints it started.
- M300 Plus on real hardware (header model id 50 and firmware 2.6.0 are from Z-Suite but untested).
- M300 Dual (dual extrusion), Z-SEMIFLEX profile.

## Install
Build the package with `python3 tools/build_package.py` and drag `dist/ZortraxM-<version>.curapackage` onto Cura's window, then restart Cura. For development on macOS, `./install_mac.sh` copies the plugin folder instead.

Then add the printer from Add printer (it shows up under networked printers) or pick **Zortrax M200 Plus** / **M300 Plus** from the non-networked list. To connect: Preferences → Printers → Connect via Network. Save files with "Save to Disk" (format: Zortrax ZCodex2).

## Develop
```sh
python3 tests/test_zcodex.py           # unit tests (needs `cryptography` only for tests)
python3 tools/gen_presets.py           # regenerate materials/quality from zsuite_profiles
python3 tools/zcodex2_inspect.py FILE  # dump a .zcodex2
python3 tools/compare_zcodex.py A B    # compare two .zcodex2 files (e.g. Cura vs Z-Suite)
python3 tools/gen_platform.py          # regenerate the build-plate meshes
python3 tools/build_package.py         # build the .curapackage
```
