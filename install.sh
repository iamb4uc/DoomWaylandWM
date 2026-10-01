#!/bin/sh
set -eu

PROGRAM=${0##*/}
DEFAULT_PACKAGES_DIR=packages/void

PACKAGES_DIR=${PACKAGES_DIR:-$DEFAULT_PACKAGES_DIR}
DOTFILES_PREFIX=${DOTFILES_PREFIX:-$HOME}
ASSUME_YES=0
INSTALL_DEPS=1
INSTALL_OPTIONAL=0
DRY_RUN=0
LIST_ONLY=0
UNINSTALL=0
SELECT_SYSTEM=0
SELECT_DOTS=0
SELECT_ANY=0
SUDO=

[ "$(id -u)" -eq 0 ] || SUDO=${SUDO:-sudo}

usage() {
	cat <<EOF
Usage: $PROGRAM [module] [options]

Install the WAYLAND_SYSTEM desktop profile.
With no module selected, this defaults to --all.

Modules:
      --system          Install Void Wayland support packages
      --dots            Install Wayland dotfile symlinks
      --all             Install every module (default)

Options:
  -y, --yes              Non-interactive mode; answer yes to prompts
      --dry-run          Print planned actions without changing the system
      --list             List modules and exit
      --uninstall        Uninstall selected modules instead of installing
      --no-deps          Skip dependency installation
      --optional         Include optional packages from 90-optional
      --packages-dir DIR Read Void package manifests from DIR
      --dotfiles-prefix DIR
                         Install dotfile symlinks under DIR (default: \$HOME)
  -h, --help             Show this help

Environment:
  PACKAGES_DIR, DOTFILES_PREFIX, SUDO

Examples:
  ./install.sh --dry-run --all
  ./install.sh --yes --dots --no-deps
  ./install.sh --yes --all
EOF
}

log() {
	printf '%s\n' "==> $*"
}

die() {
	printf '%s\n' "error: $*" >&2
	exit 1
}

need_cmd() {
	command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

confirm() {
	prompt=$1

	if [ "$ASSUME_YES" -eq 1 ] || [ "$DRY_RUN" -eq 1 ]; then
		return 0
	fi

	printf '%s [Y/n] ' "$prompt"
	read -r answer
	answer=${answer:-y}

	case "$answer" in
		y|Y|yes|YES) return 0 ;;
		*) return 1 ;;
	esac
}

run() {
	printf '+'
	for arg in "$@"; do
		printf ' %s' "$arg"
	done
	printf '\n'
	if [ "$DRY_RUN" -eq 1 ]; then
		return 0
	fi
	"$@"
}

as_root() {
	if [ "$(id -u)" -eq 0 ]; then
		run "$@"
	else
		need_cmd "$SUDO"
		run "$SUDO" "$@"
	fi
}

is_void_linux() {
	[ -r /etc/os-release ] && grep -Eq '^(ID=void|DISTRIB_ID="?void"?)' /etc/os-release
}

require_void_linux() {
	if [ "$DRY_RUN" -eq 1 ]; then
		return 0
	fi

	is_void_linux || die "this installer is Void Linux exclusive"
	need_cmd xbps-install
}

package_list() {
	[ -d "$PACKAGES_DIR" ] || die "missing package manifest directory: $PACKAGES_DIR"
	find "$PACKAGES_DIR" -type f | sort | while IFS= read -r file; do
		case "${file##*/}" in
			90-optional)
				[ "$INSTALL_OPTIONAL" -eq 1 ] || continue
				;;
		esac
		sed 's/#.*//;/^[[:space:]]*$/d' "$file"
	done
}

install_packages() {
	require_void_linux
	if ! confirm "Install Void Wayland support packages?"; then
		log "skipping packages"
		return 0
	fi

	pkgs=$(package_list | sort -u)
	[ -n "$pkgs" ] || return 0

	if [ "$DRY_RUN" -eq 1 ]; then
		printf '%s\n' "$pkgs" | sed 's/^/+ package /'
		return 0
	fi

	as_root xbps-install -S
	as_root xbps-install -yu xbps
	as_root xbps-install -yu
	# shellcheck disable=SC2086
	as_root xbps-install -y $pkgs
}

install_dots() {
	if [ "$UNINSTALL" -eq 1 ]; then
		run make PREFIX="$DOTFILES_PREFIX" uninstall
	else
		run make PREFIX="$DOTFILES_PREFIX" install
	fi
}

list_modules() {
	cat <<'EOF'
system  Void Wayland support packages
dots    Wayland dotfile symlinks
all     system + dots
EOF
}

select_all_if_needed() {
	if [ "$SELECT_ANY" -eq 0 ]; then
		SELECT_SYSTEM=1
		SELECT_DOTS=1
	fi
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--system) SELECT_SYSTEM=1; SELECT_ANY=1 ;;
		--dots) SELECT_DOTS=1; SELECT_ANY=1 ;;
		--all) SELECT_SYSTEM=1; SELECT_DOTS=1; SELECT_ANY=1 ;;
		-y|--yes) ASSUME_YES=1 ;;
		--dry-run) DRY_RUN=1 ;;
		--list) LIST_ONLY=1 ;;
		--uninstall) UNINSTALL=1 ;;
		--no-deps) INSTALL_DEPS=0 ;;
		--optional) INSTALL_OPTIONAL=1 ;;
		--packages-dir)
			[ "$#" -ge 2 ] || die "--packages-dir requires a value"
			PACKAGES_DIR=$2
			shift
			;;
		--dotfiles-prefix)
			[ "$#" -ge 2 ] || die "--dotfiles-prefix requires a value"
			DOTFILES_PREFIX=$2
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			die "unknown option: $1"
			;;
	esac
	shift
done

if [ "$LIST_ONLY" -eq 1 ]; then
	list_modules
	exit 0
fi

select_all_if_needed

if [ "$UNINSTALL" -eq 1 ]; then
	[ "$SELECT_DOTS" -eq 1 ] && install_dots
	exit 0
fi

if [ "$SELECT_SYSTEM" -eq 1 ]; then
	if [ "$INSTALL_DEPS" -eq 1 ]; then
		install_packages
	else
		log "skipping packages by request"
	fi
fi

[ "$SELECT_DOTS" -eq 1 ] && install_dots
