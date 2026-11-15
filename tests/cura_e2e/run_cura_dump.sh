#!/bin/bash
# run_cura_dump.sh OUT.json -- resolve every preset setting for every material x quality in headless Cura
P=~/.local/share/cura/5.14
rm -rf $P/plugins/ZuraE2E $P/plugins/ZortraxM $P/machine_instances $P/user $P/definition_changes $P/extruders /tmp/claude-0/e2e/out
cp -r /tmp/claude-0/zura/tests/cura_e2e/ZuraE2E /tmp/claude-0/zura/plugins/ZortraxM $P/plugins/
export ZURA_E2E_KEYS=$(python3 -I -c "
import sys,json; sys.path.insert(0,'/tmp/claude-0/zura/tools'); import gen_presets as g
p=json.load(open(g.PROFILES+'/index.json'))['profiles'][0]; pr=json.load(open(g.PROFILES+'/'+p['file']))
ks=sorted(set(g.cura_values(pr['configuration'],pr['settings'],0.2))|{'retraction_prime_speed','material_flow','line_width','wall_line_width_0','infill_line_distance','default_material_print_temperature','default_material_bed_temperature','cool_fan_speed'})
print(json.dumps(ks))")
cd /opt/cura/squashfs-root
timeout 300 xvfb-run -a -s "-screen 0 1600x1000x24" ./AppRun > /tmp/claude-0/cura-run1.log 2>&1
rm -rf /tmp/claude-0/e2e/out
ZURA_E2E_DUMP="$1" timeout 600 xvfb-run -a -s "-screen 0 1600x1000x24" ./AppRun > /tmp/claude-0/cura-run.log 2>&1
cat /tmp/claude-0/e2e/out/e2e.log | tail -2
