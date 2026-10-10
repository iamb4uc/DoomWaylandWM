# Waybar applet performance

The popups stay in Python/GTK. `waybar-applet` uses the installed native
`gapplication` client to switch an already-open popup over D-Bus. It starts
Python when no popup is running. Closing the popup exits the application;
there is no persistent popup service.

NetworkManager and night-light code load only when needed. Device commands
run on one background worker, with GTK updates delivered on the main thread.
Slider writes coalesce to the latest value. Closing or switching a popup
discards obsolete results, cancels pending jobs, removes timers, and disconnects
Wi-Fi handlers. Bluetooth fetches only adapter/device properties, rather than
the entire BlueZ object tree. Weather uses asynchronous pipe completion.

Night-light status runs once per minute per bar, plus an immediate refresh on
settings changes through Waybar signal 9. Gammastep still handles the actual
schedule independently. Applying unchanged settings avoids restarting it.

## Measurements

Measured on the active Sway session. Cold-popup figures are median times from
starting applet imports to GTK's first `after-paint` event: three samples before,
five after. They exclude the interpreter's startup and the Waybar click dispatch.
Device details may finish loading after first paint. Other applications were
running, so these are local observations, not timing guarantees.

| Applet | Before first paint | After first paint |
| --- | ---: | ---: |
| Calendar | 471 ms | 181 ms |
| Brightness | 284 ms | 185 ms |
| Battery | 214 ms | 187 ms |
| Night light | 479 ms | 221 ms |
| Volume | 297 ms | 172 ms |
| Bluetooth | 271 ms | 183 ms |
| Wi-Fi | 351 ms | 175 ms |
| Notifications | 421 ms | 191 ms |
| Weather | 321 ms | 193 ms |

Eight-run `hyperfine` comparison of switching battery -> calendar in the same
open application: direct Python clients averaged **451.4 ms per pair**; the
native launcher averaged **48.7 ms per pair**, about **9.3 times faster**.
This measures command completion, not the compositor's presentation time.

The night-light status helper averaged **111.7 ms before** and **55.4 ms after**.
Its periodic executions across two bars drop from **1,440 to 120 per hour**.
Measured open-popup PSS is approximately **30-36 MiB** after the changes;
there was no consistent reduction versus the initial 29-33 MiB samples.
The resource gains are fewer interpreter launches, less CPU work, and fewer
idle wakeups. No popup process remains after dismissal.

## Reproduce and validate

```sh
python3 tests/benchmark-waybar-applets.py --runs 5 --output HDMI-A-1
make check
make check-install
```

The checks cover lazy imports, input validation, schedule persistence,
unchanged settings, background error reporting, stale callbacks, and slider
coalescing. Live QA opened all nine popups, compared audio/backlight values
with the installed tools, repeated Wi-Fi/calendar switching, checked invalid
and unchanged night-light Apply actions, and verified process cleanup.
The latter Apply handler returned in roughly 0.2 ms while work finished
asynchronously. Hardware connection/power changes were not exercised.
