#!/usr/bin/env bash
# mock_faults.sh — 阶段 1：mock 故障矩阵。每种故障都必须【真的停止】：退出码非 0 / 序列中断，
# 不是只打印警告。全部离线（--mock），不碰 USB/相机。mock 根用 work/mock-faults（独立，不污染 work/mock）。
set -u
cd "$(dirname "$0")/../.."
T=tools/jiritsu_send.py
M=work/mock-faults
SRC=/tmp/mock_faults_payload.txt
PASS=0; FAIL=0
head -c 512 /dev/urandom > "$SRC"

newmock(){ rm -rf "$M"; mkdir -p "$M"; python3 "$T" --mock --mock-dir "$M" mount >/dev/null 2>&1 \
           || { echo "FATAL: 播种 mock 失败"; exit 1; } }

# t <名称> <ZERO|NONZERO> <必须出现在输出里的 grep 模式> <工具参数…>
t(){ local name=$1 exp=$2 mark=$3; shift 3
  local out rc ok
  out=$(python3 "$T" --mock --mock-dir "$M" "$@" 2>&1); rc=$?
  ok=1
  [ "$exp" = NONZERO ] && [ $rc -eq 0 ] && ok=0
  [ "$exp" = ZERO ] && [ $rc -ne 0 ] && ok=0
  [ -n "$mark" ] && ! printf '%s' "$out" | grep -q "$mark" && ok=0
  if [ $ok = 1 ]; then PASS=$((PASS+1)); echo "PASS  $name  (rc=$rc)"
  else FAIL=$((FAIL+1)); echo "FAIL  $name  (rc=$rc, 期望 $exp${mark:+, 且输出含 /$mark/})"
    printf '%s\n' "$out" | sed 's/^/        | /' | head -8; fi
}
# rcbash <名称> <期望rc非0> <grep 模式> <命令…>（跑 wrapw.sh 这类外部命令）
rcb(){ local name=$1 mark=$2; shift 2
  local out rc ok
  out=$("$@" 2>&1); rc=$?
  ok=1; [ $rc -eq 0 ] && ok=0
  [ -n "$mark" ] && ! printf '%s' "$out" | grep -q "$mark" && ok=0
  if [ $ok = 1 ]; then PASS=$((PASS+1)); echo "PASS  $name  (rc=$rc)"
  else FAIL=$((FAIL+1)); echo "FAIL  $name  (rc=$rc, 期望非0${mark:+, 输出含 /$mark/})"
    printf '%s\n' "$out" | sed 's/^/        | /' | head -8; fi
}

echo '== 0) 健康基线：正常 mock 下 preflight 必须 PASS（否则后面全不可信）=='
newmock; t 'baseline preflight' ZERO 'PREFLIGHT PASS' preflight

echo '== 1) 写没有 --allow-write → 拒绝 =='
newmock
t 'fput 无 --allow-write' NONZERO '默认 RO' fput /tmp/zzprobe1 "$SRC"
t 'put 无 --allow-write' NONZERO '默认 RO' put /tmp/jiritsu/zzprobe1 "$SRC"
t 'fdel 无 --allow-write' NONZERO '默认 RO' fdel /tmp/zzprobe1
t 'del 无 --allow-write' NONZERO '默认 RO' del /tmp/jiritsu/zzprobe1

echo '== 2) 白名单外路径 → 拒绝 =='
newmock
t 'fput /usr/bin/up.sh' NONZERO '白名单' --allow-write --level L2.5 fput /usr/bin/up.sh "$SRC"
t 'fput /setting/updater/comp' NONZERO '白名单' --allow-write --level L2.5 fput /setting/updater/comp "$SRC"
t 'fput 未知级别' NONZERO '不在级别表' --allow-write --level L9 fput /tmp/zzprobe1 "$SRC"

echo '== 3) 危险 opcode（jir 0x4003 FORMAT）→ 拒绝 =='
newmock
t 'jir 0x4003 无 --i-know-what-im-doing' NONZERO '危险 opcode 黑名单硬挡' jir 0x4003
t 'jir 0x4004 START' NONZERO '危险 opcode 黑名单硬挡' jir 0x4004
t 'jir 0x4006 带 --i-know-what-im-doing 可发' ZERO '⚠⚠' jir 0x4006 --i-know-what-im-doing

echo '== 4) 设备身份不符（bcdDevice 0x203）→ preflight 失败 =='
newmock
printf 'idVendor\t0x054c\nidProduct\t0x0d29\nbcdDevice\t0x0203\nproduct\tILCE-7C\n' > "$M/device_desc.tsv"
t 'preflight bcd 0x0203' NONZERO '\[1\]' preflight
printf 'idVendor\t0x054c\nidProduct\t0x0d2a\nbcdDevice\t0x0200\nproduct\tILCE-7C\n' > "$M/device_desc.tsv"
t 'preflight PID 0d2a(MTP)' NONZERO '\[1\]' preflight

echo '== 5) dat4=00 03（版本不符）→ preflight 失败 =='
newmock
printf '\x00\x03' > "$M/fs/setting_updater_dat4"
t 'preflight dat4=00 03' NONZERO '\[2\] dat4=0003' preflight

echo '== 6) /setting/updater/mode 存在 → preflight 失败 =='
newmock
echo '1' > "$M/fs/setting_updater_mode"
t 'preflight mode 旗标残留' NONZERO 'mode 旗标残留' preflight

echo '== 7) 分区镜像截短（mock /dev/nflasha7 只给 4096B）→ dump 判失败 =='
newmock
mkdir -p "$M/dev"; head -c 4096 /dev/urandom > "$M/dev/nflasha7"
t 'dump 截短 nflasha7' NONZERO 'dump 失败' dump nflasha7 "$M/out_a7.bin"

echo '== 8) 部分写/读回少字节（MOCK_TRUNC_READ=7）→ 写序列 exit 1 =='
newmock
rcb 'wrapw 读回少 7B → 停' '读回字节数/内容与源不符' \
    env MOCKDIR=$M MOCK_TRUNC_READ=7 REMOTE=/tmp/zzprobe1 SRC="$SRC" bash tools/wrapw.sh

echo '== 9) 旧 zzprobe 残留（mock 预置）→ 探针必须先报告已存在，不得静默覆盖 =='
newmock
echo 'OLD-RESIDUE-not-yours' > "$M/fs/tmp_zzprobe1"
rcb 'wrapw 遇预置 zzprobe → 拒覆盖' '已存在' \
    env MOCKDIR=$M REMOTE=/tmp/zzprobe1 SRC="$SRC" bash tools/wrapw.sh

echo '== 10) 工具 sha 不符（临时改 work/TOOL_HASH）→ preflight 失败 =='
newmock
cp work/TOOL_HASH work/TOOL_HASH.bak.mockfaults
printf 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef  tools/jiritsu_send.py\n' > work/TOOL_HASH
t 'preflight 工具 sha 不符' NONZERO '\[3\] 工具 sha 不符' preflight
mv work/TOOL_HASH.bak.mockfaults work/TOOL_HASH

echo
echo "== 结果：PASS=$PASS FAIL=$FAIL =="
[ $FAIL -eq 0 ] || exit 1
