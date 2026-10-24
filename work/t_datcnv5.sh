#!/bin/sh
# 第五轮：退出码 / 上限 / 往返一致性 / 大文件解码
cp -r /cam /c >/dev/null 2>&1 || true
chmod -R +x /c/lib >/dev/null 2>&1
cd /c/lib
for p in "libc-2.11.2.so libc.so.6" "libm-2.11.2.so libm.so.6" "libdl-2.11.2.so libdl.so.2" \
         "libpthread-2.11.2.so libpthread.so.0" "librt-2.11.2.so librt.so.1" "ld-2.11.2.so ld-linux.so.3"; do
  set -- $p; ln -sf "$1" "$2"; done
cp /u/lib/libstdc++.so.6.0.14 /c/lib/ 2>/dev/null; ln -sf libstdc++.so.6.0.14 /c/lib/libstdc++.so.6
cp /u/lib/libosal_uipc.so /c/lib/ 2>/dev/null
LDR=/c/lib/ld-2.11.2.so; U=/u/bin/ud_datcnv.elf
R() { echo -n "rc="; $LDR --library-path /c/lib $U "$@" >/tmp/.o 2>&1; echo "$?"; grep -v '/dev/uipc' /tmp/.o; }
H() { od -An -tx1 -v "$1" | tr -d ' \n'; }
mkdir -p /tmp/d5; cd /tmp/d5

echo "### 1) 退出码 / 静默失败"
printf '01234567890123456' > t17.txt; R -e -i t17.txt -o t17.bin -a; echo "  17位输入 -> 文件大小=$(wc -c < t17.bin)"
: > t0.txt; R -e -i t0.txt -o t0.bin -a; echo "  空输入 -> 文件大小=$(wc -c < t0.bin)"
R -d -i t0.bin -o t0d.txt -a; echo "  解码空文件 -> 输出存在? $(ls t0d.txt 2>&1 | tail -1)"
R -e -i /nope -o x.bin -a; R -d -i /nope -o x.txt -a
mkdir -p sub; R -e -i t17.txt -o sub/ok.bin -a; echo "  覆盖已有文件 rc + size=$(wc -c < sub/ok.bin)"
R -d; R -e; R -a; R
echo "### 2) 往返：digits-only（up.sh 的用法）"
for v in 0200 0100 0000 91030019 00000000 2.00 1.00; do
  echo "$v" > w.txt                       # echo 带换行，和 up.sh 一样
  $LDR --library-path /c/lib $U -e -i w.txt -o w.bin -a
  $LDR --library-path /c/lib $U -d -i w.bin -o r.txt -a
  printf 'text=%-9s dat(len=%s)=%s  -d-> [%s] %s\n' "$v" "$(wc -c < w.bin | tr -d ' ')" "$(H w.bin)" "$(cat r.txt)" "$(printf '%s\n' "$v" | cmp -s - r.txt && echo 一致 || echo 不一致)"
done
echo "### 3) dat2/3/4 大小推断（8/8/4 字符 -> 字节数）"
for n in 4 8; do s=""; i=0; while [ $i -lt $n ]; do s="${s}$((i % 10))"; i=$((i+1)); done; printf '%s\n' "$s" > z.txt; $LDR --library-path /c/lib $U -e -i z.txt -o z.bin -a; echo "${n}字符 -> $(wc -c < z.bin) 字节 $(H z.bin)"; done
echo "### 4) 解码大文件（是否有上限/崩溃）"
for n in 64 512 1030 1031 2048 4096; do
  head -c $n /dev/urandom > big.bin
  echo -n "  size=$n rc="; $LDR --library-path /c/lib $U -d -i big.bin -o big.txt -a >/tmp/.o 2>&1; echo -n "$? "; grep -v '/dev/uipc' /tmp/.o; echo -n "  out=$(wc -c < big.txt 2>/dev/null) "
  echo -n "  无-a out=$( $LDR --library-path /c/lib $U -d -i big.bin -o bign.txt >/dev/null 2>&1; wc -c < bign.txt 2>/dev/null)"
  echo
done
echo "### 5) 随机字节 -e -a 再 -d（校验缺失）"
printf '0200' > c0.txt; $LDR --library-path /c/lib $U -e -i c0.txt -o c0.bin -a
cp c0.bin c1.bin; printf '\377' | dd of=c1.bin bs=1 seek=0 count=1 conv=notrunc status=none
$LDR --library-path /c/lib $U -d -i c1.bin -o c1.txt -a; echo "  ff02 -> [$(cat c1.txt)] rc=$?"
echo "### 6) 是否存在任何 magic/头：多个不同长度输出的前字节"
for v in 01 0123 012345 01234567 0123456789; do printf '%s\n' "$v" > m.txt; $LDR --library-path /c/lib $U -e -i m.txt -o m.bin -a; echo "  '$v' -> $(H m.bin)"; done
