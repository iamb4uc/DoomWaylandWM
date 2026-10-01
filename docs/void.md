# Void Linux

Install package support and symlinked configs:

```sh
./install.sh --yes --all
```

Install only the configs:

```sh
./install.sh --yes --dots --no-deps
```

The current local Void package index provides Sway and the Wayland support tools
in `packages/void`, so this profile stays XBPS-native by default.

Check the expected runtime commands:

```sh
make doctor
```
