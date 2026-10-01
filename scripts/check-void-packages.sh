#!/bin/sh
set -eu

PACKAGES_DIR=${PACKAGES_DIR:-packages/void}
INCLUDE_OPTIONAL=${INCLUDE_OPTIONAL:-0}

command -v xbps-query >/dev/null 2>&1 || {
	printf '%s\n' 'xbps-query not found' >&2
	exit 1
}

[ -d "$PACKAGES_DIR" ] || {
	printf '%s\n' "missing package directory: $PACKAGES_DIR" >&2
	exit 1
}

missing=$(mktemp)
trap 'rm -f "$missing"' EXIT

find "$PACKAGES_DIR" -type f | sort | while IFS= read -r file; do
	case "${file##*/}" in
		90-optional)
			[ "$INCLUDE_OPTIONAL" -eq 1 ] || continue
			;;
	esac
	sed 's/#.*//;/^[[:space:]]*$/d' "$file" | while IFS= read -r pkg; do
		if xbps-query -Rs "^${pkg}-[0-9]" >/dev/null 2>&1; then
			printf 'ok: %s\n' "$pkg"
		else
			printf 'missing: %s\n' "$pkg" >&2
			printf '%s\n' "$pkg" >> "$missing"
		fi
	done
done

[ ! -s "$missing" ]
