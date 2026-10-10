#!/usr/bin/env python3
"""Small Waybar controls for the existing brightness, network, and battery modules."""

import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, GtkLayerShell

NM = None
night_light = None


def load_nm():
    global NM
    if NM is None:
        gi.require_version("NM", "1.0")
        from gi.repository import NM as module
        NM = module
    return NM


APP_ID = "io.github.iamb4uc.WaybarApplets"
STYLE = Path.home() / ".config/waybar/applets.css"
POWER_SUPPLY = Path("/sys/class/power_supply")
KINDS = ("brightness", "wifi", "battery", "volume", "bluetooth", "calendar",
         "weather", "notifications", "night-light")


def read_number(path):
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_text(path, default=""):
    try:
        return path.read_text().strip()
    except OSError:
        return default


def command_output(*args, timeout=3):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def battery_details(root=POWER_SUPPLY):
    batteries = [
        path for path in root.iterdir()
        if read_text(path / "type") == "Battery"
        and read_text(path / "scope") != "Device"
    ] if root.exists() else []
    if not batteries:
        return None
    battery = next((path for path in batteries if path.name.startswith("BAT")), batteries[0])
    state = read_text(battery / "status", "Unknown")
    percent = read_number(battery / "capacity")
    energy = read_number(battery / "energy_now")
    full = read_number(battery / "energy_full")
    power = read_number(battery / "power_now")
    estimate = None
    if energy is not None and full is not None and power and power > 0:
        remaining = max(0, full - energy) if state == "Charging" else energy
        estimate = round(remaining / power * 60)
    mains = [
        path for path in root.iterdir()
        if path != battery and read_text(path / "type") == "Mains"
    ]
    plugged = any(read_number(path / "online") == 1 for path in mains)
    return {"percent": percent, "state": state, "minutes": estimate, "plugged": plugged}


def security_type(ap):
    load_nm()
    flags = int(ap.get_wpa_flags()) | int(ap.get_rsn_flags())
    keys = getattr(NM, "80211ApSecurityFlags")
    if flags & int(keys.KEY_MGMT_PSK):
        return "psk"
    if flags & int(keys.KEY_MGMT_SAE):
        return "sae"
    if flags or int(ap.get_flags()) & int(getattr(NM, "80211ApFlags").PRIVACY):
        return "enterprise"
    return "open"


def ssid_bytes(ap):
    ssid = ap.get_ssid()
    return bytes(ssid.get_data()) if ssid else b""


def ssid_name(ap):
    load_nm()
    raw = ssid_bytes(ap)
    return NM.utils_ssid_to_utf8(raw) if raw else "Hidden network"


def format_minutes(minutes):
    if minutes is None:
        return "Time unavailable"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m"


def shifted_month(year, month, offset):
    year, month_zero = divmod(year * 12 + month - 1 + offset, 12)
    return year, month_zero + 1


