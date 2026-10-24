#!/bin/bash
# bootarea_run.sh —— L1.6（只读）：把 Round 9 定出来的 boot 区/头区目标 dump 回来。
# 跑在远端（相机所接的 Ubuntu，~/a7c-jiritsu）。全程只读：不 put/fput/fdel、不重启、不改旗标。
# 依据：
#  - Round 9：nflasha 分区表在 **USER 字节偏移 0**（= partinf 之前 64 KiB 头区第一 sector），
#    表不属于任何 nflashaN 分区 ⇒ 只能用裸节点 /dev/nflasha（252:0=整块 USER 区）读。
#  - 两个根文件系统里都有静态节点 /dev/nflashaB0 / nflashaB1（= eMMC BOOT1/BOOT2，EXBL 所在）。
#  - 目的：回答「EXBL 怎么校验 boot/vmlinux.bin + boot/initrd.img」——p1chksum 是纯文本 MD5 清单，
#    且在 initrd 与 a15(/usr) 里 0 处引用 ⇒ 只有 EXBL 读它。这决定「改 a1 里 sauu」是 R1 还是 R0。
set -u -x
D=${D:-$HOME/a7c-jiritsu/bootarea}
TOOL=${TOOL:-$HOME/a7c-jiritsu/jiritsu_send.py}
mkdir -p "$D"
LOG="$D/run.log"
exec > >(tee -a "$LOG") 2>&1
date -u

# 0) 开工自检（不带 --devs：B0/B1/裸 nflasha 不是 partinf 分区，别被备份清单判死）
python3 "$TOOL" preflight || { echo 'PREFLIGHT 不过 —— 停，先看输出'; exit 1; }

# 1) 先确认节点在不在（只读，一次 512B 试探：失败就报 FileControl 状态码，不重试）
for n in nflashaB0 nflashaB1 nflasha; do
  echo "=== 试探 /dev/$n（fget 读全设备，nflasha 是全 USER 区 1.288GiB，别在这一步做）==="
  if [ "$n" = nflasha ]; then echo '  跳过（太大，见第 3 步）'; continue; fi
  python3 "$TOOL" fget "/dev/$n" --out "$D/probe_$n.bin" || echo "  /dev/$n 读失败（记下状态码，别重试）"
done

# 2) 正式 dump：两次独立读比 sha（B0/B1 长度未知 —— 首次读到的长度就是 ground truth，写进 BACKUP_MANIFEST）
for n in nflashaB0 nflashaB1; do
  echo "=== dump /dev/$n（两次）==="
  python3 "$TOOL" dump "$n" --out "$D/$n.bin" --twice 2 || echo "  /dev/$n dump 失败"
done

# 3) 可选：整块 USER 区（含 64KiB 头区 + 分区表）。1.288 GiB，约 100 秒/次；只在 1) 2) 都顺利时做。
if [ "${WHOLE:-0}" = 1 ]; then
  echo "=== dump /dev/nflasha（整块 USER 区，单次读）==="
  python3 "$TOOL" dump nflasha --out "$D/nflasha_user.bin" --twice 1 || echo '  整区读失败'
fi

date -u
echo '完成。把 bootarea/ 同步回本机 work/l3-camera/，并把 B0/B1 的长度+sha 写进 work/BACKUP_MANIFEST.tsv'
