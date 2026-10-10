#!/bin/sh
set -eu

repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home" "$tmp/state" "$tmp/mock"

cat >"$tmp/bin/mock" <<'EOF'
#!/bin/sh
name=${0##*/}
printf '%s %s\n' "$name" "$*" >>"$MOCK_DIR/calls"
case "$name" in
	pgrep)
		for arg do target=$arg; done
		[ -e "$MOCK_DIR/$target" ] ;;
	pkill)
		for arg do target=$arg; done
		rm -f "$MOCK_DIR/$target" ;;
	pw-cli) [ -e "$MOCK_DIR/pipewire" ] ;;
	pactl)
		case "$1" in
			info) [ -e "$MOCK_DIR/pipewire-pulse" ] ;;
			get-default-sink)
				[ -e "$MOCK_DIR/wireplumber" ] || exit 1
				if [ "${MOCK_DUMMY:-0}" = 1 ] && [ ! -e "$MOCK_DIR/recovered" ]; then
					printf '%s\n' auto_null
				else
					printf '%s\n' 'alsa_output.test'
				fi
				;;
		esac ;;
	swaymsg)
		if [ "$1" = -t ] && [ "$2" = get_outputs ]; then
			[ "${MOCK_DISPLAY_FAIL:-0}" != 1 ] || exit 1
			printf '%s\n' '[{"name":"HDMI-A-1","active":true,"modes":[{"width":1920,"height":1080,"refresh":75000}],"current_mode":{"width":1920,"height":1080,"refresh":60000},"rect":{"width":1920}},{"name":"eDP-1","active":true,"modes":[],"rect":{"width":1920}}]'
		fi ;;
	wofi) printf '%s\n' Left ;;
	wayland_night_light.py) : >"$MOCK_DIR/gammastep" ;;
	wireplumber)
		: >"$MOCK_DIR/wireplumber"
		[ "${MOCK_DUMMY:-0}" != 1 ] || : >"$MOCK_DIR/recovered" ;;
	pipewire|pipewire-pulse|mako|waybar|gammastep|swayidle|syncthing|mpd|wayland-sway-watch|wayland-output-watch)
		: >"$MOCK_DIR/$name" ;;
esac
EOF
chmod +x "$tmp/bin/mock"
for name in pgrep pkill pw-cli pactl swaymsg wofi pipewire pipewire-pulse wireplumber mako waybar gammastep swayidle syncthing mpd wayland-sway-watch wayland-output-watch wayland-wallpaper dbus-update-activation-environment wl-paste; do
	ln -s mock "$tmp/bin/$name"
done
ln -s mock "$tmp/bin/wayland_night_light.py"

export PATH="$tmp/bin:$PATH" HOME="$tmp/home" XDG_STATE_HOME="$tmp/state" MOCK_DIR="$tmp/mock"
export MOCK_DISPLAY_FAIL=1
: >"$MOCK_DIR/dunst"
"$repo_dir/.local/bin/wayland-autostart"

for _ in 1 2 3 4 5 6 7 8 9 10; do
	[ -e "$MOCK_DIR/mako" ] && break
	sleep 0.1
done
[ -e "$MOCK_DIR/mako" ]
[ -e "$MOCK_DIR/gammastep" ]
grep -q '^wayland_night_light.py start$' "$MOCK_DIR/calls"
[ ! -e "$MOCK_DIR/dunst" ]
grep -q 'display setup failed' "$XDG_STATE_HOME/wayland/autostart.log"

core=$(grep -n '^pipewire $' "$MOCK_DIR/calls" | head -1 | cut -d: -f1)
manager=$(grep -n '^wireplumber $' "$MOCK_DIR/calls" | head -1 | cut -d: -f1)
pulse=$(grep -n '^pipewire-pulse $' "$MOCK_DIR/calls" | head -1 | cut -d: -f1)
[ "$core" -lt "$manager" ]
[ "$core" -lt "$pulse" ]

export MOCK_DISPLAY_FAIL=0
mkdir -p "$HOME/.config/sway"
"$repo_dir/.config/sway/scripts/display-layout"
grep -q '^output HDMI-A-1 enable position 0 0$' "$HOME/.config/sway/display-layout.conf"
grep -q '^output eDP-1 enable position 1920 0$' "$HOME/.config/sway/display-layout.conf"
"$repo_dir/.local/bin/wayland-autostart" --display-only
grep -q '^swaymsg output HDMI-A-1 mode 1920x1080@75Hz$' "$MOCK_DIR/calls"
if grep -Eq '^swaymsg output .* (enable|position) ' "$MOCK_DIR/calls"; then
	printf '%s\n' 'display refresh setup changed the selected layout' >&2
	exit 1
fi

: >"$MOCK_DIR/calls"
"$repo_dir/.local/bin/wayland-autostart" --audio-only
grep -q 'audio: healthy after resume' "$XDG_STATE_HOME/wayland/autostart.log"
if grep -Eq '^(pipewire|wireplumber|pipewire-pulse) $' "$MOCK_DIR/calls"; then
	printf '%s\n' 'healthy resume restarted audio' >&2
	exit 1
fi

export MOCK_DUMMY=1
: >"$MOCK_DIR/calls"
"$repo_dir/.local/bin/wayland-autostart" --audio-only
[ -e "$MOCK_DIR/recovered" ]
grep -q 'audio: recovered' "$XDG_STATE_HOME/wayland/autostart.log"
grep -q '^wireplumber $' "$MOCK_DIR/calls"
if grep -Eq '^(pipewire|pipewire-pulse) $' "$MOCK_DIR/calls"; then
	printf '%s\n' 'dummy sink recovery restarted a healthy component' >&2
	exit 1
fi

printf '%s\n' 'wayland autostart and audio recovery: ok'
