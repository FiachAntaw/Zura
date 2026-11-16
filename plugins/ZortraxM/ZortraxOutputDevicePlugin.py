"""Creates a ZortraxOutputDevice for the active Zortrax machine and runs LAN discovery."""
import threading

from PyQt6.QtCore import QTimer

from UM.Logger import Logger
from UM.OutputDevice.OutputDeviceManager import ManualDeviceAdditionAttempt
from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from UM.Signal import Signal

from cura.CuraApplication import CuraApplication

from cura.Settings.CuraStackBuilder import CuraStackBuilder

from .lan import client as lan
from .models import model_for_hardware
from .ZortraxOutputDevice import ZortraxCameraProvider, ZortraxOutputDevice

HOST_KEY = "zortrax_host"


def _broadcast_addresses() -> list:
    """Subnet broadcast address of every IPv4 interface that is up, plus 255.255.255.255."""
    addresses = []
    try:
        from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface
        flags = QNetworkInterface.InterfaceFlag
        for iface in QNetworkInterface.allInterfaces():
            f = iface.flags()
            if not (f & flags.IsUp) or not (f & flags.IsRunning) or (f & flags.IsLoopBack) or not (f & flags.CanBroadcast):
                continue
            for entry in iface.addressEntries():
                ip, bcast = entry.ip(), entry.broadcast()
                if ip.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol and not bcast.isNull():
                    addresses.append(bcast.toString())
    except Exception as e:
        Logger.log("w", "Could not list network interfaces for Zortrax discovery: %s", e)
    addresses.append("255.255.255.255")
    return list(dict.fromkeys(addresses))


class ZortraxOutputDevicePlugin(OutputDevicePlugin):
    discoveredDevicesChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._discovered = []  # [{host, hardware, serialNumber}]
        self._device = None
        self._provider_registered = False
        self._listed = {}  # host -> ZortraxOutputDevice shown in Cura's "Add printer" list
        self._refresh = QTimer()
        self._refresh.setInterval(15000)
        self._refresh.timeout.connect(self.startDiscovery)
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
        self._refresh.start()
        self._onStackChanged()

    def stop(self) -> None:
        self._refresh.stop()
        self._removeDevice()

    # ---------------------------------------------------------------- discovery
    def startDiscovery(self) -> None:
        threading.Thread(target=self._discover, daemon=True).start()

    def _discover(self) -> None:
        try:
            found = lan.discover_printers(timeout=3, broadcast=_broadcast_addresses())
        except Exception as e:
            Logger.log("w", "Zortrax discovery failed: %s", e)
            found = []
        CuraApplication.getInstance().callLater(self._setDiscovered, found)

    def _setDiscovered(self, found) -> None:
        self._discovered = found
        self._syncAddPrinterList(found)
        self.discoveredDevicesChanged.emit()

    # ---------------------------------------------------------------- Cura "Add printer" integration
    def _syncAddPrinterList(self, found) -> None:
        model = CuraApplication.getInstance().getDiscoveredPrintersModel()
        registry = CuraApplication.getInstance().getContainerRegistry()
        seen = set()
        for p in found:
            m = model_for_hardware(p.get("hardware"))
            if m is None or not registry.findDefinitionContainersMetadata(id=m[0]):
                continue
            self._listPrinter(p["host"], p.get("serialNumber", ""), m[0])
            seen.add(p["host"])
        for host in list(self._listed):
            if host not in seen and not getattr(self._listed[host], "_manual", False):
                self._listed.pop(host)
                model.removeDiscoveredPrinter(host)

    def _listPrinter(self, host: str, serial: str, definition_id: str, firmware: str = "", manual: bool = False) -> None:
        model = CuraApplication.getInstance().getDiscoveredPrintersModel()
        device = self._listed.get(host)
        if device and device.serial == serial and device.definitionId == definition_id:
            return
        if not manual and any(d.serial == serial and h != host and getattr(d, "_manual", False)
                              for h, d in self._listed.items()):
            return  # the user added this printer by IP; keep that entry
        if device:
            model.removeDiscoveredPrinter(host)
        for other_host, other in list(self._listed.items()):  # same printer found under another address
            if serial and other_host != host and other.serial == serial:
                self._listed.pop(other_host)
                model.removeDiscoveredPrinter(other_host)
        device = ZortraxOutputDevice(host, serial, definition_id, firmware)
        device._manual = manual
        self._listed[host] = device
        model.addDiscoveredPrinter(ip_address=host, key=device.getId(), name=device.getName(),
                                   create_callback=self._createMachine, machine_type=definition_id, device=device)

    def _createMachine(self, key: str) -> None:
        device = next((d for d in self._listed.values() if d.getId() == key), None)
        if device is None:
            return
        machine = CuraStackBuilder.createMachine(device.getName(), device.definitionId)
        if not machine:
            Logger.log("e", "Could not create a machine for Zortrax printer %s", device.address)
            return
        machine.setMetaDataEntry(HOST_KEY, device.address)
        CuraApplication.getInstance().getMachineManager().setActiveMachine(machine.getId())

    def canAddManualDevice(self, address: str = "") -> ManualDeviceAdditionAttempt:
        return ManualDeviceAdditionAttempt.POSSIBLE

    def addManualDevice(self, address: str, callback=None) -> None:
        def probe():
            ok, info = False, None
            try:
                client = lan.PrinterClient(address, timeout=5)
                serial = str(lan.fields(client.request([{"type": "status", "fields": ["serialNumber"]}])[0])
                             .get("serialNumber") or "")
                try:
                    version = lan.fields(client.request([{"type": "version", "fields": ["firmware", "hardware"]}])[0])
                except lan.PrinterError:
                    version = {}
                m = model_for_hardware(version.get("hardware"))
                info = (serial, m[0] if m else "zortrax_m200_plus", str(version.get("firmware") or ""))
                ok = True
            except Exception as e:
                Logger.log("i", "No Zortrax printer at %s: %s", address, e)
            CuraApplication.getInstance().callLater(done, ok, info)

        def done(ok, info):
            if ok:
                self._listPrinter(address, info[0], info[1], info[2], manual=True)
            if callback:
                callback(ok, address)
        threading.Thread(target=probe, daemon=True).start()

    def removeManualDevice(self, key: str, address=None) -> None:
        if address and address in self._listed and getattr(self._listed[address], "_manual", False):
            self._listed.pop(address)
            CuraApplication.getInstance().getDiscoveredPrintersModel().removeDiscoveredPrinter(address)

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
            self._device = ZortraxOutputDevice(host, definition_id=stack.definition.getId())
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
