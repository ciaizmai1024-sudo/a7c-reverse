#!/usr/bin/env bash
# L2.5a/2.5b 真机写探针驱动。全程 tee 到 ~/a7c-jiritsu/l25.log
set -u
cd ~/a7c-jiritsu
D=~/a7c-jiritsu/l25
mkdir -p $D
exec > >(tee -a ~/a7c-jiritsu/l25.log) 2>&1
w1() { TMO=${1:-200}; shift; TMO=$TMO bash ~/a7c-jiritsu/wrap1.sh "$@"; }
sh16() { sha256sum "$1" | cut -c1-16; }
relax() { echo zzz888ZZZ | sudo -S -p "" chmod -R a+r $D 2>/dev/null; }
w2() { TMO=${1:-200}; shift; TMO=$TMO bash ~/a7c-jiritsu/wrap2.sh "$@"; }
step() { echo; echo "########## $1 $(date +%H:%M:%S) ##########"; }

step "S0 lsusb"
lsusb | grep 054c || { echo "FATAL: 054c:0d29 不在，停"; exit 1; }

step "S1 mount (Jiritsu 0x4002)"
w2 200 tools/jiritsu_send.py mount

step "S2 baseline reads"
w2 300 tools/jiritsu_send.py fget /setting/updater/comp $D/base_comp.bin
w2 300 tools/jiritsu_send.py fget /setting/updater/dat4 $D/base_dat4.bin
echo "  dat4 hex: $(xxd -p $D/base_dat4.bin 2>/dev/null | tr -d '\n')  size=$(stat -c%s $D/base_dat4.bin 2>/dev/null)"
w2 300 tools/jiritsu_send.py fget /tmp/nsswitch.conf $D/base_nsswitch.bin
w2 300 tools/jiritsu_send.py fget /setting/updater/zzprobe $D/base_zzprobe.bin
w2 300 tools/jiritsu_send.py fget /setting/updater/mode $D/base_mode.bin
relax

step "S3 before dumps (nflasha2 20MB / nflasha10 12MB, --twice 1)"
w2 600 tools/jiritsu_send.py dump nflasha2 $D/before_a2.bin --twice 1
w2 600 tools/jiritsu_send.py dump nflasha10 $D/before_a10.bin --twice 1
relax
echo "  before_a2 sha16=$(sh16 $D/before_a2.bin)  before_a10 sha16=$(sh16 $D/before_a10.bin)"

step "S4 payload + L2.5a fput /tmp/zzprobe"
python3 - <<'EOF'
import hashlib, time
ep = int(time.time())
pre = ("A7C-L25-%d-HELLO-WRITE-PATH-PAD" % ep)[:32].ljust(32, '.')
full = pre + hashlib.sha256(pre.encode()).hexdigest()[:8].encode()
assert len(full) == 40, len(full)
open('/home/wubin/a7c-jiritsu/l25/zz.bin', 'wb').write(full)
print('  payload:', full, ' len=', len(full))
EOF
echo "  zz.bin sha=$(sha256sum $D/zz.bin)"
w1 200 tools/fput_raw.py /tmp/zzprobe $D/zz.bin
w2 300 tools/jiritsu_send.py fget /tmp/zzprobe $D/rb_a10.bin
relax
cmp $D/zz.bin $D/rb_a10.bin && echo "  L2.5a 读回 cmp: 一致 rc=0" || echo "  L2.5a 读回 cmp: 不一致 rc=$?"
echo "  rb_a10 sha16=$(sh16 $D/rb_a10.bin)  zz sha16=$(sh16 $D/zz.bin)"

step "S5 L2.5b fput /setting/updater/zzprobe"
w1 200 tools/fput_raw.py /setting/updater/zzprobe $D/zz.bin
w2 300 tools/jiritsu_send.py fget /setting/updater/zzprobe $D/rb_a2.bin
relax
cmp $D/zz.bin $D/rb_a2.bin && echo "  L2.5b 读回 cmp: 一致 rc=0" || echo "  L2.5b 读回 cmp: 不一致 rc=$?"
echo "  rb_a2 sha16=$(sh16 $D/rb_a2.bin)"

