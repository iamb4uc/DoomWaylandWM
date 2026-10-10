#!/usr/bin/env python3

import argparse
import importlib.util
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
KINDS = ("calendar", "brightness", "battery", "night-light", "volume", "bluetooth", "wifi", "notifications", "weather")


def sample(kind, output):
    started = time.perf_counter()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(REPO / ".local/bin"))
    spec = importlib.util.spec_from_file_location("applets", REPO / ".local/bin/waybar-applets.py")
    applets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(applets)
    imported = time.perf_counter()
    app = applets.Applets()
    app.set_application_id(f"{applets.APP_ID}.Benchmark.p{os.getpid()}")
    app.register(None)
    app.open_applet(kind, output)
    built = time.perf_counter()
    loop = applets.GLib.MainLoop()

    def painted(_clock):
        clock.disconnect(handler)
        memory = dict(line.split(":", 1) for line in Path("/proc/self/smaps_rollup").read_text().splitlines()[1:])
        print(json.dumps({"import_ms": (imported - started) * 1000,
                          "build_ms": (built - imported) * 1000,
                          "paint_ms": (time.perf_counter() - started) * 1000,
                          "pss_mib": int(memory["Pss"].split()[0]) / 1024,
                          "cpu_ms": (resource.getrusage(resource.RUSAGE_SELF).ru_utime +
                                     resource.getrusage(resource.RUSAGE_SELF).ru_stime) * 1000}), flush=True)
        app.dismiss()
        loop.quit()

    clock = app.windows[-1].get_frame_clock()
    handler = clock.connect("after-paint", painted)
    applets.GLib.timeout_add_seconds(10, loop.quit)
    loop.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", choices=KINDS)
    parser.add_argument("--output", default="HDMI-A-1")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--kinds", nargs="+", choices=KINDS, default=KINDS)
    args = parser.parse_args()
    if args.sample:
        sample(args.sample, args.output)
    else:
        results = {}
        for kind in args.kinds:
            samples = []
            for _ in range(args.runs):
                child = subprocess.run([sys.executable, __file__, "--sample", kind, "--output", args.output],
                                       capture_output=True, text=True, check=True, timeout=15)
                samples.append(json.loads(child.stdout))
            results[kind] = {key: round(statistics.median(item[key] for item in samples), 2)
                             for key in samples[0]}
        print(json.dumps(results, indent=2))
