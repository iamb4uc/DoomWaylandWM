#!/bin/sh
set -eu

repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
state_dir=$(mktemp -d)
bin_dir=$state_dir/bin
mkdir -p "$bin_dir"
trap 'rm -rf "$state_dir"' EXIT

cat > "$bin_dir/flameshot" <<'EOF'
#!/bin/sh
printf '%s\n' 'flameshot was called' >&2
exit 99
EOF

cat > "$bin_dir/pgrep" <<'EOF'
#!/bin/sh
case "$*" in
  *flameshot*) exit 0 ;;
  *) exit 1 ;;
esac
EOF

cat > "$bin_dir/gdbus" <<'EOF'
#!/bin/sh
printf '%s\n' 'gdbus was called' >&2
exit 99
EOF

cat > "$bin_dir/slurp" <<'EOF'
#!/bin/sh
printf '%s\n' '0,0 10x10'
EOF

cat > "$bin_dir/grim" <<'EOF'
#!/bin/sh
printf '%s' 'fake-png'
EOF

cat > "$bin_dir/swappy" <<'EOF'
#!/bin/sh
set -eu

[ "${1:-}" = -f ]
[ "${2:-}" = - ]
[ "${3:-}" = -o ]
target=$4
cat > "$target"
printf '%s\n' "$*" > "$SWAPPY_CALL"
EOF

cat > "$bin_dir/wl-copy" <<'EOF'
#!/bin/sh
cat > "$SCREENSHOT_COPY"
EOF

cat > "$bin_dir/notify-send" <<'EOF'
#!/bin/sh
exit 0
EOF

chmod +x "$bin_dir"/*
export PATH="$bin_dir:$PATH"
export SCREENSHOT_COPY="$state_dir/copy.png"
export SWAPPY_CALL="$state_dir/swappy-call"
export XDG_PICTURES_DIR="$state_dir/pictures"

shot=$("$repo_dir"/.local/bin/wayland-shot area)
case "$shot" in
  "$XDG_PICTURES_DIR"/Screenshots/shot-*.png) ;;
  *) exit 1 ;;
esac
[ -s "$shot" ]
[ -s "$SCREENSHOT_COPY" ]
grep -Fqx -- "-f - -o $shot" "$SWAPPY_CALL"

printf '%s\n' 'wayland-shot annotation flow: ok'