step "S6 after dumps + diff"
w2 600 tools/jiritsu_send.py dump nflasha2 $D/after_a2.bin --twice 1
w2 600 tools/jiritsu_send.py dump nflasha10 $D/after_a10.bin --twice 1
echo "  after_a2 sha16=$(sh16 $D/after_a2.bin)  after_a10 sha16=$(sh16 $D/after_a10.bin)"
relax
python3 tools/l25_diff.py $D/before_a10.bin $D/after_a10.bin nflasha10 ZZPROBE zzprobe
python3 tools/l25_diff.py $D/before_a2.bin $D/after_a2.bin nflasha2 ZZPROBE zzprobe

step "S7 副作用复查"
w2 300 tools/jiritsu_send.py fget /setting/updater/comp $D/after_comp.bin
w2 300 tools/jiritsu_send.py fget /setting/updater/dat4 $D/after_dat4.bin
w2 300 tools/jiritsu_send.py fget /tmp/nsswitch.conf $D/after_nsswitch.bin
w2 300 tools/jiritsu_send.py fget /setting/updater/zzprobe $D/probe_again.bin
w2 300 tools/jiritsu_send.py fget /setting/updater/mode $D/mode_again.bin
relax
for f in comp dat4 nsswitch; do
  cmp $D/base_$f.bin $D/after_$f.bin 2>&1 && echo "  复查 $f: 前后一致" || echo "  复查 $f: 有差异/缺失 !!"
done
echo "  dat4 after hex: $(xxd -p $D/after_dat4.bin 2>/dev/null | tr -d '\n')  size=$(stat -c%s $D/after_dat4.bin 2>/dev/null)"

step "S8 边界 fput /usr/lib/zzprobe (预期失败 EROFS)"
w1 200 tools/fput_raw.py /usr/lib/zzprobe $D/zz.bin

step "S9 Plan B: Jiritsu SET_FILE2(0x4010) put /tmp/jiritsu/zzprobe"
w2 200 tools/jiritsu_send.py put /tmp/jiritsu/zzprobe $D/zz.bin
w2 300 tools/jiritsu_send.py get /tmp/jiritsu/zzprobe $D/rb_jir.bin
relax
cmp $D/zz.bin $D/rb_jir.bin && echo "  Plan B 读回 cmp: 一致 rc=0" || echo "  Plan B 读回 cmp: 不一致 rc=$?"
echo "  rb_jir sha16=$(sh16 $D/rb_jir.bin)"

step "S9.5 覆盖语义实验：fput /tmp/zzprobe 第二份不同内容(44B)后读回"
python3 -c "
pre=('A7C-L25-OVERWRITE2-%d-' % 1234567890)[:36].ljust(36,'.');
open('/home/wubin/a7c-jiritsu/l25/zz2.bin','wb').write(pre+b'2222')"
w1 200 tools/fput_raw.py /tmp/zzprobe $D/zz2.bin
w2 300 tools/jiritsu_send.py fget /tmp/zzprobe $D/rb_a10_b.bin
relax
echo "  size after 2nd write: $(stat -c%s $D/rb_a10_b.bin 2>/dev/null)  (zz.bin=40, zz2.bin=$(stat -c%s $D/zz2.bin 2>/dev/null))"
cmp $D/zz2.bin $D/rb_a10_b.bin && echo "  覆盖语义: 截断覆盖(=新内容)" || echo "  覆盖语义: 非截断，见上 size 与 hexdump:"
xxd $D/rb_a10_b.bin 2>/dev/null | head -5
echo "  恢复 40B 标志内容："
w1 200 tools/fput_raw.py /tmp/zzprobe $D/zz.bin

step "S10 收尾：恢复原始 zzprobe(40B) 状态确认 + 权限"
w2 300 tools/jiritsu_send.py fget /tmp/zzprobe $D/rb_a10_final.bin
relax
cmp $D/zz.bin $D/rb_a10_final.bin && echo "  最终 /tmp/zzprobe = 原 40B 载荷" || echo "  !! 最终读回不等于原载荷"
echo zzz888ZZZ | sudo -S -p "" chmod -R a+r $D 2>/dev/null
echo zzz888ZZZ | sudo -S -p "" chown -R wubin:wubin $D 2>/dev/null
ls -la $D
echo "ALLDONE $(date +%H:%M:%S)"
