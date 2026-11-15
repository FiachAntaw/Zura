"""Cura output device for a Zortrax printer on the LAN: send & print, status, camera, controls."""
import base64
import json
import re
import threading
import time
from io import StringIO
from typing import Optional

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage

from UM.Logger import Logger
from UM.Message import Message
from UM.PluginRegistry import PluginRegistry
from UM.i18n import i18nCatalog

from cura.CuraApplication import CuraApplication
from cura.PrinterOutput.Models.MaterialOutputModel import MaterialOutputModel
from cura.PrinterOutput.Models.PrintJobOutputModel import PrintJobOutputModel
from cura.PrinterOutput.Models.PrinterOutputModel import PrinterOutputModel
from cura.PrinterOutput.PrinterOutputController import PrinterOutputController
from cura.PrinterOutput.PrinterOutputDevice import ConnectionState, ConnectionType, PrinterOutputDevice

from .lan import client as lan
from .models import name_for_definition
from . import ZCodex2Writer

catalog = i18nCatalog("cura")

# Zortrax printerStatus -> Cura printer / job state strings
PRINTER_STATE = {"printing": "printing", "paused": "paused", "pausing": "paused", "idle": "idle", "idling": "idle",
                 "heating": "pre_print", "failsafe": "error", "sleep": "idle", "sleeping": "idle", "aborting": "printing",
                 "finished": "idle", "maintenance": "maintenance"}
JOB_STATE = {"printing": "printing", "heating": "pre_print", "paused": "paused", "pausing": "pausing",
             "aborting": "aborting", "finished": "finished"}


class ZortraxController(PrinterOutputController):
    def __init__(self, device: "ZortraxOutputDevice") -> None:
        super().__init__(device)
        self.can_pause = True
        self.can_abort = True
        self.can_pre_heat_bed = False
        self.can_pre_heat_hotends = False
        self.can_send_raw_gcode = False
        self.can_control_manually = False

    def setJobState(self, job, state: str) -> None:
        action = {"pause": "pause", "print": "resume", "abort": "abort"}.get(state)
        if action:
            self._output_device.sendControl(action)


