import os

from UM.MimeTypeDatabase import MimeType, MimeTypeDatabase
from UM.Resources import Resources

from . import ZCodex2Writer

_network_plugin = []  # set in register(); used by the connect action

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

MimeTypeDatabase.addMimeType(MimeType(
    name="application/x-zortrax-zcodex2",
    comment="Zortrax ZCodex2",
    suffixes=["zcodex2"],
))

MimeTypeDatabase.addMimeType(MimeType(
    name="application/x-zortrax-zcode",
    comment="Zortrax ZCode (M200/M300)",
    suffixes=["zcode"],
))

# Make our machine definitions, materials and quality profiles visible to Cura.
Resources.addSearchPath(os.path.join(PLUGIN_DIR, "resources"))


def getMetaData():
    return {
        "mesh_writer": {
            "output": [{
                "extension": "zcodex2",
                "description": "Zortrax ZCodex2 file",
                "mime_type": "application/x-zortrax-zcodex2",
                "mode": ZCodex2Writer.ZCodex2Writer.OutputMode.BinaryMode,
            }, {
                "extension": "zcode",
                "description": "Zortrax ZCode file (M200/M300)",
                "mime_type": "application/x-zortrax-zcode",
                "mode": ZCodex2Writer.ZCodex2Writer.OutputMode.BinaryMode,
            }]
        }
    }


def register(app):
    from .ZortraxOutputDevicePlugin import ZortraxOutputDevicePlugin
    from .ZortraxConnectAction import ZortraxConnectAction
    network = ZortraxOutputDevicePlugin()
    _network_plugin[:] = [network]
    return {
        "mesh_writer": ZCodex2Writer.ZCodex2Writer(),
        "output_device": network,
        "machine_action": ZortraxConnectAction(),
    }
