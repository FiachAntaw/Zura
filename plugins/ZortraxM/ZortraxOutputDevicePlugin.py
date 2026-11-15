"""Creates a ZortraxOutputDevice for the active Zortrax machine and runs LAN discovery."""
import threading

from PyQt6.QtCore import QTimer

from UM.Logger import Logger
from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from UM.Signal import Signal

from cura.CuraApplication import CuraApplication

from .lan import client as lan
from .ZortraxOutputDevice import ZortraxCameraProvider, ZortraxOutputDevice

HOST_KEY = "zortrax_host"


class ZortraxOutputDevicePlugin(OutputDevicePlugin):
    discoveredDevicesChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._discovered = []  # [{host, hardware, serialNumber}]
        self._device = None
        self._provider_registered = False
        app = CuraApplication.getInstance()
        app.globalContainerStackChanged.connect(self._onStackChanged)
        app.engineCreatedSignal.connect(self._onEngineCreated)

    def _onEngineCreated(self) -> None:
        engine = CuraApplication.getInstance()._qml_engine
        if engine and not self._provider_registered:
            engine.addImageProvider("zortraxcam", ZortraxCameraProvider.instance())
            self._provider_registered = True

    def start(self) -> None:
        self.startDiscovery()
        self._onStackChanged()

    def stop(self) -> None:
        self._removeDevice()

    # ---------------------------------------------------------------- discovery
    def startDiscovery(self) -> None:
        threading.Thread(target=self._discover, daemon=True).start()

    def _discover(self) -> None:
        try:
            found = lan.discover_printers(timeout=3)
        except Exception as e:
            Logger.log("w", "Zortrax discovery failed: %s", e)
            found = []
        CuraApplication.getInstance().callLater(self._setDiscovered, found)

    def _setDiscovered(self, found) -> None:
        self._discovered = found
        self.discoveredDevicesChanged.emit()

    def getDiscovered(self):
        return list(self._discovered)

    # ---------------------------------------------------------------- active machine
    def setHostForActiveMachine(self, host: str) -> None:
        stack = CuraApplication.getInstance().getGlobalContainerStack()
        if stack is None:
            return
        stack.setMetaDataEntry(HOST_KEY, host.strip())
        self._onStackChanged()

    def activeHost(self) -> str:
        stack = CuraApplication.getInstance().getGlobalContainerStack()
        return (stack.getMetaDataEntry(HOST_KEY, "") or "") if stack else ""

    def _onStackChanged(self) -> None:
        stack = CuraApplication.getInstance().getGlobalContainerStack()
        host = ""
        if stack is not None and stack.definition.getId().startswith("zortrax_"):
            host = stack.getMetaDataEntry(HOST_KEY, "") or ""
        if self._device and self._device.host == host:
            return
        self._removeDevice()
        if not host:
            return
        try:
            self._device = ZortraxOutputDevice(host)
        except ValueError:
            Logger.log("w", "Invalid Zortrax printer address %s", host)
            return
        self.getOutputDeviceManager().addOutputDevice(self._device)
        self._device.connect()

    def _removeDevice(self) -> None:
        if self._device:
            self._device.close()
            self.getOutputDeviceManager().removeOutputDevice(self._device.getId())
            self._device = None