class ZortraxOutputDevice(PrinterOutputDevice):
    cameraChanged = pyqtSignal()
    statusChanged = pyqtSignal()
    filesChanged = pyqtSignal()

    def __init__(self, host: str, serial: str = "", definition_id: str = "zortrax_m200_plus",
                 firmware: str = "", parent: QObject = None) -> None:
        super().__init__(device_id="zortrax-" + host, connection_type=ConnectionType.NetworkConnection, parent=parent)
        self._host = host
        self._address = host
        self._serial = serial
        self._definition_id = definition_id
        self._firmware = firmware
        self._client = lan.PrinterClient(host, timeout=10)
        self._lock = threading.Lock()
        self._busy = False
        self._status: dict = {}
        self._camera_url = ""
        self._camera_counter = 0
        self._camera_enabled = True
        self._last_error = ""
        self._uploading = False
        self._loaded_material = ""
        self._files: list = []
        self._files_loading = False
        self._files_requested = False
        self._model_name = name_for_definition(definition_id)
        self.setName(self._model_name + (" (" + serial + ")" if serial else ""))
        self.setShortDescription(catalog.i18nc("@action:button", "Print over network"))
        self.setDescription(catalog.i18nc("@properties:tooltip", "Send to the Zortrax printer at {0}").format(host))
        self.setIconName("print")
        self.setConnectionText(catalog.i18nc("@info:status", "Connected to Zortrax printer at {0}").format(host))
        self._monitor_view_qml_path = PluginRegistry.getInstance().getPluginPath("ZortraxM") + "/qml/MonitorItem.qml"
        self._update_timer.setInterval(3000)
        printer = PrinterOutputModel(output_controller=ZortraxController(self), number_of_extruders=1)
        printer.updateName(self.getName())
        printer.updateType(self._model_name)
        self._printers = [printer]
        self._setAcceptsCommands(True)

    # ------------------------------------------------------------------ status polling
    def _update(self) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self) -> None:
        try:
            with self._lock:
                responses = self._client.status()
                camera = None
                if self._camera_enabled:
                    try:
                        camera = self._client.camera(50)
                    except lan.PrinterError:
                        camera = None
            CuraApplication.getInstance().callLater(self._applyStatus, responses, camera)
        except Exception as e:  # network failures are expected when the printer is off
            CuraApplication.getInstance().callLater(self._applyError, str(e))
        finally:
            self._busy = False

    def _wake_if_sleeping(self) -> None:
        """Like Z-Suite: wake the printer only when it reports "sleeping" (wakeUp drops the connection)."""
        try:
            state = lan.fields(self._client.status()[0]).get("printerStatus")
        except lan.PrinterError:
            return
        if state == "sleeping":
            try:
                self._client.control("wakeUp")
            except lan.PrinterError:
                pass
            time.sleep(1)

    def _applyError(self, text: str) -> None:
        self._last_error = text
        self.setConnectionState(ConnectionState.Error)
        self.statusChanged.emit()

    def _applyStatus(self, responses, camera) -> None:
        status = lan.fields(responses[0])
        job = lan.fields(responses[1]) if len(responses) > 1 else {}
        self._status = {**status, **{"job_" + k: v for k, v in job.items()}}
        self._last_error = ""
        self.setConnectionState(ConnectionState.Connected)
        if not self._files_requested:
            self._files_requested = True
            self.refreshFiles()
        printer = self._printers[0]
        serial = status.get("serialNumber")
        if serial and printer.name != "{0} ({1})".format(self._model_name, serial):
            printer.updateName("{0} ({1})".format(self._model_name, serial))
        state = str(status.get("printerStatus", "")).lower()
        printer.updateState(PRINTER_STATE.get(state, "idle"))
        self._syncLoadedMaterial(str(status.get("currentMaterial") or ""))
        try:
            printer.extruders[0].updateHotendTemperature(float(status.get("hotendTemperature", 0)))
            printer.updateBedTemperature(float(status.get("heatbedTemperature", 0)))
        except (TypeError, ValueError):
            pass
        in_progress = str(status.get("printingInProgress", "0")) not in ("0", "False", "false", "")
        if in_progress or state in JOB_STATE:
            name = str(job.get("filename") or "print")
            pj = printer.activePrintJob
            if pj is None or pj.name != name:
                pj = PrintJobOutputModel(output_controller=printer.getController(), key=name, name=name)
                printer.updateActivePrintJob(pj)
            pj.updateState(JOB_STATE.get(state, "printing"))
            progress = self._progress(job)
            if progress is not None:
                total = self._estimated_seconds(job)
                if total:
                    pj.updateTimeTotal(total)
                    pj.updateTimeElapsed(int(total * progress / 100))
        else:
            printer.updateActivePrintJob(None)
        if camera:
            image = QImage.fromData(base64.b64decode(camera["data"]))
            if not image.isNull():
                ZortraxCameraProvider.instance().setImage(self._host, image)
                self._camera_counter += 1
                self._camera_url = "image://zortraxcam/{0}?{1}".format(self._host, self._camera_counter)
                self.cameraChanged.emit()
        self.statusChanged.emit()

    def _syncLoadedMaterial(self, name: str) -> None:
        """Show the filament the printer reports as loaded on Cura's printer model."""
        if name == self._loaded_material:
            return
        self._loaded_material = name
        extruder = self._printers[0].extruders[0]
        if not name:
            extruder.updateActiveMaterial(None)
            return
        meta = _zortrax_material(name)
        extruder.updateActiveMaterial(MaterialOutputModel(
            guid=meta.get("GUID") if meta else None, type=meta.get("material", "") if meta else "",
            color=meta.get("color_code", "#ffffff") if meta else "#ffffff", brand="Zortrax", name=name))

    @pyqtProperty(str, notify=statusChanged)
    def loadedMaterial(self) -> str:
        return self._loaded_material

    @staticmethod
    def _progress(job: dict) -> Optional[float]:
        try:
            return float(job.get("progress"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _estimated_seconds(job: dict) -> int:
        meta = job.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = {}
        if isinstance(meta, dict):
            try:
                return int(meta.get("PrintTime") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    # ------------------------------------------------------------------ QML properties
    @pyqtProperty(str, notify=cameraChanged)
    def cameraUrl(self) -> str:
        return self._camera_url

    @pyqtProperty("QVariantMap", notify=statusChanged)
    def zortraxStatus(self) -> dict:
        return {k: str(v) for k, v in self._status.items()}

    @pyqtProperty(str, notify=statusChanged)
    def lastError(self) -> str:
        return self._last_error

    @pyqtProperty(str, constant=True)
    def host(self) -> str:
        return self._host

    @pyqtProperty(str, constant=True)
    def name(self) -> str:
        """Cura's "Add printer" list reads device.name."""
        return self.getName()

    @property
    def address(self) -> str:
        return self._host

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def definitionId(self) -> str:
        return self._definition_id

    @pyqtSlot(str, result=str)
    def getProperty(self, key: str) -> str:
        """Used by Cura's "Add printer by IP" page."""
        return {"firmware_version": self._firmware, "serial": self._serial, "address": self._host}.get(key, "")

    # ------------------------------------------------------------------ controls
    @pyqtSlot(str)
    def sendControl(self, action: str) -> None:
        threading.Thread(target=self._control, args=(action,), daemon=True).start()

    def _control(self, action: str) -> None:
        try:
            with self._lock:
                self._client.control(action)
        except Exception as e:
            CuraApplication.getInstance().callLater(self._showError, catalog.i18nc("@info", "{0} failed: {1}").format(action, e))

    @pyqtSlot(str)
    def setLights(self, value: str) -> None:
        def run():
            try:
                with self._lock:
                    self._client.set_setting("lights", value)
            except Exception as e:
                CuraApplication.getInstance().callLater(self._showError, str(e))
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------ files on the printer
    @pyqtProperty("QVariantList", notify=filesChanged)
    def printerFiles(self) -> list:
        return self._files

    @pyqtProperty(bool, notify=filesChanged)
    def filesLoading(self) -> bool:
        return self._files_loading

    @pyqtSlot()
    def refreshFiles(self) -> None:
        if self._files_loading:
            return
        self._files_loading = True
        self.filesChanged.emit()
        threading.Thread(target=self._listFiles, daemon=True).start()

    def _listFiles(self) -> None:
        app = CuraApplication.getInstance()
        try:
            with self._lock:
                entries = self._client.list_files("/")
            app.callLater(self._setFiles, _print_files(entries), None)
        except Exception as e:
            app.callLater(self._setFiles, None, str(e))

    def _setFiles(self, files, error) -> None:
        self._files_loading = False
        if files is not None:
            self._files = files
        elif error:
            Logger.log("w", "Could not list files on %s: %s", self._host, error)
        self.filesChanged.emit()

    @pyqtSlot(str)
    def printStoredFile(self, name: str) -> None:
        def run():
            try:
                with self._lock:
                    self._wake_if_sleeping()
                    self._client.print_file(name, forced=False)
                CuraApplication.getInstance().callLater(self._update)
            except Exception as e:
                info = re.search(r'"startPrintAdditionalInfo"\s*:\s*"?(\d+)', str(e))
                reason = lan.describe_start_info(info.group(1)) if info else str(e)
                CuraApplication.getInstance().callLater(
                    self._showError, catalog.i18nc("@info", "The printer refused to start {0}: {1}").format(name, reason))
        threading.Thread(target=run, daemon=True).start()

    @pyqtSlot(str)
    def deleteStoredFile(self, name: str) -> None:
        def run():
            try:
                with self._lock:
                    self._client.delete("/" + name)
            except Exception as e:
                CuraApplication.getInstance().callLater(self._showError, str(e))
            CuraApplication.getInstance().callLater(self.refreshFiles)
        threading.Thread(target=run, daemon=True).start()

    def _showError(self, text: str) -> None:
        Message(text, title=catalog.i18nc("@info:title", "Zortrax printer"), message_type=Message.MessageType.ERROR).show()

    # ------------------------------------------------------------------ send & print
    def requestWrite(self, nodes, file_name=None, limit_mimetypes=False, file_handler=None, filter_by_machine=False, **kwargs) -> None:
        if self._uploading:
            Message(catalog.i18nc("@info", "A file is already being sent to this printer."), title="Zortrax").show()
            return
        sliced_for = _active_material_name()
        if self._loaded_material and sliced_for and _norm(sliced_for) != _norm(self._loaded_material):
            self._confirmMismatch(nodes, sliced_for)
            return
        self._sendNodes(nodes)

    def _confirmMismatch(self, nodes, sliced_for: str) -> None:
        message = Message(
            catalog.i18nc("@info", "This print was prepared for {0}, but the printer has {1} loaded. The printer may refuse it or print with the wrong settings.")
            .format(sliced_for, self._loaded_material),
            title=catalog.i18nc("@info:title", "Different material loaded"), lifetime=0,
            message_type=Message.MessageType.WARNING)
        message.addAction("send", catalog.i18nc("@action:button", "Print anyway"), "", "")
        message.addAction("cancel", catalog.i18nc("@action:button", "Cancel"), "", "",
                          button_style=Message.ActionButtonStyle.SECONDARY)
        self._pending_nodes = nodes
        message.actionTriggered.connect(self._onMismatchAction)
        self._mismatch_message = message
        message.show()

    def _onMismatchAction(self, message, action: str) -> None:
        message.hide()
        nodes, self._pending_nodes = getattr(self, "_pending_nodes", None), None
        if action == "send" and nodes is not None:
            self._sendNodes(nodes)

    def _sendNodes(self, nodes) -> None:
        writer = ZCodex2Writer.ZCodex2Writer()
        buffer = _BytesSink()
        if not writer.write(buffer, nodes):
            self._showError(writer.getInformation() or "Could not create the print file.")
            return
        job_name = CuraApplication.getInstance().getPrintInformation().jobName or "cura"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_name)[:40] or "cura"
        remote = "/{0}_{1}.zcodex2".format(safe, time.strftime("%Y%m%d-%H%M%S"))
        self._uploading = True
        message = Message(catalog.i18nc("@info:status", "Sending {0} to the printer").format(remote.lstrip("/")),
                          title="Zortrax", progress=0, dismissable=False, lifetime=0)
        message.show()
        threading.Thread(target=self._send, args=(buffer.getvalue(), remote, message), daemon=True).start()

    def _send(self, data: bytes, remote: str, message: Message) -> None:
        app = CuraApplication.getInstance()
        try:
            def progress(sent, total):
                app.callLater(message.setProgress, int(sent * 100 / max(total, 1)))
            with self._lock:
                lan.upload_bytes(self._client, data, remote, progress)
                self._wake_if_sleeping()
                try:
                    self._client.print_file(remote, forced=False)
                except lan.PrinterError as e:
                    info = re.search(r'"startPrintAdditionalInfo"\s*:\s*"?(\d+)', str(e))
                    reason = lan.describe_start_info(info.group(1)) if info else ""
                    raise lan.PrinterError("The printer refused to start: " + (reason or str(e)))
            app.callLater(self._sendDone, message, None)
        except Exception as e:
            Logger.logException("w", "Zortrax send failed")
            app.callLater(self._sendDone, message, str(e))

    def _sendDone(self, message: Message, error: Optional[str]) -> None:
        self._uploading = False
        message.hide()
        if error:
            self._showError(error)
        else:
            Message(catalog.i18nc("@info", "Print started on the Zortrax printer."), title="Zortrax",
                    message_type=Message.MessageType.POSITIVE).show()
            self._update()
            self.refreshFiles()


def _print_files(entries) -> list:
    """Printable files from an FTP listing, newest first."""
    out = []
    for e in entries:
        name = e.get("name") or (e.get("listing", "").split()[-1] if e.get("listing") else "")
        if e.get("type") in ("dir", "cdir", "pdir") or not name.lower().endswith((".zcodex", ".zcodex2")):
            continue
        modify = str(e.get("modify", ""))
        when = "{0}-{1}-{2} {3}:{4}".format(modify[0:4], modify[4:6], modify[6:8], modify[8:10], modify[10:12]) if len(modify) >= 12 else ""
        try:
            n = int(e.get("size") or 0)
            size = "{0:.1f} MB".format(n / 1e6) if n >= 1e6 else ("{0} KB".format(max(1, round(n / 1e3))) if n else "")
        except ValueError:
            size = ""
        out.append({"name": name, "size": size, "modified": when, "sort": modify})
    out.sort(key=lambda f: f["sort"], reverse=True)
    return out


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _active_material_name() -> str:
    stack = CuraApplication.getInstance().getGlobalContainerStack()
    if stack is None or not stack.extruderList:
        return ""
    material = stack.extruderList[0].material
    return material.getMetaDataEntry("color_name") or material.getName() if material else ""


def _zortrax_material(name: str) -> Optional[dict]:
    """Metadata of the Zortrax material file whose name matches the printer's material name."""
    registry = CuraApplication.getInstance().getContainerRegistry()
    for meta in registry.findInstanceContainersMetadata(type="material", brand="Zortrax"):
        if _norm(meta.get("name", "")) == _norm(name) and meta.get("id") == meta.get("base_file"):
            return meta
    return None


class _BytesSink:
    """Minimal binary stream for MeshWriter.write()."""
    def __init__(self):
        self._parts = []

    def write(self, data):
        self._parts.append(bytes(data))

    def getvalue(self) -> bytes:
        return b"".join(self._parts)


from PyQt6.QtQuick import QQuickImageProvider  # noqa: E402


class ZortraxCameraProvider(QQuickImageProvider):
    _instance = None

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._images = {}

    @classmethod
    def instance(cls) -> "ZortraxCameraProvider":
        if cls._instance is None:
            cls._instance = ZortraxCameraProvider()
        return cls._instance

    def setImage(self, host: str, image: QImage) -> None:
        self._images[host] = image

    def requestImage(self, image_id, requested_size):
        host = image_id.split("?", 1)[0]
        image = self._images.get(host, QImage(640, 480, QImage.Format.Format_RGB32))
        return image, image.size()
