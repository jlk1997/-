#!/usr/bin/env bash
# Download the two Essentia models health.py looks for. Safe to re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${1:-$ROOT/models}"
mkdir -p "$MODELS_DIR"
BASE="${ESSENTIA_MODEL_BASE:-https://essentia.upf.edu/models}"
files=(
  "feature-extractors/discogs-effnet-bs64-1.pb"
  "classification-heads/mtg_jamendo_moodtheme-discogs-effnet-1.pb"
)
for rel in "${files[@]}"; do
  name="$(basename "$rel")"
  dest="$MODELS_DIR/$name"
  if [[ -f "$dest" ]]; then
    echo "exists $name"
    continue
  fi
  echo "download $name"
  curl -fsSL "$BASE/$rel" -o "$dest"
done
echo "models in $MODELS_DIR"