class Applets(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.kind = None
        self.output = None
        self.windows = []
        self.nm_client = None
        self.wifi_device = None
        self.brightness_timer = None
        self.volume_timer = None
        self.generation = 0
        self.executor = None
        self.jobs = {}
        self.sources = []
        self.wifi_signals = []
        self.weather_process = None
        self.cancellable = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        action = Gio.SimpleAction.new("open", GLib.VariantType.new("(ss)"))
        action.connect("activate", lambda _action, parameter: self.request_applet(*parameter.unpack()))
        self.add_action(action)
        css = Gtk.CssProvider()
        css.load_from_path(str(STYLE))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        pass

    def do_shutdown(self):
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
        Gtk.Application.do_shutdown(self)

    def run_background(self, name, work, finished):
        token = (self.generation, name)
        if token in self.jobs:
            return False
        if self.executor is None:
            from concurrent.futures import ThreadPoolExecutor
            self.executor = ThreadPoolExecutor(max_workers=1)
        future = self.executor.submit(work)
        self.jobs[token] = future

        def deliver():
            self.jobs.pop(token, None)
            if token[0] != self.generation:
                return False
            try:
                value, error = future.result(), None
            except Exception as failure:
                value, error = None, failure
            finished(value, error)
            return False

        future.add_done_callback(lambda _future: GLib.idle_add(deliver))
        return True

    def do_command_line(self, command_line):
        args = command_line.get_arguments()
        if len(args) != 3 or args[1] not in KINDS:
            print("usage: waybar-applets.py KIND OUTPUT", file=sys.stderr)
            if self.kind is None:
                self.quit()
            return 2
        return self.request_applet(args[1], args[2])

    def request_applet(self, kind, output):
        if kind not in KINDS:
            return 2
        if self.kind == kind and self.output == output:
            self.dismiss()
            return 0
        try:
            self.open_applet(kind, output)
        except (OSError, ValueError, GLib.Error, subprocess.SubprocessError) as error:
            print(f"waybar-applets: {error}", file=sys.stderr)
            self.dismiss()
            return 1
        return 0

    def monitor_for_output(self, output):
        result = subprocess.run(
            ["swaymsg", "-t", "get_outputs", "-r"],
            check=True, capture_output=True, text=True, timeout=3,
        )
        matches = [item for item in json.loads(result.stdout)
                   if item["name"] == output and item["active"]]
        if not matches:
            raise ValueError(f"output {output} is unavailable")
        rect = matches[0]["rect"]
        display = Gdk.Display.get_default()
        for index in range(display.get_n_monitors()):
            monitor = display.get_monitor(index)
            geometry = monitor.get_geometry()
            if (geometry.x, geometry.y, geometry.width, geometry.height) == (
                rect["x"], rect["y"], rect["width"], rect["height"]
            ):
                return monitor
        raise ValueError(f"could not locate GTK monitor for {output}")

    def new_layer_window(self, monitor, layer, name, keyboard):
        window = Gtk.Window()
        self.add_window(window)
        window.set_decorated(False)
        window.set_app_paintable(True)
        visual = window.get_screen().get_rgba_visual()
        if visual:
            window.set_visual(visual)
        window.set_name(name)
        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_monitor(window, monitor)
        GtkLayerShell.set_layer(window, layer)
        GtkLayerShell.set_keyboard_mode(window, keyboard)
        GtkLayerShell.set_exclusive_zone(window, 0)
        self.windows.append(window)
        return window

    def open_applet(self, kind, output):
        self.dismiss(quit_app=False)
        self.cancellable = Gio.Cancellable()
        monitor = self.monitor_for_output(output)
        self.kind, self.output = kind, output
        display = Gdk.Display.get_default()
        for index in range(display.get_n_monitors()):
            screen = display.get_monitor(index)
            geometry = screen.get_geometry()
            catcher = self.new_layer_window(
                screen, GtkLayerShell.Layer.TOP, "applet-catcher",
                GtkLayerShell.KeyboardMode.NONE,
            )
            for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                         GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(catcher, edge, True)
            catcher.set_default_size(geometry.width, geometry.height)
            backdrop = Gtk.EventBox()
            backdrop.set_visible_window(False)
            backdrop.set_hexpand(True)
            backdrop.set_vexpand(True)
            backdrop.connect("button-press-event", lambda *_: self.dismiss())
            catcher.add(backdrop)
            catcher.show_all()

        panel = self.new_layer_window(
            monitor, GtkLayerShell.Layer.OVERLAY, "applet-window",
            GtkLayerShell.KeyboardMode.ON_DEMAND,
        )
        GtkLayerShell.set_anchor(panel, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(panel, GtkLayerShell.Edge.TOP, 8)
        panel_width = 340 if kind == "calendar" else 420 if kind in ("weather", "notifications") else 320
        if kind in ("calendar", "weather"):
            GtkLayerShell.set_anchor(panel, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_margin(
                panel, GtkLayerShell.Edge.LEFT,
                max(0, (monitor.get_geometry().width - panel_width) // 2),
            )
        else:
            GtkLayerShell.set_anchor(panel, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(panel, GtkLayerShell.Edge.RIGHT, 42)
        panel.set_size_request(panel_width, -1)
        panel.connect("key-press-event", self.on_key_press)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_name("applet-panel")
        self.content = content
        self.password_box = None
        panel.add(content)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label={"brightness": "Brightness", "wifi": "Wi-Fi",
                                 "battery": "Battery", "volume": "Volume",
                                 "bluetooth": "Bluetooth", "calendar": "Calendar",
                                 "weather": "Weather", "notifications": "Notifications",
                                 "night-light": "Night light"}[kind],
                          xalign=0)
        title.get_style_context().add_class("applet-title")
        header.pack_start(title, True, True, 0)
        close = Gtk.Button(label="×")
        close.get_style_context().add_class("applet-close")
        close.connect("clicked", lambda *_: self.dismiss())
        header.pack_end(close, False, False, 0)
        content.pack_start(header, False, False, 0)
        if kind == "brightness":
            self.build_brightness(content)
        elif kind == "battery":
            self.build_battery(content)
        elif kind == "wifi":
            self.build_wifi(content)
        elif kind == "volume":
            self.build_volume(content)
        elif kind == "bluetooth":
            self.build_bluetooth(content)
        elif kind == "calendar":
            self.build_calendar(content)
        elif kind == "weather":
            self.build_weather(content)
        elif kind == "night-light":
            self.build_night_light(content)
        else:
            self.build_notifications(content)
        panel.show_all()

    def dismiss(self, quit_app=True):
        self.generation += 1
        for future in list(self.jobs.values()):
            future.cancel()
        if self.cancellable:
            self.cancellable.cancel()
            self.cancellable = None
        for source in self.sources:
            GLib.source_remove(source)
        self.sources.clear()
        for obj, handler in self.wifi_signals:
            if GObject.signal_handler_is_connected(obj, handler):
                GObject.signal_handler_disconnect(obj, handler)
        self.wifi_signals.clear()
        if self.weather_process:
            self.weather_process.force_exit()
            self.weather_process = None
        if self.brightness_timer:
            GLib.source_remove(self.brightness_timer)
            self.brightness_timer = None
        if self.volume_timer:
            GLib.source_remove(self.volume_timer)
            self.volume_timer = None
        for window in reversed(self.windows):
            window.destroy()
        self.windows.clear()
        self.kind = self.output = None
        self.wifi_device = None
        self.password_box = None
        if quit_app:
            self.quit()

    def on_key_press(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.dismiss()
            return True
        return False

    def build_night_light(self, content):
        global night_light
        if night_light is None:
            import wayland_night_light as night_light
        general = night_light.settings()["general"]
        self.night_light_status = Gtk.Label(xalign=0)
        content.pack_start(self.night_light_status, False, False, 0)
        self.night_light_schedule = Gtk.Label(xalign=0)
        content.pack_start(self.night_light_schedule, False, False, 0)
        self.night_light_toggle = Gtk.Button()
        self.night_light_toggle.connect("clicked", self.toggle_night_light)
        content.pack_start(self.night_light_toggle, False, False, 0)
        self.night_light_temperatures = {}
        for key, title in (("temp-night", "Night temperature"), ("temp-day", "Day temperature")):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
            control = Gtk.SpinButton.new_with_range(1000, 10000, 100)
            control.set_value(int(general[key]))
            control.set_tooltip_text("Kelvin: lower is warmer; 6500K is neutral")
            row.pack_end(control, False, False, 0)
            self.night_light_temperatures[key] = control
            content.pack_start(row, False, False, 0)
        content.pack_start(Gtk.Label(label="Lower K = warmer · 6500K = neutral", xalign=0), False, False, 0)
        self.night_light_times = {}
        for key, title in (("dusk-time", "Start time"), ("dawn-time", "End time")):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
            entry = Gtk.Entry()
            entry.set_width_chars(5)
            entry.set_max_length(5)
            entry.set_text(general[key])
            entry.set_placeholder_text("HH:MM")
            entry.set_tooltip_text("24-hour local time; start must be later than end")
            entry.connect("activate", self.apply_night_light)
            self.night_light_times[key] = entry
            row.pack_end(entry, False, False, 0)
            content.pack_start(row, False, False, 0)
        apply = Gtk.Button(label="Apply settings")
        self.night_light_apply = apply
        apply.connect("clicked", self.apply_night_light)
        content.pack_start(apply, False, False, 0)
        self.refresh_night_light()

    def refresh_night_light(self):
        general = night_light.settings()["general"]
        label, _state = night_light.status(general)
        self.night_light_schedule.set_text(f"{general['dusk-time']}–{general['dawn-time']} · local time")
        self.night_light_status.set_text(label)
        self.night_light_toggle.set_label("Enable night light" if night_light.DISABLED.exists()
                                         else "Disable night light")

    def toggle_night_light(self, _button):
        enabled = night_light.DISABLED.exists()
        self.night_light_change(lambda: night_light.set_enabled(enabled))

    def night_light_change(self, work):
        self.night_light_toggle.set_sensitive(False)
        self.night_light_apply.set_sensitive(False)
        self.night_light_status.set_text("Applying…")

        def finished(_value, error):
            self.night_light_toggle.set_sensitive(True)
            self.night_light_apply.set_sensitive(True)
            if error:
                self.night_light_status.set_text(f"Could not apply: {error}")
            else:
                self.refresh_night_light()

        self.run_background("night-light", work, finished)

    def apply_night_light(self, _button):
        try:
            for control in self.night_light_temperatures.values():
                control.update()
            values = (
                self.night_light_temperatures["temp-day"].get_value_as_int(),
                self.night_light_temperatures["temp-night"].get_value_as_int(),
                self.night_light_times["dusk-time"].get_text().strip(),
                self.night_light_times["dawn-time"].get_text().strip(),
            )
            self.night_light_change(lambda: night_light.save_settings(*values))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            self.night_light_status.set_text(f"Could not apply: {error}")

    def build_brightness(self, content):
        try:
            device = next(iter(sorted(Path("/sys/class/backlight").iterdir())))
            percent = round(int((device / "brightness").read_text()) * 100 /
                            int((device / "max_brightness").read_text()))
        except (OSError, ValueError, StopIteration, ZeroDivisionError):
            content.pack_start(Gtk.Label(label="Backlight unavailable"), False, False, 0)
            return
        value = Gtk.Label(label=f"{percent}%", xalign=0)
        content.pack_start(value, False, False, 0)
        slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        slider.set_draw_value(False)
        slider.set_value(max(1, percent))
        slider.connect("value-changed", self.on_brightness_changed, value)
        content.pack_start(slider, False, False, 0)

    def on_brightness_changed(self, slider, label):
        percent = int(slider.get_value())
        label.set_text(f"{percent}%")
        if self.brightness_timer:
            GLib.source_remove(self.brightness_timer)
        self.brightness_timer = GLib.timeout_add(40, self.set_brightness, percent)

    def set_brightness(self, percent):
        self.brightness_timer = None
        self.brightness_target = percent

        def finished(_value, error):
            if error:
                print(f"waybar-applets: brightness: {error}", file=sys.stderr)
            if self.brightness_target != percent:
                self.set_brightness(self.brightness_target)

        self.run_background("brightness-set", lambda: command_output(
            "brightnessctl", "-c", "backlight", "set", f"{percent}%"), finished)
        return False

    def build_battery(self, content):
        self.battery_rows = {}
        for key in ("Charge", "State", "Power", "Estimate"):
            row = Gtk.Label(xalign=0)
            row.get_style_context().add_class("applet-detail")
            content.pack_start(row, False, False, 0)
            self.battery_rows[key] = row
        self.update_battery()
        self.sources.append(GLib.timeout_add_seconds(15, self.update_battery))

    def update_battery(self):
        if self.kind != "battery":
            return False
        try:
            details = battery_details()
        except OSError:
            details = None
        if not details:
            self.battery_rows["Charge"].set_text("No system battery")
            for key in ("State", "Power", "Estimate"):
                self.battery_rows[key].set_text("")
            return True
        self.battery_rows["Charge"].set_text(
            f"Charge  {details['percent']}%" if details["percent"] is not None
            else "Charge  unavailable"
        )
        self.battery_rows["State"].set_text(f"State  {details['state']}")
        self.battery_rows["Power"].set_text(
            f"AC power  {'Connected' if details['plugged'] else 'Disconnected'}"
        )
        self.battery_rows["Estimate"].set_text(
            f"Estimate  {format_minutes(details['minutes'])}"
        )
        return True

    def build_volume(self, content):
        self.volume_status = Gtk.Label(xalign=0)
        self.volume_status.set_line_wrap(True)
        content.pack_start(self.volume_status, False, False, 0)
        self.volume_value = Gtk.Label(xalign=0)
        content.pack_start(self.volume_value, False, False, 0)
        self.volume_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.volume_slider.set_draw_value(False)
        content.pack_start(self.volume_slider, False, False, 0)
        self.volume_slider.connect("value-changed", self.on_volume_changed)
        self.volume_mute = Gtk.Button()
        self.volume_mute.connect("clicked", self.toggle_volume_mute)
        content.pack_start(self.volume_mute, False, False, 0)
        content.pack_start(Gtk.Label(label="Output devices", xalign=0), False, False, 0)
        self.volume_outputs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.pack_start(self.volume_outputs, False, False, 0)
        refresh = Gtk.Button(label="Refresh outputs")
        refresh.connect("clicked", lambda *_: self.refresh_volume())
        content.pack_start(refresh, False, False, 0)
        self.refresh_volume()

    def refresh_volume(self):
        if self.kind != "volume":
            return
        self.volume_status.set_text("Loading audio…")
        self.volume_slider.set_sensitive(False)
        self.volume_mute.set_sensitive(False)

        def read():
            default = command_output("pactl", "get-default-sink")
            sinks = json.loads(command_output("pactl", "--format=json", "list", "sinks"))
            sink = next(item for item in sinks if item["name"] == default)
            channels = list(sink["volume"].values())
            level = round(sum(channel["value"] for channel in channels) / len(channels) * 100 / 65536)
            return level, sink["mute"], default, sinks

        self.run_background("volume-read", read, self.show_volume)

    def show_volume(self, value, error):
        if error:
            self.volume_status.set_text(f"Audio unavailable: {error}")
            return
        level, muted, default, sinks = value
        self.volume_slider.set_sensitive(True)
        self.volume_mute.set_sensitive(True)
        self.volume_status.set_text("Default output")
        self.volume_value.set_text(f"{level}%{' · muted' if muted else ''}")
        self.volume_slider.handler_block_by_func(self.on_volume_changed)
        self.volume_slider.set_value(min(level, 150))
        self.volume_slider.handler_unblock_by_func(self.on_volume_changed)
        self.volume_mute.set_label("Unmute" if muted else "Mute")
        for child in self.volume_outputs.get_children():
            self.volume_outputs.remove(child)
        for sink in sinks:
            name = sink["name"]
            description = sink.get("description", name)
            button = Gtk.Button(label=f"{'✓ ' if name == default else ''}{description[:48]}")
            button.set_tooltip_text(description)
            button.connect("clicked", self.set_output_sink, name)
            self.volume_outputs.pack_start(button, False, False, 0)
        self.volume_outputs.show_all()

    def on_volume_changed(self, slider):
        level = int(slider.get_value())
        self.volume_value.set_text(f"{level}%")
        if self.volume_timer:
            GLib.source_remove(self.volume_timer)
        self.volume_timer = GLib.timeout_add(40, self.set_volume, level)

    def set_volume(self, level):
        self.volume_timer = None
        self.volume_target = level

        def finished(_value, error):
            if error:
                self.volume_status.set_text(f"Could not set volume: {error}")
            if self.volume_target != level:
                self.set_volume(self.volume_target)

        self.run_background("volume-set", lambda: command_output(
            "pamixer", "--allow-boost", "--set-volume", str(level)), finished)
        return False

    def toggle_volume_mute(self, _button):
        self.run_background("volume-mute", lambda: command_output("pamixer", "--toggle-mute"),
                            self.volume_action_finished)

    def volume_action_finished(self, _value, error):
        if error:
            self.volume_status.set_text(f"Could not change audio: {error}")
        else:
            self.refresh_volume()

    def set_output_sink(self, _button, name):
        def change():
            command_output("pactl", "set-default-sink", name)
            inputs = json.loads(command_output("pactl", "--format=json", "list", "sink-inputs"))
            for item in inputs:
                command_output("pactl", "move-sink-input", str(item["index"]), name)
        self.run_background("volume-output", change, self.volume_action_finished)

    def build_bluetooth(self, content):
        self.bt_busy = False
        self.bt_status = Gtk.Label(label="Loading Bluetooth…", xalign=0)
        self.bt_status.set_line_wrap(True)
        content.pack_start(self.bt_status, False, False, 0)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.bt_toggle = Gtk.Button()
        self.bt_toggle.set_sensitive(False)
        self.bt_toggle.connect("clicked", self.toggle_bluetooth)
        actions.pack_start(self.bt_toggle, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self.refresh_bluetooth())
        actions.pack_start(refresh, True, True, 0)
        content.pack_start(actions, False, False, 0)
        self.bt_devices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.pack_start(self.bt_devices, False, False, 0)
        pair = Gtk.Button(label="Pair a new device: bluetoothctl")
        pair.connect("clicked", self.open_bluetoothctl)
        content.pack_start(pair, False, False, 0)
        self.refresh_bluetooth()

    def refresh_bluetooth(self):
        if self.kind != "bluetooth":
            return
        cancellable = self.cancellable

        def read():
            from xml.etree import ElementTree
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, cancellable)

            def call(path, interface, method, parameters=None):
                return bus.call_sync("org.bluez", path, interface, method, parameters, None,
                                     Gio.DBusCallFlags.NONE, 3000, cancellable).unpack()[0]

            def children(path):
                xml = call(path, "org.freedesktop.DBus.Introspectable", "Introspect")
                return [f"{path}/{node.attrib['name']}" for node in ElementTree.fromstring(xml).findall("node")]

            adapters = [path for path in children("/org/bluez") if path.rsplit("/", 1)[1].startswith("hci")]
            if not adapters:
                raise ValueError("No Bluetooth adapter")
            adapter = adapters[0]

            def properties(path, interface):
                return call(path, "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (interface,)))

            devices = [(path, properties(path, "org.bluez.Device1")) for path in children(adapter)
                       if path.rsplit("/", 1)[1].startswith("dev_")]
            return bus, adapter, properties(adapter, "org.bluez.Adapter1"), devices

        self.run_background("bluetooth-read", read, self.show_bluetooth)

    def show_bluetooth(self, value, error):
        if error:
            self.bt_status.set_text(f"Bluetooth unavailable: {error}")
            return
        self.bluez_bus, self.bt_adapter, properties, devices = value
        powered = properties.get("Powered", False)
        self.bt_status.set_text("Bluetooth on" if powered else "Bluetooth off")
        self.bt_toggle.set_sensitive(True)
        self.bt_toggle.set_label("Turn off" if powered else "Turn on")
        for child in self.bt_devices.get_children():
            self.bt_devices.remove(child)
        for path, device in devices:
            if device.get("Adapter") != self.bt_adapter or not device.get("Paired"):
                continue
            name = device.get("Alias", device["Address"])
            is_connected = device.get("Connected", False)
            button = Gtk.Button(label=f"{'✓ ' if is_connected else ''}{name[:30]} · {'Disconnect' if is_connected else 'Connect'}")
            button.set_tooltip_text(name)
            button.set_sensitive(powered)
            button.connect("clicked", self.bluetooth_device_action,
                           "Disconnect" if is_connected else "Connect", path)
            self.bt_devices.pack_start(button, False, False, 0)
        if not self.bt_devices.get_children():
            self.bt_devices.pack_start(Gtk.Label(label="No paired devices", xalign=0),
                                       False, False, 0)
        self.bt_devices.show_all()

    def toggle_bluetooth(self, _button):
        powered = self.bt_toggle.get_label() != "Turn off"
        self.start_bluetooth_action(self.bt_adapter, "org.freedesktop.DBus.Properties", "Set",
                                    GLib.Variant("(ssv)", ("org.bluez.Adapter1", "Powered", GLib.Variant("b", powered))))

    def bluetooth_device_action(self, _button, action, path):
        self.start_bluetooth_action(path, "org.bluez.Device1", action, None)

    def start_bluetooth_action(self, path, interface, method, parameters):
        if getattr(self, "bt_busy", False):
            return
        self.bt_busy = True
        self.bt_status.set_text("Updating Bluetooth…")
        self.bt_toggle.set_sensitive(False)
        generation = self.generation

        def finished(bus, result):
            error = None
            try:
                bus.call_finish(result)
            except GLib.Error as failure:
                error = failure
            if generation != self.generation:
                return
            self.bt_busy = False
            if error:
                self.bt_toggle.set_sensitive(True)
                self.bt_status.set_text(f"Bluetooth: {error.message}")
            else:
                self.refresh_bluetooth()

        self.bluez_bus.call("org.bluez", path, interface, method, parameters, None,
                            Gio.DBusCallFlags.NONE, 12000, self.cancellable, finished)

    def open_bluetoothctl(self, _button):
        try:
            subprocess.Popen(["doomterm", "-e", "bluetoothctl"], start_new_session=True)
            self.dismiss()
        except OSError as error:
            self.bt_status.set_text(f"Could not open bluetoothctl: {error}")

    def build_calendar(self, content):
        self.calendar_year = datetime.now().year
        self.calendar_month = datetime.now().month
        self.clock_label = Gtk.Label(xalign=0)
        content.pack_start(self.clock_label, False, False, 0)
        self.update_clock()
        self.sources.append(GLib.timeout_add_seconds(1, self.update_clock))
        navigation = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        previous = Gtk.Button(label="<")
        previous.connect("clicked", self.change_calendar_month, -1)
        navigation.pack_start(previous, False, False, 0)
        self.calendar_month_label = Gtk.Label()
        navigation.pack_start(self.calendar_month_label, True, True, 0)
        next_month = Gtk.Button(label=">")
        next_month.connect("clicked", self.change_calendar_month, 1)
        navigation.pack_end(next_month, False, False, 0)
        content.pack_start(navigation, False, False, 0)
        self.calendar_widget = Gtk.Calendar()
        self.calendar_widget.set_display_options(
            Gtk.CalendarDisplayOptions.SHOW_DAY_NAMES
            | Gtk.CalendarDisplayOptions.NO_MONTH_CHANGE
        )
        content.pack_start(self.calendar_widget, False, False, 0)
        self.show_calendar_month()

    def update_clock(self):
        if self.kind != "calendar":
            return False
        self.clock_label.set_text(datetime.now().strftime("%A, %d %B %Y · %H:%M:%S"))
        return True

    def change_calendar_month(self, _button, offset):
        self.calendar_year, self.calendar_month = shifted_month(
            self.calendar_year, self.calendar_month, offset
        )
        self.show_calendar_month()

    def show_calendar_month(self):
        self.calendar_month_label.set_text(
            datetime(self.calendar_year, self.calendar_month, 1).strftime("%B %Y")
        )
        today = datetime.now().date()
        self.calendar_widget.select_month(self.calendar_month - 1, self.calendar_year)
        self.calendar_widget.clear_marks()
        if (self.calendar_year, self.calendar_month) == (today.year, today.month):
            self.calendar_widget.mark_day(today.day)
            self.calendar_widget.select_day(today.day)
        else:
            self.calendar_widget.select_day(0)

    def build_weather(self, content):
        self.weather_status = Gtk.Label(label="Loading Jalandhar weather…", xalign=0)
        content.pack_start(self.weather_status, False, False, 0)
        self.weather_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.pack_start(self.weather_rows, False, False, 0)
        try:
            process = Gio.Subprocess.new(
                [str(Path.home() / ".local/bin/waybar-weather.py"), "details"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            )
            self.weather_process = process
            process.communicate_utf8_async(None, self.cancellable, self.weather_ready, self.generation)
        except GLib.Error as error:
            self.weather_status.set_text(f"Weather unavailable: {error}")

    def weather_ready(self, process, result, generation):
        try:
            _ok, output, error = process.communicate_utf8_finish(result)
        except GLib.Error as error:
            if generation == self.generation:
                self.weather_status.set_text(f"Weather unavailable: {error.message}")
            return
        if generation != self.generation:
            return
        self.weather_process = None
        try:
            info = json.loads(output)
            if not info:
                raise ValueError("No current forecast")
            self.show_weather(info)
        except (ValueError, KeyError, TypeError) as failure:
            self.weather_status.set_text(f"Weather unavailable: {failure or error.strip()}")

    def show_weather(self, info):
        for child in self.weather_rows.get_children():
            self.weather_rows.remove(child)
        self.weather_status.set_text(
            f"{info['icon']}  {info['temperature']:.0f}°C · {info['description']}"
        )
        today = info["forecast"][0]
        lines = [
            f"Feels like  {info['feels_like']:.0f}°C",
            f"Humidity  {info['humidity']}%",
            f"Wind  {info['wind_speed']:.0f} km/h · {info['wind_direction']}°",
            f"Precipitation  {info['precipitation']:.1f} mm",
            f"Today  {today['low']:.0f}–{today['high']:.0f}°C · rain {today['rain_chance']}%",
            f"Sunrise  {info['sunrise'][11:16]} · Sunset  {info['sunset'][11:16]}",
        ]
        for day in info["forecast"][1:]:
            lines.append(
                f"{day['day']}  {day['condition']} · {day['low']:.0f}–{day['high']:.0f}°C · rain {day['rain_chance']}%"
            )
        lines.append(
            f"Open-Meteo forecast · {info['updated'].replace('T', ' ')}"
            + (" · cached" if info["stale"] else "")
        )
        for line in lines:
            label = Gtk.Label(label=line, xalign=0)
            label.set_line_wrap(True)
            label.set_max_width_chars(48)
            label.get_style_context().add_class("applet-detail")
            self.weather_rows.pack_start(label, False, False, 0)
        self.weather_rows.show_all()

    def build_notifications(self, content):
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self.refresh_notifications())
        actions.pack_start(refresh, True, True, 0)
        restore = Gtk.Button(label="Restore latest")
        restore.connect("clicked", self.restore_notification)
        actions.pack_start(restore, True, True, 0)
        content.pack_start(actions, False, False, 0)
        self.notification_status = Gtk.Label(xalign=0)
        content.pack_start(self.notification_status, False, False, 0)
        self.notification_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.notification_scroll = scroll
        scroll.add(self.notification_list)
        content.pack_start(scroll, True, True, 0)
        self.refresh_notifications()

    def refresh_notifications(self):
        if self.kind != "notifications":
            return
        self.notification_status.set_text("Loading notifications…")

        def read():
            current = json.loads(command_output("makoctl", "list", "-j"))
            history = json.loads(command_output("makoctl", "history", "-j"))
            return current, history

        self.run_background("notifications-read", read, self.show_notifications)

    def show_notifications(self, value, error):
        if error:
            self.notification_status.set_text(f"Mako unavailable: {error}")
            return
        current, history = value
        self.notification_status.set_text(
            f"{len(current)} active · {len(history)} recent"
        )
        self.notification_scroll.set_size_request(
            -1, min(400, max(100, (len(current) + len(history)) * 54 + 40))
        )
        for child in self.notification_list.get_children():
            self.notification_list.remove(child)
        for label, notifications in (("Now", current), ("Earlier", history)):
            if not notifications:
                continue
            heading = Gtk.Label(label=label, xalign=0)
            heading.get_style_context().add_class("applet-title")
            self.notification_list.pack_start(heading, False, False, 0)
            for item in notifications[:20]:
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                title = Gtk.Label(
                    label=f"{item.get('app_name') or 'Application'} · {item.get('summary') or 'Notification'}",
                    xalign=0,
                )
                title.set_line_wrap(True)
                title.set_max_width_chars(48)
                box.pack_start(title, False, False, 0)
                body = item.get("body")
                if body:
                    detail = Gtk.Label(label=body[:250], xalign=0)
                    detail.set_line_wrap(True)
                    detail.set_max_width_chars(48)
                    detail.get_style_context().add_class("applet-detail")
                    box.pack_start(detail, False, False, 0)
                self.notification_list.pack_start(box, False, False, 0)
        if not current and not history:
            self.notification_list.pack_start(
                Gtk.Label(label="No recent notifications", xalign=0), False, False, 0
            )
        self.notification_list.show_all()

    def restore_notification(self, _button):
        def finished(_value, error):
            if error:
                self.notification_status.set_text(f"Could not restore: {error}")
            else:
                self.refresh_notifications()

        self.run_background("notification-restore", lambda: command_output("makoctl", "restore"), finished)

    def build_wifi(self, content):
        load_nm()
        self.wifi_status = Gtk.Label(label="Loading Wi-Fi…", xalign=0)
        self.wifi_status.get_style_context().add_class("applet-detail")
        content.pack_start(self.wifi_status, False, False, 0)
        self.wifi_disconnect = Gtk.Button(label="Disconnect")
        self.wifi_disconnect.set_no_show_all(True)
        self.wifi_disconnect.connect("clicked", self.disconnect_wifi)
        content.pack_start(self.wifi_disconnect, False, False, 0)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.wifi_toggle = Gtk.Button()
        self.wifi_toggle.connect("clicked", self.toggle_wifi)
        actions.pack_start(self.wifi_toggle, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self.scan_wifi())
        actions.pack_start(refresh, True, True, 0)
        content.pack_start(actions, False, False, 0)
        self.wifi_message = Gtk.Label(xalign=0)
        self.wifi_message.set_line_wrap(True)
        self.wifi_message.get_style_context().add_class("applet-message")
        content.pack_start(self.wifi_message, False, False, 0)
        self.wifi_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(80)
        scroll.set_max_content_height(270)
        scroll.set_propagate_natural_height(True)
        scroll.add(self.wifi_list)
        self.wifi_scroll = scroll
        content.pack_start(scroll, True, True, 0)
        manage = Gtk.Button(label="Enterprise or advanced setup: nmtui")
        manage.connect("clicked", lambda *_: self.open_nmtui())
        content.pack_start(manage, False, False, 0)
        if self.nm_client:
            self.wifi_ready()
        else:
            generation = self.generation

            def initialized(_source, result):
                try:
                    client = NM.Client.new_finish(result)
                except GLib.Error as error:
                    if generation == self.generation:
                        self.wifi_status.set_text(f"Wi-Fi unavailable: {error.message}")
                    return
                if generation == self.generation:
                    self.nm_client = client
                    self.wifi_ready()

            NM.Client.new_async(self.cancellable, initialized)

    def wifi_ready(self):
        self.wifi_device = next((device for device in self.nm_client.get_devices()
                                 if isinstance(device, NM.DeviceWifi)), None)
        handler = self.nm_client.connect("notify::wireless-enabled", lambda *_: self.refresh_wifi())
        self.wifi_signals.append((self.nm_client, handler))
        if self.wifi_device:
            for signal in ("access-point-added", "access-point-removed",
                           "notify::state", "notify::active-access-point"):
                handler = self.wifi_device.connect(signal, lambda *_: self.refresh_wifi())
                self.wifi_signals.append((self.wifi_device, handler))
        self.refresh_wifi()
        self.scan_wifi()

    def wifi_message_text(self, message):
        if self.kind == "wifi":
            self.wifi_message.set_text(message)

    def refresh_wifi(self):
        if self.kind != "wifi":
            return
        enabled = self.nm_client.wireless_get_enabled()
        self.wifi_toggle.set_label("Turn Wi-Fi off" if enabled else "Turn Wi-Fi on")
        for child in self.wifi_list.get_children():
            self.wifi_list.remove(child)
        if not self.wifi_device:
            self.wifi_status.set_text("No Wi-Fi device")
            self.wifi_disconnect.hide()
            return
        if not enabled:
            self.wifi_status.set_text("Wi-Fi is off")
            self.wifi_disconnect.hide()
            return
        active = self.wifi_device.get_active_access_point()
        self.wifi_disconnect.set_visible(bool(active))
        self.wifi_status.set_text(
            f"Connected to {ssid_name(active)}" if active else "Not connected"
        )
        seen = {}
        for ap in self.wifi_device.get_access_points():
            raw = ssid_bytes(ap)
            if not raw:
                continue
            key = (raw, security_type(ap))
            if key not in seen or ap.get_strength() > seen[key].get_strength():
                seen[key] = ap
        for ap in sorted(seen.values(), key=lambda item: item.get_strength(), reverse=True)[:15]:
            state = security_type(ap)
            label = f"{'✓ ' if active and ap.get_bssid() == active.get_bssid() else ''}{ssid_name(ap)}  ·  {ap.get_strength()}%{'  ' if state != 'open' else ''}"
            button = Gtk.Button(label=label)
            button.get_style_context().add_class("applet-network")
            button.connect("clicked", self.select_ap, ap)
            self.wifi_list.pack_start(button, False, False, 0)
        self.wifi_scroll.set_size_request(
            -1, min(270, max(80, min(len(seen), 15) * 40))
        )
        self.wifi_list.show_all()

    def scan_wifi(self):
        if not self.wifi_device or not self.nm_client.wireless_get_enabled():
            return
        self.wifi_message_text("Scanning…")
        self.wifi_device.request_scan_async(None, self.scan_finished)

    def scan_finished(self, device, result):
        if self.kind != "wifi":
            return
        try:
            device.request_scan_finish(result)
            self.wifi_message_text("")
        except GLib.Error as error:
            self.wifi_message_text(str(error))
        self.refresh_wifi()

    def toggle_wifi(self, _button):
        if not self.nm_client:
            return
        target = "off" if self.nm_client.wireless_get_enabled() else "on"

        def finished(_value, error):
            if error:
                self.wifi_message_text(f"Could not change Wi-Fi: {error}")
            else:
                self.refresh_wifi()

        self.run_background("wifi-toggle", lambda: command_output("nmcli", "radio", "wifi", target), finished)

    def select_ap(self, _button, ap):
        if self.wifi_device.get_active_access_point() == ap:
            return
        raw = ssid_bytes(ap)
        connections = self.wifi_device.get_available_connections() or []
        saved = next(
            (connection for connection in connections
             if connection.get_setting_wireless()
             and connection.get_setting_wireless().get_ssid()
             and bytes(connection.get_setting_wireless().get_ssid().get_data()) == raw),
            None,
        )
        if saved:
            self.wifi_message_text(f"Connecting to {ssid_name(ap)}…")
            self.nm_client.activate_connection_async(
                saved, self.wifi_device, ap.get_path(), None, self.activation_finished
            )
            return
        kind = security_type(ap)
        if kind == "enterprise":
            self.open_nmtui()
        elif kind == "open":
            self.add_connection(ap, None, kind)
        else:
            self.password_prompt(ap, kind)

    def password_prompt(self, ap, kind):
        if self.password_box:
            self.content.remove(self.password_box)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.password_box = box
        box.pack_start(Gtk.Label(label=f"Password for {ssid_name(ap)}", xalign=0),
                       False, False, 0)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_placeholder_text("Wi-Fi password")
        box.pack_start(entry, False, False, 0)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", self.cancel_password)
        buttons.pack_start(cancel, True, True, 0)
        connect = Gtk.Button(label="Connect")
        connect.connect("clicked", self.submit_password, ap, kind, entry)
        buttons.pack_start(connect, True, True, 0)
        box.pack_start(buttons, False, False, 0)
        entry.connect("activate", self.submit_password, ap, kind, entry)
        self.content.pack_start(box, False, False, 0)
        box.show_all()
        entry.grab_focus()

    def cancel_password(self, _button):
        self.content.remove(self.password_box)
        self.password_box = None

    def submit_password(self, _widget, ap, kind, entry):
        password = entry.get_text()
        if len(password) < 8:
            self.wifi_message_text("Password must be at least 8 characters")
            return
        self.content.remove(self.password_box)
        self.password_box = None
        self.add_connection(ap, password, kind)

    def add_connection(self, ap, password, kind):
        connection = NM.SimpleConnection.new()
        identity = NM.SettingConnection.new()
        identity.set_property("id", ssid_name(ap))
        identity.set_property("uuid", str(uuid.uuid4()))
        identity.set_property("type", NM.SETTING_WIRELESS_SETTING_NAME)
        connection.add_setting(identity)
        wireless = NM.SettingWireless.new()
        wireless.set_property("ssid", ap.get_ssid())
        wireless.set_property("mode", "infrastructure")
        connection.add_setting(wireless)
        if password is not None:
            security = NM.SettingWirelessSecurity.new()
            security.set_property("key-mgmt", "sae" if kind == "sae" else "wpa-psk")
            security.set_property("psk", password)
            connection.add_setting(security)
        for setting_class in (NM.SettingIP4Config, NM.SettingIP6Config):
            setting = setting_class.new()
            setting.set_property("method", "auto")
            connection.add_setting(setting)
        self.wifi_message_text(f"Connecting to {ssid_name(ap)}…")
        self.nm_client.add_and_activate_connection2(
            connection, self.wifi_device, ap.get_path(),
            GLib.Variant("a{sv}", {}), None, self.new_connection_finished
        )

    def activation_finished(self, client, result):
        try:
            active = client.activate_connection_finish(result)
            self.watch_connection(active)
        except GLib.Error as error:
            self.wifi_message_text(f"Connection failed: {error.message}")

    def new_connection_finished(self, client, result):
        try:
            active, _details = client.add_and_activate_connection2_finish(result)
            self.watch_connection(active)
        except GLib.Error as error:
            self.wifi_message_text(f"Connection failed: {error.message}")

    def watch_connection(self, active):
        def changed(connection, _param=None):
            if self.kind != "wifi":
                return
            if connection.get_state() == NM.ActiveConnectionState.ACTIVATED:
                self.dismiss()
            elif connection.get_state() == NM.ActiveConnectionState.DEACTIVATED:
                self.wifi_message_text("Connection failed; check credentials")
        active.connect("notify::state", changed)
        changed(active)

    def disconnect_wifi(self, _button):
        active = self.wifi_device.get_active_connection()
        if not active:
            return
        self.wifi_message_text("Disconnecting…")
        self.nm_client.deactivate_connection_async(
            active, None, self.disconnect_finished
        )

    def disconnect_finished(self, client, result):
        try:
            client.deactivate_connection_finish(result)
            self.wifi_message_text("Disconnected")
        except GLib.Error as error:
            self.wifi_message_text(f"Disconnect failed: {error.message}")
        self.refresh_wifi()

    def open_nmtui(self):
        try:
            subprocess.Popen(["doomterm", "-e", "nmtui"], start_new_session=True)
            self.dismiss()
        except OSError as error:
            self.wifi_message_text(f"Could not open nmtui: {error}")


if __name__ == "__main__":
    sys.exit(Applets().run(sys.argv))
