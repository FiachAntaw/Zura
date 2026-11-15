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
        if not app.getGlobalContainerStack() or app.getGlobalContainerStack().definition.getId() != "zortrax_m200_plus":
            app.getMachineManager().addMachine("zortrax_m200_plus")
        try:
            wm = app.getWelcomePagesModel()
            wm._should_show_welcome_flow = False
            wm.shouldShowWelcomeFlowChanged.emit()
            win = app.getMainWindow()
            win.setWidth(1500); win.setHeight(950)
        except Exception as e:
            log(f"welcome/resize: {e}")
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
        writer = app.getMeshFileHandler().getWriter("ZortraxM")
        with open(os.path.join(OUT, "cura-e2e.zcodex2"), "wb") as f:
            ok = writer.write(f, None)
        log(f"zcodex2 write ok={ok} info={writer.getInformation()}")
        from io import StringIO
        g = StringIO(); PluginRegistry.getInstance().getPluginObject("GCodeWriter").write(g, None)
        open(os.path.join(OUT, "cura-e2e.gcode"), "w").write(g.getvalue())
        if os.environ.get("ZURA_E2E_NET"):
            from UM.PluginRegistry import PluginRegistry as PR
            import importlib
            mod = importlib.import_module(type(writer).__module__.rsplit(".", 1)[0])
            mod._network_plugin[0].setHostForActiveMachine("127.0.0.1")
            log("host set")
            QTimer.singleShot(8000, self.step_net)
            return
        log("done")
        QTimer.singleShot(500, app.closeApplication)

    @guard
    def step_net(self):
        app = CuraApplication.getInstance()
        dev = app.getOutputDeviceManager().getOutputDevice("zortrax-127.0.0.1")
        log(f"device={dev is not None} state={dev.connectionState if dev else None} status={dict(dev.zortraxStatus) if dev else None} camera={dev.cameraUrl if dev else None} err={dev.lastError if dev else None}")
        item = dev.monitorItem
        log(f"monitor item created={item is not None}")
        dev.requestWrite(app.getController().getScene().getRoot().getChildren())
        if os.environ.get("ZURA_E2E_SHOTS"):
            QTimer.singleShot(9000, self.step_shots)
            return
        QTimer.singleShot(10000, self.step_net2)

    @guard
    def step_shots(self):
        app = CuraApplication.getInstance()
        app.getController().setActiveStage("MonitorStage")
        QTimer.singleShot(5000, self.step_shot_monitor)

    @guard
    def step_shot_monitor(self):
        app = CuraApplication.getInstance()
        out = os.environ["ZURA_E2E_SHOTS"]
        for m in list(app.getVisibleMessages()):
            m.hide()
        QTimer.singleShot(1500, self.step_shot_monitor2)

    @guard
    def step_shot_monitor2(self):
        app = CuraApplication.getInstance()
        out = os.environ["ZURA_E2E_SHOTS"]
        app.getMainWindow().grabWindow().save(os.path.join(out, "monitor.png"))
        log("monitor shot saved")
        # Connect dialog: host the action's QML in its own window
        from cura.MachineAction import MachineAction
        action = app.getMachineActionManager().getMachineAction("ZortraxConnectAction")
        action.refresh()
        from PyQt6.QtQml import QQmlComponent
        engine = app._qml_engine
        comp = QQmlComponent(engine)
        comp.setData(b"import QtQuick 2.15; import QtQuick.Window 2.15; import UM 1.5 as UM; Window { width: 760; height: 520; visible: true; color: UM.Theme.getColor('main_background') }", QUrl())
        self._win = comp.create()
        path = os.path.join(app.getPluginRegistry().getPluginPath("ZortraxM"), "qml", "ConnectAction.qml")
        self._item = app.createQmlComponent(path, {"manager": action})
        self._item.setParentItem(self._win.contentItem())
        self._item.setProperty("width", 760); self._item.setProperty("height", 520)
        QTimer.singleShot(5000, self.step_shot_connect)

    @guard
    def step_shot_connect(self):
        out = os.environ["ZURA_E2E_SHOTS"]
        self._win.grabWindow().save(os.path.join(out, "connect.png"))
        log("connect shot saved")
        QTimer.singleShot(500, CuraApplication.getInstance().closeApplication)

    @guard
    def step_net2(self):
        app = CuraApplication.getInstance()
        dev = app.getOutputDeviceManager().getOutputDevice("zortrax-127.0.0.1")
        p = dev.activePrinter
        log(f"after send: printer state={p.state} job={(p.activePrintJob.name, p.activePrintJob.state) if p.activePrintJob else None} hotend={p.extruders[0].hotendTemperature}")
        dev.sendControl("pause")
        QTimer.singleShot(5000, self.step_net3)

    @guard
    def step_net3(self):
        app = CuraApplication.getInstance()
        dev = app.getOutputDeviceManager().getOutputDevice("zortrax-127.0.0.1")
        log(f"after pause: state={dev.zortraxStatus.get('printerStatus')}")
        log("done")
        QTimer.singleShot(500, app.closeApplication)

def getMetaData():
    return {}

def register(app):
    return {"extension": E2E()}
