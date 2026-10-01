SHELL := /bin/sh

REPO := $(CURDIR)
PREFIX ?= $(HOME)
BACKUP_DIR ?= $(PREFIX)/.wayland-system-backup/$(shell date +%Y%m%d%H%M%S)

CONFIG_DIR_LINKS := $(filter-out .config/README.md .config/gtk-3.0 .config/gtk-4.0,$(patsubst .config/%,.config/%,$(wildcard .config/*)))
CONFIG_FILE_LINKS := .config/gtk-3.0/settings.ini .config/gtk-4.0/settings.ini
LOCAL_LINKS := $(shell find .local/bin .local/share -type f 2>/dev/null | sort)
LINKS := $(CONFIG_DIR_LINKS) $(CONFIG_FILE_LINKS) $(LOCAL_LINKS)
EXECUTABLES := $(shell find .local/bin -maxdepth 1 -type f | sort) scripts/check-void-packages.sh
SHELL_SCRIPTS := $(shell find .local/bin -maxdepth 1 -type f ! -name '*.py' | sort)

.PHONY: all help install dirs link chmod uninstall clean lint test check check-install smoke doctor status

all: install

help:
	@printf '%s\n' \
		'Targets:' \
		'  make install       Symlink Wayland files into $$HOME' \
		'  make uninstall     Remove symlinks that point back to this repo' \
		'  make check         Syntax-check scripts and man pages' \
		'  make smoke         Run installer smoke tests' \
		'  make check-install Test install into a temp HOME' \
		'  make doctor        Check expected Wayland commands' \
		'  make status        Show git status'

install: dirs link chmod
	@printf 'wayland files installed into %s\n' "$(PREFIX)"

dirs:
	@mkdir -p \
		"$(PREFIX)/.config" \
		"$(PREFIX)/.cache" \
		"$(PREFIX)/.local" \
		"$(PREFIX)/.local/bin" \
		"$(PREFIX)/.local/share" \
		"$(PREFIX)/.local/state"

link:
	@set -eu; \
	for path in $(LINKS); do \
		src="$(REPO)/$$path"; \
		dst="$(PREFIX)/$$path"; \
		[ -e "$$src" ] || [ -L "$$src" ] || continue; \
		mkdir -p "$$(dirname "$$dst")"; \
		if [ -e "$$dst" ] || [ -L "$$dst" ]; then \
			if [ "$$(readlink "$$dst" 2>/dev/null || true)" = "$$src" ]; then \
				printf 'ok: %s\n' "$$dst"; \
				continue; \
			fi; \
			mkdir -p "$(BACKUP_DIR)/$$(dirname "$$path")"; \
			mv "$$dst" "$(BACKUP_DIR)/$$path"; \
			printf 'backup: %s -> %s\n' "$$dst" "$(BACKUP_DIR)/$$path"; \
		fi; \
		ln -s "$$src" "$$dst"; \
		printf 'link: %s -> %s\n' "$$dst" "$$src"; \
	done

chmod:
	@set -eu; \
	for file in $(EXECUTABLES); do \
		[ -f "$$file" ] || continue; \
		chmod +x "$$file"; \
	done
	@printf 'checked executable bits\n'

uninstall:
	@set -eu; \
	for path in $(LINKS); do \
		src="$(REPO)/$$path"; \
		dst="$(PREFIX)/$$path"; \
		if [ "$$(readlink "$$dst" 2>/dev/null || true)" = "$$src" ]; then \
			rm "$$dst"; \
			printf 'removed: %s\n' "$$dst"; \
		fi; \
	done

clean:
	@rm -rf .cache .local/state
	@printf 'cleaned generated state\n'

lint:
	@set -eu; \
	for file in install.sh scripts/*.sh $(SHELL_SCRIPTS); do \
		[ -f "$$file" ] || continue; \
		sh -n "$$file"; \
	done
	@python3 -c 'import ast, pathlib; [ast.parse(path.read_text()) for path in pathlib.Path(".local/bin").glob("*.py")]'
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck install.sh scripts/*.sh $(SHELL_SCRIPTS); fi
	@if command -v mandoc >/dev/null 2>&1; then mandoc -Tascii man/*.1 >/dev/null; fi
	@printf 'syntax checks passed\n'

test:
	@python3 tests/test-waybar-applets.py
	@python3 tests/test-waybar-weather.py
	@sh tests/test-waybar-transient-control.sh
	@sh tests/test-wayland-autostart.sh

check: lint test

smoke: check
	@./install.sh --help >/dev/null
	@./install.sh --list >/dev/null
	@./install.sh --dry-run --no-deps --all >/dev/null
	@./install.sh --dry-run --uninstall --dots >/dev/null
	@printf 'installer smoke tests ok\n'

check-install:
	@set -eu; \
	tmp="$$(mktemp -d)"; \
	mkdir -p "$$tmp/.local/bin" "$$tmp/.local/share/keep"; \
	touch "$$tmp/.local/bin/existing-tool" "$$tmp/.local/share/keep/file"; \
	$(MAKE) PREFIX="$$tmp" install >/dev/null; \
	test -e "$$tmp/.local/bin/existing-tool"; \
	test -e "$$tmp/.local/share/keep/file"; \
	test "$$(readlink "$$tmp/.config/sway")" = "$(REPO)/.config/sway"; \
	test "$$(readlink "$$tmp/.config/gtk-3.0/settings.ini")" = "$(REPO)/.config/gtk-3.0/settings.ini"; \
	test "$$(readlink "$$tmp/.config/gtk-4.0/settings.ini")" = "$(REPO)/.config/gtk-4.0/settings.ini"; \
	test "$$(readlink "$$tmp/.config/waybar")" = "$(REPO)/.config/waybar"; \
	test "$$(readlink "$$tmp/.config/eww")" = "$(REPO)/.config/eww"; \
	test "$$(readlink "$$tmp/.local/bin/waybar-about-device")" = "$(REPO)/.local/bin/waybar-about-device"; \
	test "$$(readlink "$$tmp/.local/bin/waybar-cava")" = "$(REPO)/.local/bin/waybar-cava"; \
	test "$$(readlink "$$tmp/.local/bin/waybar-applets.py")" = "$(REPO)/.local/bin/waybar-applets.py"; \
	test "$$(readlink "$$tmp/.local/bin/waybar-weather.py")" = "$(REPO)/.local/bin/waybar-weather.py"; \
	test "$$(readlink "$$tmp/.local/share/applications/pympress.desktop")" = "$(REPO)/.local/share/applications/pympress.desktop"; \
	test "$$(readlink "$$tmp/.local/bin/wayland-session")" = "$(REPO)/.local/bin/wayland-session"; \
	test "$$(readlink "$$tmp/.local/bin/wayland-actions")" = "$(REPO)/.local/bin/wayland-actions"; \
	test "$$(readlink "$$tmp/.local/bin/wayland-autostart")" = "$(REPO)/.local/bin/wayland-autostart"; \
	test "$$(readlink "$$tmp/.local/bin/wayland-sway-watch")" = "$(REPO)/.local/bin/wayland-sway-watch"; \
	test "$$(readlink "$$tmp/.local/bin/sway-bindings")" = "$(REPO)/.local/bin/sway-bindings"; \
	printf 'install check passed: %s\n' "$$tmp"

doctor:
	@.local/bin/wayland-system-doctor

status:
	@git status --short
