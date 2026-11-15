"""Machine action: pick a discovered Zortrax printer or enter its IP address."""
from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot

from UM.i18n import i18nCatalog
from cura.MachineAction import MachineAction

catalog = i18nCatalog("cura")


class ZortraxConnectAction(MachineAction):
    discoveredChanged = pyqtSignal()
    hostChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("ZortraxConnectAction", catalog.i18nc("@action", "Connect via Network"))
        self._qml_url = "qml/ConnectAction.qml"
        self._plugin = None

    def _network(self):
        if self._plugin is None:
            self._plugin = _find_plugin()
            if self._plugin:
                self._plugin.discoveredDevicesChanged.connect(self.discoveredChanged.emit)
        return self._plugin

    def needsUserInteraction(self) -> bool:
        return False

    @pyqtSlot()
    def refresh(self) -> None:
        if self._network():
            self._network().startDiscovery()

    @pyqtProperty("QVariantList", notify=discoveredChanged)
    def discovered(self):
        net = self._network()
        return [{"host": d["host"], "serial": d["serialNumber"], "hardware": d["hardware"]}
                for d in (net.getDiscovered() if net else [])]

    @pyqtProperty(str, notify=hostChanged)
    def host(self) -> str:
        return self._network().activeHost() if self._network() else ""

    @pyqtSlot(str)
    def setHost(self, host: str) -> None:
        if self._network():
            self._network().setHostForActiveMachine(host)
            self.hostChanged.emit()


def _find_plugin():
    from . import _network_plugin
    return _network_plugin[0] if _network_plugin else None
