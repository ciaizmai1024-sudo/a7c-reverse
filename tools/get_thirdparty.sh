#!/usr/bin/env bash
# 重建 refs/（第三方参考仓库，版权归各自作者；本仓库不入库）。
# 用法: tools/get_thirdparty.sh [目标目录，默认 ./refs]
set -euo pipefail

cd "$(dirname "$0")/.."
DEST="${1:-refs}"
mkdir -p "$DEST"

clone() { # clone <url> <目录名>
  local url="$1" dir="$2"
  if [ -d "$DEST/$dir/.git" ]; then
    echo "已有 $DEST/$dir，跳过"
    return
  fi
  echo "-> $DEST/$dir"
  git clone --depth 1 "$url" "$DEST/$dir"
}

# 容器格式 / 公开密钥表 / updatershell
clone https://github.com/ma1co/fwtool.py            fwtool.py
clone https://github.com/ma1co/Sony-PMCA-RE         Sony-PMCA-RE
# 同芯片（CXD90045）的 QEMU / 救援工作
clone https://github.com/cokeenet/zve10-qemu        zve10-qemu
# A7C II 已商用的改功能工具（含 issue 里的真机 root 报告）
clone https://github.com/QAQLeonard/a7c2-fl23-research a7c2-fl23-research
# DAT/FDAT 格式与三层校验
clone https://github.com/Lost-week-1025/CXD90045-FPSU  CXD90045-FPSU
# 同芯片真机工具链（cam.py / dump_flash / ARM32 libJit 载荷）
clone https://github.com/nolan2628/Sony-ZVE-10-Camtool Sony-ZVE-10-Camtool

# CXD90045 板级模型（不需要整仓库，取一个文件就够）：
#   curl -o /tmp/bionz.c https://raw.githubusercontent.com/ma1co/qemu/master/hw/arm/bionz.c
echo
echo "完成。注意：CXD90045 的多把 FDAT AES 密钥在 fwtool.py 的 PR #52（master 只有 k0）："
echo "  cd $DEST/fwtool.py && git fetch origin pull/52/head:pr52 && git checkout pr52"
