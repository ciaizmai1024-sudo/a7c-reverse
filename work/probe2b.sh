#!/bin/bash
# B) 路径存在性/大小矩阵 (FileControl 0xff01 fget) —— 只读
cd ~/a7c-jiritsu
mkdir -p probe2 && cd probe2
paths="/setting/updater/mode
/setting/updater/mode1
/setting/updater/mode2
/setting/updater/mode3
/setting/updater/mode4
/setting/updater/mode5
/setting/updater/mode6
/setting/updater/comp
/setting/updater/uincomp
/setting/updater/debug
/setting/updater/dat4
/setting/updater/version.txt
/setting/updater/kikilog.dat
/setting/Backup.bin
/setting/updater/Backup.bin
/setting/partinf.conf
/setting/mount.conf
/setting/kemco.txt
/usr/bin/crypter.elf
/usr/bin/udtrbody.bin
/usr/bin/up.sh
/usr/bin/mf
/usr/bin/sauu
/tmp/jiritsu
/tmp/jiritsu/libJit.so
/tmp/jbusy
/tmp/etc/nsswitch.conf"
for p in $paths; do
  loc=$(echo "$p" | sed 's#/#_#g').bin
  echo "=== $p"
  echo zzz888ZZZ | sudo -S -p "" env PYTHONDONTWRITEBYTECODE=1 timeout 90 python3 ../tools/jiritsu_send.py fget "$p" "$loc" 2>&1 | tail -3
  ls -l "$loc" 2>/dev/null
done | tee path_matrix.log 2>&1
echo "=== DIR LISTING ==="
ls -l ~/a7c-jiritsu/probe2
