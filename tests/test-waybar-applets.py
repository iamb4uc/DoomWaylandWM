#!/usr/bin/env python3
"""Check the battery data used by the Waybar popup without opening a display."""

import importlib.util
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import datetime
from threading import Event
from types import MethodType, SimpleNamespace
import time
import subprocess


script = Path(__file__).resolve().parents[1] / ".local/bin/waybar-applets.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("waybar_applets", script)
applets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(applets)
assert applets.NM is None
assert applets.night_light is None
launcher = script.parent / "waybar-applet"
for arguments in (("unknown", "HDMI-A-1"), ("calendar", "HDMI-A-1');invalid"), ()):
    result = subprocess.run([str(launcher), *arguments], capture_output=True, timeout=2)
    assert result.returncode == 2

import wayland_night_light as night_light
with TemporaryDirectory() as directory:
    root = Path(directory)
    config = root / "config.ini"
    config.write_text("[general]\ntemp-day=6500\ntemp-night=4200\ndusk-time=20:00\ndawn-time=05:00\nfade=0\nadjustment-method=wayland\n")
    disabled = root / "disabled"
    with patch.object(night_light, "CONFIG", config), patch.object(night_light, "STATE", root), \
            patch.object(night_light, "DISABLED", disabled), patch.object(night_light, "running", return_value=True), \
            patch.object(night_light, "notify_bar"):
        for hour, minute, expected in ((4, 59, "active"), (5, 0, "day"),
                                       (19, 59, "day"), (20, 0, "active"), (0, 0, "active")):
            with patch.object(night_light, "datetime") as clock:
                clock.now.return_value = datetime(2026, 10, 5, hour, minute)
                assert night_light.status()[1] == expected
        with patch.object(night_light, "stop") as stop, patch.object(night_light, "start") as start:
            night_light.set_enabled(False)
            assert disabled.exists()
            stop.assert_called_once()
            night_light.save_settings(6500, 3800, "21:30", "06:15")
            start.assert_not_called()
            assert night_light.settings()["general"]["temp-night"] == "3800"
            assert night_light.settings()["general"]["dusk-time"] == "21:30"
            assert night_light.settings()["general"]["dawn-time"] == "06:15"
            assert night_light.status()[1] == "disabled"
            before = config.read_text()
            try:
                night_light.save_settings(6500, 999, "20:00", "05:00")
            except ValueError:
                pass
            else:
                raise AssertionError("Out-of-range temperature accepted")
            assert config.read_text() == before
            for dusk, dawn in (("24:00", "05:00"), ("20:60", "05:00"),
                               ("8:00", "05:00"), ("20:00", "20:00"), ("08:00", "17:00")):
                try:
                    night_light.save_settings(6500, 3800, dusk, dawn)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid schedule accepted")
                assert config.read_text() == before
            night_light.set_enabled(True)
            assert not disabled.exists()
            start.assert_called_once()
            for hour, minute, expected in ((6, 14, "active"), (6, 15, "day"),
                                           (21, 29, "day"), (21, 30, "active")):
                with patch.object(night_light, "datetime") as clock:
                    clock.now.return_value = datetime(2026, 10, 5, hour, minute)
                    assert night_light.status()[1] == expected
            night_light.save_settings(6500, 4200, "20:00", "05:00")
            assert start.call_count == 2
            before = config.read_text()
            stop.reset_mock()
            night_light.save_settings(6500, 4200, "20:00", "05:00")
            stop.assert_not_called()
            assert config.read_text() == before
        disabled.touch()
        with patch.object(night_light, "running", side_effect=AssertionError("Disabled startup launched")):
            night_light.start()
print("night light settings, schedule and persistence checks passed")

state = SimpleNamespace(generation=0, executor=None, jobs={}, volume_timer=None)
state.run_background = MethodType(applets.Applets.run_background, state)
state.set_volume = MethodType(applets.Applets.set_volume, state)
entered, release = Event(), Event()
calls = []


def slow_volume(*args):
    calls.append(int(args[-1]))
    entered.set()
    assert release.wait(2)


def drain(predicate):
    deadline = time.monotonic() + 3
    context = applets.GLib.MainContext.default()
    while not predicate():
        assert time.monotonic() < deadline, "Background operation stalled"
        context.iteration(False)
        time.sleep(0.001)


try:
    with patch.object(applets, "command_output", side_effect=slow_volume):
        state.set_volume(10)
        assert entered.wait(1)
        state.set_volume(20)
        state.set_volume(30)
        assert len(state.jobs) == 1
        release.set()
        drain(lambda: not state.jobs)
        assert calls == [10, 30]
    entered.clear()
    release.clear()
    delivered = []

    def slow_read():
        entered.set()
        assert release.wait(2)
        return "stale"

    state.run_background("read", slow_read, lambda value, error: delivered.append(value))
    assert entered.wait(1)
    state.generation += 1
    release.set()
    drain(lambda: not state.jobs)
    assert delivered == []

    def failing_read():
        raise ValueError("Device unavailable")

    state.run_background("read", failing_read, lambda value, error: delivered.append(error))
    drain(lambda: not state.jobs)
    assert isinstance(delivered[0], ValueError)
finally:
    release.set()
    if state.executor:
        state.executor.shutdown(wait=True, cancel_futures=True)
print("background delivery, error reporting and slider coalescing checks passed")

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


flags = getattr(applets.load_nm(), "80211ApSecurityFlags")
privacy = getattr(applets.NM, "80211ApFlags").PRIVACY
assert applets.security_type(AccessPoint()) == "open"
assert applets.security_type(AccessPoint(privacy)) == "enterprise"
assert applets.security_type(AccessPoint(privacy, flags.KEY_MGMT_PSK)) == "psk"
assert applets.security_type(AccessPoint(privacy, rsn=flags.KEY_MGMT_SAE)) == "sae"
print("waybar applet Wi-Fi security checks passed")
