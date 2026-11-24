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
        if os.environ.get("ZURA_E2E_INSTALL"):
            QTimer.singleShot(4000, self.step_install)
            return
        QTimer.singleShot(4000, self.step_machine)

    def step_install(self):
        """Install a .curapackage the way drag-and-drop does; Cura applies it on the next start."""
        app = CuraApplication.getInstance()
        pid = app.getPackageManager().installPackage(os.environ["ZURA_E2E_INSTALL"])
        log(f"install scheduled: {pid}")
        QTimer.singleShot(1000, app.closeApplication)

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
        machine = os.environ.get("ZURA_E2E_MACHINE", "zortrax_m200_plus")
        if not app.getGlobalContainerStack() or app.getGlobalContainerStack().definition.getId() != machine:
            app.getMachineManager().addMachine(machine)
        if os.environ.get("ZURA_E2E_MATERIAL"):
            app.getMachineManager().setMaterialById("0", os.environ["ZURA_E2E_MATERIAL"])
        try:
            wm = app.getWelcomePagesModel()
            wm._should_show_welcome_flow = False
            wm.shouldShowWelcomeFlowChanged.emit()
            win = app.getMainWindow()
            win.setWidth(1500); win.setHeight(950)
        except Exception as e:
            log(f"welcome/resize: {e}")
        if os.environ.get("ZURA_E2E_ADD"):
            QTimer.singleShot(6000, self.step_add)
            return
        if os.environ.get("ZURA_E2E_DUMP"):
            QTimer.singleShot(3000, self.step_dump)
            return
        QTimer.singleShot(3000, self.step_info)

    @guard
    def step_add(self):
        """Cura's Add printer flow: the fake printer must appear as a networked printer and be addable."""
        app = CuraApplication.getInstance()
        model = app.getDiscoveredPrintersModel()
        listed = {a: (p.name, p.machineType, p.readableMachineType) for a, p in model.discoveredPrintersByAddress.items()}
        log(f"discovered: {listed}")
        model.checkManualDevice(os.environ.get("ZURA_E2E_MANUAL", "127.0.0.2"))
        if os.environ.get("ZURA_E2E_SHOTS"):
            from PyQt6.QtQml import QQmlComponent
            comp = QQmlComponent(app._qml_engine)
            comp.setData(b"import QtQuick 2.15; import Cura 1.1 as Cura; Item { Component.onCompleted: Cura.Actions.addMachine.trigger() }", QUrl())
            self._trigger = comp.create()
            self._addwin = self._trigger
            if self._addwin is None:
                log("add dialog qml errors: " + "; ".join(e.toString() for e in comp.errors()))
        QTimer.singleShot(4000, self.step_add_nav)
        QTimer.singleShot(7000, self.step_add2)

    @guard
    def step_add_nav(self):
        """Click "Non UltiMaker printer" so the networked printer list shows."""
        from PyQt6.QtGui import QGuiApplication
        from PyQt6.QtCore import QMetaObject, QObject
        app = CuraApplication.getInstance()
        for w in QGuiApplication.topLevelWindows():
            if w.isVisible() and w.title() == "Add Printer":
                stack = [w.contentItem()]
                while stack:
                    o = stack.pop()
                    stack.extend(o.childItems())
                    if o.metaObject().className().startswith("AddUltimakerOrThirdPartyPrinterStack"):
                        for c in o.findChildren(QObject):
                            if "StackLayout" in c.metaObject().className():
                                c.setProperty("currentIndex", 2)
                                log("switched to non-UM printer page")
                                return
        info = []
        for w in QGuiApplication.topLevelWindows():
            n, texts = 0, []
            if hasattr(w, "contentItem"):
                stack = [w.contentItem()]
                while stack:
                    o = stack.pop(); n += 1
                    stack.extend(o.childItems())
                    t = o.property("text")
                    if isinstance(t, str) and "rinter" in t:
                        texts.append((t, type(o).__name__, o.metaObject().className()))
            info.append((w.title(), w.isVisible(), n, texts[:6]))
        log(f"non-UM button not found: {info}")

    @guard
    def step_add2(self):
        app = CuraApplication.getInstance()
        model = app.getDiscoveredPrintersModel()
        listed = {a: (p.name, p.machineType) for a, p in model.discoveredPrintersByAddress.items()}
        log(f"after manual add: {listed}")
        if os.environ.get("ZURA_E2E_SHOTS"):
            from PyQt6.QtGui import QGuiApplication
            wins = [w for w in QGuiApplication.topLevelWindows() if w.isVisible() and w is not app.getMainWindow()]
            log("windows: " + ", ".join(f"{w.title()!r} {w.width()}x{w.height()}" for w in wins))
            for w in wins:
                if hasattr(w, "grabWindow"):
                    w.grabWindow().save(os.path.join(os.environ["ZURA_E2E_SHOTS"], "add-printer.png"))
                    log("add printer shot saved")
                    w.close()
                    break
        printer = next((p for a, p in model.discoveredPrintersByAddress.items() if a != os.environ.get("ZURA_E2E_MANUAL", "127.0.0.2")), None)
        self._added = printer.address if printer else None
        if printer:
            model.createMachineFromDiscoveredPrinter(printer)
        QTimer.singleShot(6000, self.step_add3)

    @guard
    def step_add3(self):
        app = CuraApplication.getInstance()
        stack = app.getGlobalContainerStack()
        dev = app.getOutputDeviceManager().getOutputDevice(f"zortrax-{self._added}")
        log(f"active machine={stack.getName()} definition={stack.definition.getId()} host={stack.getMetaDataEntry('zortrax_host')} "
            f"device={dev is not None} state={dev.connectionState if dev else None} printer={dev.activePrinter.name if dev and dev.activePrinter else None}")
        log("done")
        QTimer.singleShot(500, app.closeApplication)

    @guard
    def step_dump(self):
        """Dump the resolved value of every preset setting for every material x quality type."""
        app = CuraApplication.getInstance()
        mm = app.getMachineManager()
        reg = app.getContainerRegistry()
        keys = json.loads(os.environ.get("ZURA_E2E_KEYS", "[]"))
        quals = reg.findInstanceContainersMetadata(type="quality", definition=os.environ.get("ZURA_E2E_MACHINE", "zortrax_m200_plus"))
        combos = sorted({(q["material"], q["quality_type"]) for q in quals if q.get("material")})
        out = {}
        for mat_id, qt in combos:
            mm.setMaterialById("0", mat_id)
            mm.setQualityGroupByQualityType(qt)
            stack = app.getGlobalContainerStack()
            ext = stack.extruderList[0]
            got = (ext.material.getMetaDataEntry("base_file"), stack.quality.getMetaDataEntry("quality_type"))
            out[f"{mat_id}|{qt}"] = {"active": list(got), "values": {k: [str(ext.getProperty(k, "value")), str(stack.getProperty(k, "value"))] for k in keys}}
        with open(os.environ["ZURA_E2E_DUMP"], "w") as f:
            json.dump(out, f, indent=0, sort_keys=True)
        log(f"dumped {len(out)} combos")
        QTimer.singleShot(500, app.closeApplication)

    @guard
    def step_info(self):
        app = CuraApplication.getInstance()
        stack = app.getGlobalContainerStack()
        ext = stack.extruderList[0]
        mats = app.getContainerRegistry().findInstanceContainersMetadata(type="material", definition=os.environ.get("ZURA_E2E_MACHINE", "zortrax_m200_plus"))
        quals = app.getContainerRegistry().findInstanceContainersMetadata(type="quality", definition=os.environ.get("ZURA_E2E_MACHINE", "zortrax_m200_plus"))
        log(json.dumps({"machine": stack.definition.getId(), "material": ext.material.getId(),
                        "quality": stack.quality.getId(), "quality_type": stack.quality.getMetaDataEntry("quality_type"),
                        "layer_height": stack.getProperty("layer_height", "value"),
                        "volume": [stack.getProperty(k, "value") for k in ("machine_width", "machine_depth", "machine_height")],
                        "print_temp": ext.getProperty("material_print_temperature", "value"),
                        "speed_wall_0": ext.getProperty("speed_wall_0", "value"),
                        "adhesion": stack.getProperty("adhesion_type", "value"),
                        "n_materials": len(mats), "n_quality": len(quals),
                        "material_ids": sorted({m.get("base_file", m["id"]) for m in mats})[:40]}))
        from cura.Machines.ContainerTree import ContainerTree
        node = ContainerTree.getInstance().machines[stack.definition.getId()]
        log("selectable materials: " + ", ".join(sorted({b for v in node.variants.values() for b in v.materials})))
        qm = app.getMachineManager().activeQualityGroups() if hasattr(app.getMachineManager(), "activeQualityGroups") else None
        app.readLocalFile(QUrl.fromLocalFile(STL))
        if os.environ.get("ZURA_E2E_PLATE"):
            QTimer.singleShot(6000, self.step_plate)
            return
        QTimer.singleShot(5000, self.step_slice)

    @guard
    def step_plate(self):
        app = CuraApplication.getInstance()
        for m in list(app.getVisibleMessages()):
            m.hide()
        QTimer.singleShot(1500, lambda: (app.getMainWindow().grabWindow().save(os.environ["ZURA_E2E_PLATE"]),
                                         log("plate shot saved"), app.closeApplication()))

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
        p = dev.activePrinter
        mat = p.extruders[0].activeMaterial
        log(f"loaded material: device={dev.loadedMaterial} model={(mat.name, mat.brand, mat.guid, mat.color) if mat else None}")
        if os.environ.get("ZURA_E2E_MISMATCH"):
            app.getMachineManager().setMaterialById("0", "zortrax_z_pla")
            dev.requestWrite(app.getController().getScene().getRoot().getChildren())
            warn = [m for m in app.getVisibleMessages() if "material" in (m.getTitle() or "").lower()]
            log(f"mismatch warning: {[(m.getTitle(), m.getText(), [a['name'] for a in m.getActions()]) for m in warn]}")
            if warn:
                if os.environ.get("ZURA_E2E_SHOTS"):
                    app.getMainWindow().grabWindow().save(os.path.join(os.environ["ZURA_E2E_SHOTS"], "mismatch.png"))
                warn[0].actionTriggered.emit(warn[0], "cancel")
                log(f"after cancel: uploading={dev._uploading}")
            log("done")
            QTimer.singleShot(500, app.closeApplication)
            return
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
        files = dev.printerFiles
        log(f"printer files: {len(files)} newest={files[0] if files else None}")
        if files:
            self._deleted = files[-1]["name"]
            dev.deleteStoredFile(self._deleted)
        QTimer.singleShot(4000, self.step_net4)

    @guard
    def step_net4(self):
        app = CuraApplication.getInstance()
        dev = app.getOutputDeviceManager().getOutputDevice("zortrax-127.0.0.1")
        names = [f["name"] for f in dev.printerFiles]
        log(f"after delete: {len(names)} files, deleted still listed={getattr(self, '_deleted', None) in names}")
        dev.sendControl("resume")  # the fake printer completes at 99%
        self._polls = 0
        QTimer.singleShot(3000, self.step_net5)

    @guard
    def step_net5(self):
        app = CuraApplication.getInstance()
        dev = app.getOutputDeviceManager().getOutputDevice("zortrax-127.0.0.1")
        p, st = dev.activePrinter, dict(dev.zortraxStatus)
        pj = p.activePrintJob
        log(f"job: printer={p.state} status={st.get('printerStatus')} name={pj.name if pj else None} "
            f"jobstate={pj.state if pj else None} progress={st.get('job_progress')} file={st.get('job_filename')} "
            f"elapsed={pj.timeElapsed if pj else None}/{pj.timeTotal if pj else None}")
        self._polls += 1
        if st.get("printerStatus") == "printing_complete" or self._polls > 40:
            log("done")
            QTimer.singleShot(500, app.closeApplication)
            return
        QTimer.singleShot(3000, self.step_net5)

def getMetaData():
    return {}

def register(app):
    return {"extension": E2E()}
