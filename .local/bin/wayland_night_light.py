#!/usr/bin/env python3

import configparser
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime

CONFIG = Path.home() / ".config/gammastep/config.ini"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "wayland"
DISABLED = STATE / "night-light-disabled"


def settings():
    config = configparser.ConfigParser()
    with CONFIG.open() as source:
        config.read_file(source)
    return config


def running():
    result = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "gammastep"],
                            capture_output=True, text=True, timeout=2)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "Cannot check Gammastep")
    return result.returncode == 0


def start():
    if DISABLED.exists() or running():
        return
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "gammastep.log").open("ab") as log:
        process = subprocess.Popen(["gammastep", "-v", "-c", str(CONFIG)],
                                   stdout=log, stderr=log, start_new_session=True)
    time.sleep(0.2)
    if process.poll() is not None:
        raise RuntimeError(f"Gammastep failed; see {STATE / 'gammastep.log'}")


def stop():
    result = subprocess.run(["pkill", "-TERM", "-u", str(os.getuid()), "-x", "gammastep"],
                            capture_output=True, text=True, timeout=2)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "Cannot stop Gammastep")
    for _ in range(50):
        if not running():
            return
        time.sleep(0.1)
    raise RuntimeError("Gammastep did not stop")


def set_enabled(enabled):
    STATE.mkdir(parents=True, exist_ok=True)
    if enabled:
        start_was_disabled = DISABLED.exists()
        DISABLED.unlink(missing_ok=True)
        try:
            start()
        except (OSError, RuntimeError, subprocess.SubprocessError):
            if start_was_disabled:
                DISABLED.touch()
            raise
    else:
        stop()
        DISABLED.touch()
    notify_bar()


def notify_bar():
    subprocess.run(["pkill", "-RTMIN+9", "-u", str(os.getuid()), "-x", "waybar"],
                   capture_output=True, timeout=2)


def save_settings(day, night, dusk, dawn):
    if not all(isinstance(value, int) and 1000 <= value <= 10000 for value in (day, night)):
        raise ValueError("Temperatures must be between 1000K and 10000K")
    if not all(isinstance(value, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value)
               for value in (dusk, dawn)):
        raise ValueError("Use 24-hour times in HH:MM format")
    if dusk <= dawn:
        raise ValueError("Start must be later than end for an overnight schedule")
    config = settings()
    values = {"temp-day": str(day), "temp-night": str(night), "dusk-time": dusk, "dawn-time": dawn}
    if all(config["general"][key] == value for key, value in values.items()):
        start()
        notify_bar()
        return
    config["general"].update(values)
    import io
    import tempfile
    buffer = io.StringIO()
    config.write(buffer, space_around_delimiters=False)
    target = CONFIG.resolve()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as source:
            temporary = Path(source.name)
            source.write(buffer.getvalue())
        subprocess.run(["gammastep", "-p", "-c", str(temporary)], check=True,
                       capture_output=True, text=True, timeout=3)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if not DISABLED.exists():
        stop()
        start()
    notify_bar()


def status(general=None):
    general = settings()["general"] if general is None else general
    if DISABLED.exists():
        return "Disabled", "disabled"
    if not running():
        return "Not running", "error"
    now = datetime.now().strftime("%H:%M")
    dusk, dawn = general["dusk-time"], general["dawn-time"]
    warm = now >= dusk or now < dawn if dusk > dawn else dusk <= now < dawn
    temperature = general["temp-night" if warm else "temp-day"]
    return f"{'Warming' if warm else 'Daytime'} · {temperature}K", "active" if warm else "day"


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["start"]:
            start()
        elif sys.argv[1:] == ["bar"]:
            general = settings()["general"]
            label, state = status(general)
            print(json.dumps({"text": "󰖔", "class": state,
                              "tooltip": f"Night light: {label}\n{general['dusk-time']}–{general['dawn-time']} local time\nClick to configure"}))
        else:
            raise ValueError("usage: wayland_night_light.py start|bar")
    except (OSError, ValueError, KeyError, configparser.Error, RuntimeError, subprocess.SubprocessError) as error:
        print(f"night light: {error}", file=sys.stderr)
        sys.exit(1)
