#!/bin/sh
# 在容器内跑相机自己的 ud_datcnv.elf（nflasha15）+ 相机自己的 glibc（nflasha7）。
# 由 tools/datcnv.sh 挂载：/cam=nflasha7 rootfs(ro) /u=nflasha15(ro) /w=work/ /t=tools/
set -e
cp -r /cam /c >/dev/null 2>&1 || true
chmod -R +x /c/lib /c/bin 2>/dev/null || true
cd /c/lib
for p in "libc-2.11.2.so libc.so.6" "libm-2.11.2.so libm.so.6" "libdl-2.11.2.so libdl.so.2" \
         "libpthread-2.11.2.so libpthread.so.0" "librt-2.11.2.so librt.so.1" "libcrypt-2.11.2.so libcrypt.so.1" \
         "libnsl-2.11.2.so libnsl.so.1" "libresolv-2.11.2.so libresolv.so.2" "libutil-2.11.2.so libutil.so.1" \
         "libanl-2.11.2.so libanl.so.1" "libnss_files-2.11.2.so libnss_files.so.2" "libnss_dns-2.11.2.so libnss_dns.so.2" \
         "libnss_nis-2.11.2.so libnss_nis.so.2" "ld-2.11.2.so ld-linux.so.3" "libproc-3.2.7.so libproc.so.3.2.7"; do
  set -- $p; ln -sf "$1" "$2"
done
# 补 nflasha15 独有的库（libstdc++ / libgcc_s / libosal_*）
cp -n /u/lib/libstdc++.so.6.0.14 /c/lib/ 2>/dev/null || true
cp -n /u/lib/libosal_uipc.so /c/lib/ 2>/dev/null || true
[ -f /u/lib/libgcc_s.so.1 ] && cp -n /u/lib/libgcc_s.so.1 /c/lib/ || true
ls /c/lib/libgcc_s* /c/lib/libstdc* 2>/dev/null || echo "WARN: 缺 libgcc_s/libstdc++ in /cam:"; ls /cam/lib | grep -E 'stdc|gcc_s' || true
ln -sf libstdc++.so.6.0.14 /c/lib/libstdc++.so.6 2>/dev/null || true
LDR=/c/lib/ld-2.11.2.so
CNV() { $LDR --library-path /c/lib /u/bin/ud_datcnv.elf "$@"; }

mkdir -p /tmp/dc && cd /tmp/dc
echo "== ELF 自检 =="
CNV; echo "no-args rc=$?"
echo
echo "== 1) -e 编码 =="
for s in 0200 0100 0000 2.00 9103 0191 000000910319; do
  printf '%s' "$s" > in_$s.txt
  printf '%s\n' "$s" > innl_$s.txt
  CNV -e -i in_$s.txt -o enc_$s.bin -a; echo "  -e -a '$s' rc=$? size=$(wc -c < enc_$s.bin 2>/dev/null)"
  CNV -e -i in_$s.txt -o encn_$s.bin ; echo "  -e    '$s' rc=$? size=$(wc -c < encn_$s.bin 2>/dev/null)"
done
echo "-- hexdump（-a 版）--"
for f in enc_*.bin; do echo "-- $f"; od -An -tx1 -v $f; done
echo "-- hexdump（无 -a 版）--"
for f in encn_*.bin; do echo "-- $f"; od -An -tx1 -v $f; done
echo
echo "== 2) 往返 -d =="
for f in enc_*.bin; do echo "-- $f -a"; CNV -d -i $f -o out.txt -a; echo "rc=$? bytes=$(wc -c < out.txt)"; od -An -tx1 -c -v out.txt; done
for f in encn_*.bin; do echo "-- $f 无a"; CNV -d -i $f -o outn.txt; echo "rc=$? bytes=$(wc -c < outn.txt)"; od -An -tx1 -c -v outn.txt; done
echo
echo "== 3) -a vs 无 -a：同输入两两 cmp =="
for s in 0200 0100 0000 2.00; do echo "-- $s"; cmp -l enc_$s.bin encn_$s.bin && echo "  完全相同"; done
echo "-- 真实 dat 文件（/u 里若存在）--"
ls -l /u/../ 2>/dev/null | head -3
for f in /u/dat2 /u/dat3 /u/dat4 /u/updater/dat2 /u/updater/dat3 /u/updater/dat4; do [ -f "$f" ] && { echo "== $f"; od -An -tx1 -v $f; }; done
echo "-- 用 -d 解真实 dat（只读，写到 /tmp）--"
for f in /u/dat2 /u/dat3 /u/dat4 /u/updater/dat2 /u/updater/dat3 /u/updater/dat4; do [ -f "$f" ] && { echo "== $f"; CNV -d -i $f -o dec.txt -a; echo rc=$?; od -An -tx1 -c -v dec.txt; }; done
echo
echo "== 4) 校验：改 1 个字节后 -d =="
cp enc_0200.bin tamper.bin
printf '\x31' | dd of=tamper.bin bs=1 seek=1 count=1 conv=notrunc status=none
od -An -tx1 -v tamper.bin
CNV -d -i tamper.bin -o tout.txt -a; echo "rc=$?"; od -An -tx1 -c -v tout.txt
echo "-- 长度实验：编码 4/8/12 字符输入，看是否固定长度 --"
for s in 0200 02000200 020002000200 abcde 02; do printf '%s' "$s" > L_$s.txt; CNV -e -i L_$s.txt -o Lb_$s.bin -a; echo "'$s' in=$(wc -c < L_$s.txt) out=$(wc -c < Lb_$s.bin 2>/dev/null) :"; od -An -tx1 -v Lb_$s.bin 2>/dev/null; done
