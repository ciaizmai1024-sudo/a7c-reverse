#!/bin/bash
DF=/opt/homebrew/opt/e2fsprogs/sbin/debugfs
IMG=$1; OUT=$2; shift 2
mkdir -p "$OUT"
for p in "$@"; do
  base=$(basename "$p")
  $DF -R "dump $p $OUT/$base" "$IMG" >/dev/null 2>&1
  if [ -f "$OUT/$base" ]; then echo "OK $p ($(stat -f%z "$OUT/$base"))"; else echo "MISS $p"; fi
done
