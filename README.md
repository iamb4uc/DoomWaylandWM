# WAYLAND_SYSTEM

A separate Wayland desktop repo for the aesthetic Sway setup.

This repo is intentionally separate from `DOOMSDAY_SYSTEM`. Keep DoomWM and the
X11 stack there. Keep Wayland-only compositor/session config here.

The install flow is symlink based. It links only repo-owned files from
`.config`, `.local/bin`, and `.local/share` into `$HOME`, and backs up conflicts
before linking.

## What It Owns

- Sway session config in `.config/sway`
- Optional SwayFX visual-effects config in `.config/swayfx`
- Waybar config in `.config/waybar`
- Eww dashboard config in `.config/eww`
- Wofi launcher theme in `.config/wofi`
- Mako notification config in `.config/mako`
- Wayland helper scripts in `.local/bin`
- Wayland package manifests in `packages/void`
- Gruvbox theme notes in `docs/gruvbox.md`
- Wallpaper loading from DoomDots `setbg` via `~/.local/share/bg`

General app config such as zsh, tmux, Neovim, lf, mpv, and browser config should
stay in DoomDots unless it becomes Wayland-specific.

`wayland-session` adds both user and system Flatpak export directories to
`XDG_DATA_DIRS`, so installed Flatpak desktop entries are available to Wofi's
`drun` mode. The repo also owns the local Pympress desktop entry.

## Install

Preview:

```sh
./install.sh --dry-run --all
```

Install dotfile symlinks only:

```sh
./install.sh --yes --dots --no-deps
```

Install Void support packages and dotfile symlinks:

```sh
./install.sh --yes --all
```

The default package set is intentionally lean. Optional portal, polkit, lock,
browser, PDF, and media packages live in `packages/void/90-optional` and are not
part of the default installer path.

To include optional packages through the installer:

```sh
./install.sh --yes --all --optional
```

## Eww dashboard

The Sway dashboard uses Eww layer-shell windows for profile, system, clock,
machine, media, weather, session actions, and folders. The launcher checks the
daemon and active windows for this config, so stale marker files cannot invert
its open/close state.

Eww is not currently packaged in the configured Void repositories. Install its
optional build dependencies, then build the Wayland backend into `~/.local/bin`:

```sh
doas xbps-install -y glib-devel gtk+3-devel gtk-layer-shell-devel libdbusmenu-gtk3-devel pango-devel cairo-devel gdk-pixbuf-devel
cargo install --git https://github.com/elkowar/eww --package eww --no-default-features --features wayland --root "$HOME/.local"
```

The session autostart opens the dashboard automatically.

Install into a temp home for testing:

```sh
make check-install
```

## Sway On Void

Sway is available in your current Void package index, so this profile stays
XBPS-native by default. The default package set installs `sway` and the small
Wayland tools used by this repo.

If `swayfx` is installed and `~/.config/swayfx/config` is linked,
`wayland-session` will use it for blur, rounded corners, shadows, and dimming.
Plain Sway remains the fallback.

## Optional Packages

Install optional extras manually if you need them:

```sh
sudo xbps-install -y xdg-desktop-portal xdg-desktop-portal-wlr xdg-desktop-portal-gtk polkit-gnome swaylock swayidle firefox qutebrowser zathura zathura-pdf-mupdf mpv ImageMagick ffmpeg mediainfo noto-fonts-ttf
```

Do not install `polkit-gnome` unless you want GUI privilege prompts in the
Wayland session. The default Sway config does not start a polkit agent.

## Useful Commands

```sh
make check
make smoke
make check-install
make doctor
```

## Repo Rule

Only keep dotfiles, local helper scripts, package manifests, and docs in this
repo. If a tool grows into a standalone project, make a new sibling repo under
`~/Git`.
