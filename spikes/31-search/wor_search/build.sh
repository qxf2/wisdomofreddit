#!/bin/sh
# Needs Rust >= 1.94 (rustup) and maturin. Build output goes to the big drive.
set -e
cd "$(dirname "$0")"
export CARGO_TARGET_DIR=/Volumes/Expansion/code/spike31/target
../venv/bin/pip install -q "maturin>=1.9,<2"
export VIRTUAL_ENV=/Volumes/Expansion/code/spike31/venv
time ../venv/bin/maturin develop --release
du -sh "$CARGO_TARGET_DIR"
