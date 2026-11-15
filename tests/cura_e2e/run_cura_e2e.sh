#!/bin/bash
# run.sh SHOTDIR  -- runs Cura twice (first run creates the machine so the welcome flow is skipped)
P=~/.local/share/cura/5.14
rm -rf $P/plugins/ZuraE2E $P/plugins/ZortraxM $P/machine_instances $P/user $P/definition_changes $P/extruders /tmp/claude-0/e2e/out
mkdir -p "$1"
cp -r /tmp/claude-0/e2e/ZuraE2E /tmp/claude-0/zura/plugins/ZortraxM $P/plugins/
cd /opt/cura/squashfs-root
timeout 300 xvfb-run -a -s "-screen 0 1600x1000x24" ./AppRun > /tmp/claude-0/cura-run1.log 2>&1
rm -rf /tmp/claude-0/e2e/out; rm -f $P/cura.log
ZURA_E2E_NET=1 ZURA_E2E_SHOTS="$1" timeout 300 xvfb-run -a -s "-screen 0 1600x1000x24" ./AppRun > /tmp/claude-0/cura-run.log 2>&1
echo exit=$?
