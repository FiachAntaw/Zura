from io import StringIO
from typing import cast

from UM.Logger import Logger
from UM.Mesh.MeshWriter import MeshWriter
from UM.PluginRegistry import PluginRegistry
from UM.i18n import i18nCatalog

from cura.CuraApplication import CuraApplication

from .zcodex import writer as zwriter

catalog = i18nCatalog("cura")


def _material_name(material_id: str) -> str:
    for name in zwriter.MATERIAL_IDS:
        if "zortrax_" + name.lower().replace(" ", "_").replace("-", "_") == material_id:
            return name
    return "Z-ABS"


def _preview_png() -> bytes:
    """Cura's post-slice snapshot, fitted onto a 320x180 PNG like Z-Suite's previews; b"" if unavailable."""
    try:
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PyQt6.QtGui import QColor, QImage, QPainter
        backend = CuraApplication.getInstance().getBackend()
        snapshot = backend.getLatestSnapshot() if hasattr(backend, "getLatestSnapshot") else None
        if snapshot is None or snapshot.isNull():
            return b""
        w, h = zwriter.PREVIEW_SIZE
        canvas = QImage(w, h, QImage.Format.Format_ARGB32)
        canvas.fill(QColor(0, 0, 0, 0))
        scaled = snapshot.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(canvas)
        painter.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
        painter.end()
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        canvas.save(buf, "PNG")
        return bytes(data.data())
    except Exception:
        Logger.logException("w", "Could not create the preview image")
        return b""


class ZCodex2Writer(MeshWriter):
    """Writes Cura's sliced G-code as a Zortrax .zcodex2 file."""

    def __init__(self) -> None:
        super().__init__(add_to_recent_files=False)

    def write(self, stream, nodes, mode=MeshWriter.OutputMode.BinaryMode) -> bool:
        if mode != MeshWriter.OutputMode.BinaryMode:
            self.setInformation(catalog.i18nc("@error", "ZCodex2 writer only supports binary mode."))
            return False
        gcode = StringIO()
        gcode_writer = cast(MeshWriter, PluginRegistry.getInstance().getPluginObject("GCodeWriter"))
        if not gcode_writer.write(gcode, None):
            self.setInformation(gcode_writer.getInformation())
            return False

        stack = CuraApplication.getInstance().getGlobalContainerStack()
        extruder = stack.extruderList[0]
        material = _material_name(extruder.material.getMetaDataEntry("base_file", extruder.material.getId()))
        definition = stack.definition
        quality_type = stack.quality.getMetaDataEntry("quality_type", "") or ""
        try:
            data = zwriter.build(
                gcode.getvalue().splitlines(),
                material=material,
                layer_mm=float(stack.getProperty("layer_height", "value")),
                quality=("Draft" if quality_type.endswith("_draft")
                         else "Normal" if quality_type.endswith("_normal") else "High"),
                nozzle_mm=float(extruder.getProperty("machine_nozzle_size", "value")),
                raft=stack.getProperty("adhesion_type", "value") == "raft",
                printer_name=str(definition.getMetaDataEntry("zortrax_printer_name", "M200 Plus")),
                printer_model_id=int(definition.getMetaDataEntry("zortrax_printer_model_id", 24)),
                min_firmware=str(definition.getMetaDataEntry("zortrax_min_firmware", "2.6.0")),
                max_z_mm=float(stack.getProperty("machine_height", "value")),
                preview_png=_preview_png(),
            )
        except Exception as e:
            Logger.logException("e", "Failed to build zcodex2")
            self.setInformation(catalog.i18nc("@error", "Could not create the ZCodex2 file: {0}").format(e))
            return False
        stream.write(data)
        return True
