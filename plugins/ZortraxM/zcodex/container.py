"""Read and write the .zcodex2 container: header JSON, preview image, ZIP entries."""
import io, json, struct, time, uuid, zipfile
from collections import OrderedDict

ENTRY_ORDER = ("AdditionalMetadata", "ZCodeData", "ConfigurationData", "UserSettingsData")

def _dumps(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def make_header(*, printer_name="M200 Plus", printer_model_id=24, min_firmware="2.6.0",
                software_version="3.7.0.0", materials, bed_temperature, chamber_temperature=-1,
                command_count, print_time_s, nozzle_diameter, bbox, layer_thickness,
                total_layers) -> "OrderedDict":
    return OrderedDict([
        ("PrintId", str(uuid.uuid4()).upper()),
        ("ZCodexVersion", "2.0.0.0"),
        ("SoftwareVersion", software_version),
        ("MinFirmwareVersion", min_firmware),
        ("PrinterModelEnumId", printer_model_id),
        ("PrinterName", printer_name),
        ("Materials", materials),
        ("HeatbedTemperature", bed_temperature),
        ("ChamberTemperature", chamber_temperature),
        ("CommandCount", command_count),
        ("PrintTime", int(print_time_s)),
        ("NozzleDiameter", nozzle_diameter),
        ("PrintBoundingBox", OrderedDict(zip(("MinX", "MinY", "MinZ", "MaxX", "MaxY", "MaxZ"), bbox))),
        ("Guid", None),
        ("LayerThickness", layer_thickness),
        ("TotalMaterialVolumeUsed", 0.0),
        ("TotalMaterialWeightUsed", 0.0),
        ("TotalLayersCount", total_layers),
        ("Timestamp", time.strftime("%Y%m%d%H%M%S") + "0000"),
        ("ResinMetadata", None),
    ])

def write(fp, header: dict, entries: dict, image: bytes = b"") -> None:
    """Write a complete .zcodex2 to a binary file object."""
    meta = _dumps(header)
    fp.write(struct.pack("<I", len(meta)) + meta + struct.pack("<I", len(image)) + image)
    stamp = time.localtime()[:6]
    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ENTRY_ORDER:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            z.writestr(info, entries[name])

def to_bytes(header: dict, entries: dict, image: bytes = b"") -> bytes:
    buf = io.BytesIO()
    write(buf, header, entries, image)
    return buf.getvalue()

def read(data: bytes):
    """Return (header, image, {entry: bytes})."""
    n = struct.unpack_from("<I", data, 0)[0]
    header = json.loads(data[4:4 + n])
    m = struct.unpack_from("<I", data, 4 + n)[0]
    image = data[8 + n:8 + n + m]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = {i.filename: z.read(i) for i in z.infolist()}
    return header, image, entries
