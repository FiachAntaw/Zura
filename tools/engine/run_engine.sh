#!/bin/bash
# usage: run_engine.sh model.stl out.gcode
R=/opt/cura/squashfs-root; P=/mnt/project-files/zura/plugins/ZortraxM/resources
export CURA_ENGINE_SEARCH_PATH=$R/share/cura/resources/definitions:$R/share/cura/resources/extruders:$P/definitions:$P/extruders
mapfile -t A < <(python3 -I -c "import json;[print(x) for x in json.load(open('/tmp/claude-0/slice/flat_args.json'))]")
cd $R && LD_LIBRARY_PATH=$R /lib64/ld-linux-x86-64.so.2 ./CuraEngine slice -j $P/definitions/zortrax_m200_plus.def.json "${A[@]}" -e0 "${A[@]}" -l "$1" -s mesh_position_x=0 -s mesh_position_y=0 -o "$2"
