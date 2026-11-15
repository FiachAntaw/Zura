"""Zortrax printer models: discovery hardware byte -> Cura machine definition."""
from typing import Optional

# Ranges follow Z-Suite's HardwareVersion -> PrinterModel mapping.
_RANGES = [
    (24, 40, "zortrax_m200_plus", "Zortrax M200 Plus"),
    (50, 60, "zortrax_m300_plus", "Zortrax M300 Plus"),
]
# The M300 Dual (hardware 60-69) is left out: it needs dual-extrusion support that Zura doesn't have yet,
# so it isn't offered in the Add printer list.


def model_for_hardware(hardware) -> Optional[tuple]:
    """(definition_id, display name) for a hardware byte, or None for printers Cura can't drive."""
    try:
        h = int(hardware)
    except (TypeError, ValueError):
        return None
    for lo, hi, definition, name in _RANGES:
        if lo <= h < hi:
            return definition, name
    return None


def name_for_definition(definition_id: str) -> str:
    for _, _, d, name in _RANGES:
        if d == definition_id:
            return name
    return "Zortrax"
