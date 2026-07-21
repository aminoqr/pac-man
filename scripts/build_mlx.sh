#!/usr/bin/env bash
# Build the 42 MiniLibX (mlx_CLXV) Python wheel from source.
#
# The repo vendors a prebuilt mlx-*-py3-none-any.whl for Linux x86_64
# (it bundles a compiled libmlx.so). Run this only when that wheel does
# not match your machine (different arch/OS) or you want to regenerate
# it. The freshly built wheel is copied to the repo root, replacing the
# vendored one, so `make install` (which pip-installs ./mlx-*.whl) then
# picks it up.
#
# Build dependencies (Debian/Ubuntu names; XCB backend):
#   clang  libvulkan-dev  zlib1g-dev  libxcb1-dev  libxcb-keysyms1-dev
#   libbsd-dev
# macOS uses the AppKit backend (Xcode CLT + a Vulkan/MoltenVK runtime).
set -e

MLX_REPO="https://github.com/42school/mlx_CLXV"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

echo "Cloning $MLX_REPO ..."
git clone --depth 1 "$MLX_REPO" "$BUILD_DIR/mlx_CLXV"
cd "$BUILD_DIR/mlx_CLXV"

echo "Configuring (auto-detect backend) ..."
./configure.sh

echo "Building the library + Python wheel ..."
make

WHEEL="$(ls mlx-*-py3-none-any.whl | head -n1)"
if [ -z "$WHEEL" ]; then
    echo "error: no wheel was produced by 'make'." >&2
    exit 1
fi

# Drop any stale vendored wheels, then install the fresh one.
rm -f "$REPO_ROOT"/mlx-*-py3-none-any.whl
cp "$WHEEL" "$REPO_ROOT/"
echo "Built and vendored $REPO_ROOT/$(basename "$WHEEL")"
echo "Now run 'make install' (or pip install ./$(basename "$WHEEL"))."
