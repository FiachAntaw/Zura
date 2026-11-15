import os

from UM.MimeTypeDatabase import MimeType, MimeTypeDatabase
from UM.Resources import Resources

from . import ZCodex2Writer

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

MimeTypeDatabase.addMimeType(MimeType(
    name="application/x-zortrax-zcodex2",
    comment="Zortrax ZCodex2",
    suffixes=["zcodex2"],
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
            }]
        }
    }


def register(app):
    return {"mesh_writer": ZCodex2Writer.ZCodex2Writer()}
