#!/usr/bin/env bash
# Cloud Agent bootstrap for the MPC3000 Vailixi 3.50 ROM research pack.
#
# This is a pure-stdlib Python project: there are no third-party packages to
# install. "Setup" means proving the toolchain and the pinned ROM identity are
# intact, then regenerating the source-derived linear image. The script is
# idempotent and safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."

python3 --version

# Verify the pinned Vailixi 3.50 linear identity and the reset-to-LCD boot slice.
python3 tools/verify_boot_slice.py
python3 -m unittest tests.test_boot_slice -v

# Regenerate the interleaved 512 KiB linear image into the gitignored build/ dir.
mkdir -p build
python3 -c "from tools.linear_rom import load_vailixi_linear; open('build/vailixi350.bin','wb').write(load_vailixi_linear())"

echo "Environment ready: build/vailixi350.bin regenerated and boot-slice facts verified."
