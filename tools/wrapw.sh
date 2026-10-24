#!/usr/bin/env bash
# wrapw.sh — 本机「写」包装：★不重试★（与远端 ~/a7c-jiritsu/wrap2.sh 的关键差异）。
#
# 为什么不用 wrap2.sh 做写：
#   wrap2.sh 对任何 rc≠0 重试 5 次。对读无所谓；对写 = “同一个文件可能被写 1–5 次”，
#   而且 rc≠0 可能只是响应超时 —— 相机侧也许已经落盘，重发就是第二次写。
#   写路径（FileControl cmd=1 / SET_FILE2）在相机侧是否幂等没有任何证据。
# 本包装的原则：
#   1) 先 preflight（六项自检，mock 下用 work/mock* 本地文件）；
#   2) 写前 fget 定状态：目标已存在且有内容 => 拒绝（残留/旧 zzprobe 不得静默覆盖；确要覆盖 FORCE=1）；
#   3) fput 只发一次，失败即停，不重发（停下来先 fget 判到底写没写进去、写了多少）；
#   4) fput 后必须 fget 记录实际字节数+sha256，与源不符（部分写/读回少字节）=> exit 1。
# 用法（全部走环境变量，写级别默认 L2.5 = 只允许 zzprobe 白名单）：
#   REMOTE=/tmp/zzprobe1 SRC=/tmp/zzprobe1.txt [LEVEL=L2.5] [MOCKDIR=work/mock-faults] [FORCE=1] bash tools/wrapw.sh
set -u
cd "$(dirname "$0")/.."
TOOL=(python3 tools/jiritsu_send.py)
REMOTE="${REMOTE:?REMOTE=<机身目标路径，须在 --level 白名单内>}"
SRC="${SRC:?SRC=<本地源文件>}"
LEVEL="${LEVEL:-L2.5}"
LOG="work/wrapw.log"; mkdir -p "$(dirname "$LOG")"
say(){ echo "[wrapw] $*" | tee -a "$LOG"; }
[ -f "$SRC" ] || { say "FAIL: 源文件不存在 $SRC"; exit 1; }
EXTRA=()
if [ -n "${MOCKDIR:-}" ]; then EXTRA+=(--mock --mock-dir "$MOCKDIR"); fi

# 1) 开工自检（含设备身份/FW 版本/工具 sha/备份清单/mode 旗标/RO-RW 声明）
"${TOOL[@]}" ${EXTRA[@]+"${EXTRA[@]}"} --allow-write --level "$LEVEL" preflight >>"$LOG" 2>&1 \
  || { say "FAIL: preflight（详见 $LOG）"; exit 1; }

# 2) 写前 fget 定状态：能读到且有内容 = 目标已存在 => 停（不得静默覆盖）
BEFORE="$(mktemp "wrapw-before.XXXXXX")"
if "${TOOL[@]}" ${EXTRA[@]+"${EXTRA[@]}"} fget "$REMOTE" "$BEFORE" >/dev/null 2>&1 && [ -s "$BEFORE" ]; then
  if [ "${FORCE:-0}" = "1" ]; then
    say "注意：目标 $REMOTE 已存在（$(wc -c <"$BEFORE" | tr -d ' ') B），FORCE=1 继续"
  else
    say "FAIL: $REMOTE 已存在（$(wc -c <"$BEFORE" | tr -d ' ') B）—— 旧 zzprobe/残留，不静默覆盖；先查明来源，fdel 或 FORCE=1"
    rm -f "$BEFORE"; exit 2
  fi
else
  say "写前状态：$REMOTE 读不到/不存在（fget 非 0 或空）"
fi

# 3) 恰好一次 fput：★失败不重试★。超时≠没写进去 —— 停下来人工 fget 定状态
"${TOOL[@]}" ${EXTRA[@]+"${EXTRA[@]}"} --allow-write --level "$LEVEL" fput "$REMOTE" "$SRC" >>"$LOG" 2>&1
 frc=$?
if [ $frc -eq 4 ]; then
  say "边界探针意外成功：$REMOTE 竞可写（非预期）—— 已 exit 4 停序列；尝试清理探针残留 fdel"
  "${TOOL[@]}" ${EXTRA[@]+"${EXTRA[@]}"} --allow-write --level "$LEVEL" fdel "$REMOTE" >>"$LOG" 2>&1 \
    || say "⚠ 残留清理失败：$REMOTE 留在机身里，手工处理后再继续"
  exit 4
fi
if [ $frc -ne 0 ]; then
  say "FAIL: fput 失败且【不重试】—— 先手动 fget $REMOTE 判状态（可能已部分落盘），再决定下一步"
  rm -f "$BEFORE"; exit 1
fi

# 4) 写后必须 fget：记录实际字节数 + sha，与源比对；不符 = 部分写/读回异常 => 序列断在这
AFTER="$(mktemp "wrapw-after.XXXXXX")"
"${TOOL[@]}" ${EXTRA[@]+"${EXTRA[@]}"} fget "$REMOTE" "$AFTER" >/dev/null 2>&1 \
  || { say "FAIL: 写后 fget 读不回（写状态未知！别再写第二次）"; rm -f "$BEFORE"; exit 1; }
sb=$(wc -c <"$SRC" | tr -d ' '); sa=$(wc -c <"$AFTER" | tr -d ' ')
ssha=$(shasum -a 256 "$SRC" | cut -d' ' -f1); asha=$(shasum -a 256 "$AFTER" | cut -d' ' -f1)
say "记录：$REMOTE src=${sb}B sha=${ssha:0:16}…  读回=${sa}B sha=${asha:0:16}…"
if [ "$sb" != "$sa" ] || [ "$ssha" != "$asha" ]; then
  say "FAIL: 读回字节数/内容与源不符（部分写 或 读回少字节）—— 停，别自动重写"
  rm -f "$BEFORE" "$AFTER"; exit 1
fi
rm -f "$BEFORE" "$AFTER"
say "OK: 单次写 + 读回一致"
