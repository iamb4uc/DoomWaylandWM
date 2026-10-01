#!/bin/sh
set -eu

repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
helper=$repo_dir/.local/bin/waybar-transient-control
config=$repo_dir/.config/sway/config
state_dir=$(mktemp -d)
trap 'rm -rf "$state_dir"' EXIT

grep -Fqx 'bindsym $mod+F2 exec $HOME/.local/bin/waybar-transient-control volume down' "$config" || {
	printf '%s\n' 'Mod+F2 does not lower the system volume' >&2
	exit 1
}
grep -Fqx 'bindsym $mod+F3 exec $HOME/.local/bin/waybar-transient-control volume up' "$config" || {
	printf '%s\n' 'Mod+F3 does not raise the system volume' >&2
	exit 1
}

export XDG_RUNTIME_DIR="$state_dir"
export WAYBAR_TRANSIENT_NOW=100

initial=$($helper volume read)
[ "$initial" = '{"text":"","tooltip":""}' ]

printf '%s\n' '103|VOL 60%' > "$state_dir/waybar-volume"
visible=$($helper volume read)
[ "$visible" = '{"text":"VOL 60%","tooltip":"Volume 60%"}' ]

export WAYBAR_TRANSIENT_NOW=104
expired=$($helper volume read)
[ "$expired" = '{"text":"","tooltip":""}' ]

printf '%s\n' '106|BRI 100%' > "$state_dir/waybar-brightness"
export WAYBAR_TRANSIENT_NOW=105
still_visible=$($helper brightness read)
[ "$still_visible" = '{"text":"BRI 100%","tooltip":"Brightness 100%"}' ]

export WAYBAR_TRANSIENT_NOW=106
expired_brightness=$($helper brightness read)
[ "$expired_brightness" = '{"text":"","tooltip":""}' ]

printf '%s\n' 'transient control state lifecycle: ok'
