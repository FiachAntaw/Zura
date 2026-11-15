# 20 mm test cube: Cura 5.14 vs Z-Suite 3.7.0

Both files are Z-ABS, 0.20 mm, High quality, with a raft, for the M200 Plus. The Cura file was sliced in headless Cura 5.14 with the Zura presets (`tests/fixtures/cura514-e2e-cube20.zcodex2`). The Z-Suite file is `tests/fixtures/zsuite-cube20.zcodex2`. Regenerate with:

```
python3 tools/compare_zcodex.py tests/fixtures/cura514-e2e-cube20.zcodex2 tests/fixtures/zsuite-cube20.zcodex2 --labels Cura Z-Suite --png-dir docs/screenshots
```

![Layer comparison](screenshots/cube-layers-cura-vs-zsuite.png)

## Overall

| | Cura | Z-Suite |
| --- | --- | --- |
| Print time (slicer estimate) | 31 min | 32 min |
| Filament | 2.12 m / 5.30 g | 2.09 m / 5.00 g |
| Nozzle / bed | 275 / 80 °C | 275 / 80 °C |
| Raft layers / raft top | 7 / 1.53 mm | 7 (+ a cleaning line) / 1.53 mm |
| First and second model layer Z | 1.89 / 2.04 mm | 1.89 / 2.04 mm |
| Model layers / top Z | 100 / 21.64 mm | 99 / 21.44 mm |
| Raft footprint | 37.2 mm | 40.0 mm |
| Retractions | 112 | 158 |
| Travel | 9.0 m | 3.3 m |
| Commands | 11,632 | 6,024 |

## Per feature

| Feature | Path (m) Cura / ZS | Speed (mm/s) Cura / ZS | Filament per mm Cura / ZS |
| --- | --- | --- | --- |
| Raft | 10.76 / 10.75 | 70 / 70 | 0.049 / 0.057 |
| Outer wall | 7.86 / 7.86 | 20 / 20 | 0.037 / 0.037 |
| Inner walls | 14.76 / 14.27 | 20 / 20 | 0.036 / 0.036 |
| Top/bottom skin | 8.60 / 6.83 | 34 / 42 | 0.033 / 0.040 |
| Infill | 9.93 / 8.23 | 67 / 67 | 0.049 / 0.049 |

## Findings

- **Fixed: raft gap.** The first comparison showed Cura printing the first model layer 0.53 mm above the raft and the second only 0.035 mm above the first, and a raft 0.3 mm taller than Z-Suite's. `RaftPlatformGap` had been mapped to `raft_airgap`, but it is the raft base height. Now `raft_airgap = FL_ModelSpace`, `layer_0_z_overlap = FL_SecondLayerLower`, raft middle/top thickness `= RB_RaftDefaultHeight` and `raft_surface_margin = RS_Enlarge`. Raft and first-layer heights now match Z-Suite exactly.
- **Fixed: flow.** Cura extrudes line width × layer height per mm for every feature; Z-Suite extrudes about 11% more on the outer wall, 8% more on inner walls and about 50% more on infill lines, which it spaces further apart. Now `wall_0_material_flow`/`wall_x_material_flow` come from `SL_ContourFeed`/`SL_InnerContourFeed` and `infill_line_width` from `IV_InfillFeed` (0.60 mm here). Filament per mm now matches on walls and infill. Top/bottom skin already matched: Z-Suite's lower feed is offset by tighter line spacing.
- **Infill pattern.** Cura uses a 20% grid; Z-Suite uses sparse diagonal lines that alternate direction.
- **First layer.** Z-Suite prints the first model layer as dense infill inside two outer contours; Cura prints it as bottom skin. Same result in practice.
- **Fixed: Z hop.** `retraction_hop_enabled`/`retraction_hop`/`retraction_min_travel` now come from `R_LiftZEnable`/`R_LiftZHeight`/`R_MinLength`, and combing is limited to infill so Cura retracts and lifts when crossing walls. Cura can only lift on a retraction, so it lifts less often than Z-Suite (which lifts on every travel over 2 mm). Combing off would lift on every travel but retracted three times as often as Z-Suite (477 vs 158), so it was not used. Cura's travel distance stays about 3× Z-Suite's.
- **Not mapped: first-layer flow.** Z-Suite's first-layer feeds (`FL_*Feed`) don't scale consistently with layer height across profiles, so they are left at 100%.
- **Height.** Cura's cube ends one layer (0.2 mm) higher.
