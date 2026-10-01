#!/usr/bin/env python3
"""Check the battery data used by the Waybar popup without opening a display."""

import importlib.util
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


script = Path(__file__).resolve().parents[1] / ".local/bin/waybar-applets.py"
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("waybar_applets", script)
applets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(applets)

assert applets.shifted_month(2026, 12, 1) == (2027, 1)
assert applets.shifted_month(2026, 1, -1) == (2025, 12)


def write(root, device, name, value):
    path = root / device
    path.mkdir(exist_ok=True)
    (path / name).write_text(str(value))


with TemporaryDirectory() as directory:
    root = Path(directory)
    assert applets.battery_details(root) is None
    write(root, "BAT0", "type", "Battery")
    write(root, "BAT0", "status", "Discharging")
    write(root, "BAT0", "capacity", 80)
    write(root, "BAT0", "energy_now", 40000000)
    write(root, "BAT0", "energy_full", 50000000)
    write(root, "BAT0", "power_now", 10000000)
    write(root, "AC", "type", "Mains")
    write(root, "AC", "online", 0)
    assert applets.battery_details(root) == {
        "percent": 80, "state": "Discharging", "minutes": 240, "plugged": False
    }
    write(root, "BAT0", "status", "Charging")
    write(root, "AC", "online", 1)
    assert applets.battery_details(root)["minutes"] == 60
    assert applets.battery_details(root)["plugged"] is True
    write(root, "BAT0", "power_now", 0)
    assert applets.battery_details(root)["minutes"] is None
    write(root, "BAT0", "scope", "Device")
    assert applets.battery_details(root) is None

print("waybar applet battery checks passed")


class AccessPoint:
    def __init__(self, privacy=0, wpa=0, rsn=0):
        self.privacy, self.wpa, self.rsn = privacy, wpa, rsn

    def get_flags(self):
        return self.privacy

    def get_wpa_flags(self):
        return self.wpa

    def get_rsn_flags(self):
        return self.rsn


flags = getattr(applets.NM, "80211ApSecurityFlags")
privacy = getattr(applets.NM, "80211ApFlags").PRIVACY
assert applets.security_type(AccessPoint()) == "open"
assert applets.security_type(AccessPoint(privacy)) == "enterprise"
assert applets.security_type(AccessPoint(privacy, flags.KEY_MGMT_PSK)) == "psk"
assert applets.security_type(AccessPoint(privacy, rsn=flags.KEY_MGMT_SAE)) == "sae"
print("waybar applet Wi-Fi security checks passed")
