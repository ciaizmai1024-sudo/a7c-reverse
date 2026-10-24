#!/bin/bash
# 用**相机自己的用户态**（busybox 1.29.3 / glibc 2.11.2 / armv7）离线跑东西。
# 做法：debian:buster-slim（glibc 的 arm/v7 镜像）里，用相机自带 ld.so + 自带库跑它自己的 ELF。
# 挂载：/cam = 相机 nflasha7 rootfs（只读）、/w = work/、/t = tools/。
#
# 用法：
#   tools/camuser.sh                      # 只打印相机 busybox 版本（自检）
#   tools/camuser.sh work/myscript.sh     # 在容器里跑脚本（脚本里先 . /t/camprefix.sh，然后用 BB / CAM）
# 例：work/t_tarcheck.sh:
#   . /t/camprefix.sh
#   BB tar tvf /w/jiritsu_firm.dat
#   rm -rf /tmp/jiritsu; mkdir -p /tmp/jiritsu
#   BB tar xpf /w/jiritsu_firm.dat ./ -C /tmp/jiritsu; echo "rc=$?"; ls -l /tmp/jiritsu
ROOT=firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked
IMG=debian:buster-slim
if [ ! -d "$ROOT" ]; then echo "找不到 $ROOT（先解 part_image/nflasha7）" >&2; exit 1; fi
if [ -z "$1" ]; then
  docker run --rm --platform linux/arm/v7 -v "$PWD/$ROOT":/cam:ro -v "$PWD/work":/w -v "$PWD/tools":/t:ro -w /w $IMG \
    sh -c '. /t/camprefix.sh; BB | head -1'
else
  shift 0
  docker run --rm --platform linux/arm/v7 -v "$PWD/$ROOT":/cam:ro -v "$PWD/work":/w -v "$PWD/tools":/t:ro -w /w $IMG \
    sh "/w/${1#work/}" "${@:2}"
fi
