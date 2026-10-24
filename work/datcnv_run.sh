#!/bin/bash
# 一次性：在 debian:buster-slim (arm/v7) 里跑 nflasha15 的 ud_datcnv.elf，glibc 用 nflasha7 的。
ROOT7=firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked
ROOT15=firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked
IMG=debian:buster-slim
docker run --rm --platform linux/arm/v7 \
  -v "$PWD/$ROOT7":/cam:ro -v "$PWD/$ROOT15":/u:ro -v "$PWD/work":/w -v "$PWD/tools":/t:ro \
  -w /w $IMG sh "$@"
