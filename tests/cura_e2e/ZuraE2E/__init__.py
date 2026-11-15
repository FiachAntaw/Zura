import os, json, traceback
from PyQt6.QtCore import QTimer, QUrl
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Backend.Backend import BackendState
from cura.CuraApplication import CuraApplication

OUT = os.environ.get("ZURA_E2E_OUT", "/tmp/claude-0/e2e/out")
STL = os.environ.get("ZURA_E2E_STL", "/tmp/claude-0/slice/cube20.stl")

def log(msg):
    Logger.log("i", "ZURA_E2E " + msg)
    with open(os.path.join(OUT, "e2e.log"), "a") as f:
        f.write(msg + "\n")

class E2E(Extension):
    def __init__(self):
        super().__init__()
        os.makedirs(OUT, exist_ok=True)
        CuraApplication.getInstance().engineCreatedSignal.connect(self.on_engine)

    def on_engine(self):
        QTimer.singleShot(4000, self.step_machine)

    def guard(fn):
        def wrap(self, *a):
            try:
                fn(self, *a)
            except Exception:
                log("EXC " + traceback.format_exc())
                CuraApplication.getInstance().closeApplication()
        return wrap

    @guard
    def step_machine(self):
        app = CuraApplication.getInstance()
        app.getMachineManager().addMachine("zortrax_m200_plus")
        QTimer.singleShot(3000, self.step_info)

    @guard
    def step_info(self):
        app = CuraApplication.getInstance()
        stack = app.getGlobalContainerStack()
        ext = stack.extruderList[0]
        mats = app.getContainerRegistry().findInstanceContainersMetadata(type="material", definition="zortrax_m200_plus")
        quals = app.getContainerRegistry().findInstanceContainersMetadata(type="quality", definition="zortrax_m200_plus")
        log(json.dumps({"machine": stack.definition.getId(), "material": ext.material.getId(),
                        "quality": stack.quality.getId(), "quality_type": stack.quality.getMetaDataEntry("quality_type"),
                        "layer_height": stack.getProperty("layer_height", "value"),
                        "print_temp": ext.getProperty("material_print_temperature", "value"),
                        "speed_wall_0": ext.getProperty("speed_wall_0", "value"),
                        "adhesion": stack.getProperty("adhesion_type", "value"),
                        "n_materials": len(mats), "n_quality": len(quals),
                        "material_ids": sorted({m.get("base_file", m["id"]) for m in mats})[:40]}))
        qm = app.getMachineManager().activeQualityGroups() if hasattr(app.getMachineManager(), "activeQualityGroups") else None
        app.readLocalFile(QUrl.fromLocalFile(STL))
        QTimer.singleShot(5000, self.step_slice)

    @guard
    def step_slice(self):
        app = CuraApplication.getInstance()
        backend = app.getBackend()
        backend.backendStateChange.connect(self.on_state)
        backend.forceSlice()
        log("slice requested")

    def on_state(self, state):
        log(f"backend state {state}")
        if state == BackendState.Done:
            QTimer.singleShot(1000, self.step_write)
        elif state == BackendState.Error:
            log("slice error"); CuraApplication.getInstance().closeApplication()

    @guard
    def step_write(self):
        from UM.PluginRegistry import PluginRegistry
        app = CuraApplication.getInstance()
        writer = PluginRegistry.getInstance().getPluginObject("ZortraxM")
        with open(os.path.join(OUT, "cura-e2e.zcodex2"), "wb") as f:
            ok = writer.write(f, None)
        log(f"zcodex2 write ok={ok} info={writer.getInformation()}")
        from io import StringIO
        g = StringIO(); PluginRegistry.getInstance().getPluginObject("GCodeWriter").write(g, None)
        open(os.path.join(OUT, "cura-e2e.gcode"), "w").write(g.getvalue())
        log("done")
        QTimer.singleShot(500, app.closeApplication)

def getMetaData():
    return {}

def register(app):
    return {"extension": E2E()}
