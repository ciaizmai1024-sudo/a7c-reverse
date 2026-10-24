#!/bin/sh
# 第二轮：-a 语义细节 / 换行 / 奇数长度 / 篡改校验 / 错误处理
cp -r /cam /c >/dev/null 2>&1 || true
chmod -R +x /c/lib >/dev/null 2>&1
cd /c/lib
for p in "libc-2.11.2.so libc.so.6" "libm-2.11.2.so libm.so.6" "libdl-2.11.2.so libdl.so.2" \
         "libpthread-2.11.2.so libpthread.so.0" "librt-2.11.2.so librt.so.1" "ld-2.11.2.so ld-linux.so.3"; do
  set -- $p; ln -sf "$1" "$2"; done
cp /u/lib/libstdc++.so.6.0.14 /c/lib/ 2>/dev/null; ln -sf libstdc++.so.6.0.14 /c/lib/libstdc++.so.6
cp /u/lib/libosal_uipc.so /c/lib/ 2>/dev/null
LDR=/c/lib/ld-2.11.2.so
CNV() { $LDR --library-path /c/lib /u/bin/ud_datcnv.elf "$@" > /tmp/.cnvout 2>&1; rc=$?; grep -v '/dev/uipc' /tmp/.cnvout; return $rc; }
D() { $LDR --library-path /c/lib /u/bin/ud_datcnv.elf "$@" >/dev/null 2>&1; }
mkdir -p /tmp/d2; cd /tmp/d2

mkdir -p /tmp; echo "### A) 输入带不带换行 (echo vs printf)"
printf '0200\n' > a_nl.txt; printf '0200' > a_no.txt; printf '0200\r\n' > a_crlf.txt
for f in a_nl a_no a_crlf; do D -e -i $f.txt -o $f.bin -a; echo "$f in=$(wc -c < $f.txt) out=$(wc -c < $f.bin) : $(od -An -tx1 -v $f.bin | tr -s ' ')"; done

echo "### B) 奇数长度 / 空格 / 字母 / 长串 (-a)"
for s in 123 1 12345 2.0 ab AB "0 200" 0123456789012345678901234567890123456789; do
  printf '%s' "$s" > x.txt; D -e -i x.txt -o x.bin -a; printf "'%s' -> len=%s : %s\n" "$s" "$(wc -c < x.bin)" "$(od -An -tx1 -v x.bin | tr -s ' ')"
  D -d -i x.bin -o y.txt -a; printf "   -d -> len=%s : %s\n" "$(wc -c < y.txt)" "$(od -An -c -v y.txt | tr -s ' ')"
done

echo "### C) 输出是否固定长度（补零到某个长度？）"
for s in 02 0200 02000000 0200000000000000; do printf '%s' "$s" > z.txt; D -e -i z.txt -o z.bin -a; echo "'$s' chars=${#s} out=$(wc -c < z.bin)"; done

echo "### D) 校验：篡改 1 字节后 -d 是否报错 / 结果变化"
printf '0200' > t.txt; D -e -i t.txt -o t.bin -a; echo "orig:"; od -An -tx1 -v t.bin
i=0
for pos in 0 1; do
  for delta in 1 0x10 0x30; do
    cp t.bin tt.bin
    printf "$(printf '\\x%02x' $((0x02 + delta)))" | dd of=tt.bin bs=1 seek=$pos count=1 conv=notrunc status=none
    echo "-- 改 offset $pos -> $(od -An -tx1 -v tt.bin | tr -s ' ')"
    echo -n "   -d -a rc="; CNV -d -i tt.bin -o to.txt -a; echo $?; od -An -c -v to.txt
  done
done
echo "-- 截短文件（只留 1 字节）-"
head -c 1 t.bin > short.bin; echo -n "rc="; CNV -d -i short.bin -o so.txt -a; echo $?; od -An -c -v so.txt
echo "-- 空文件 -d -"
: > empty.bin; echo -n "rc="; CNV -d -i empty.bin -o eo.txt -a; echo $?; ls -l eo.txt 2>&1 | tail -1
echo "-- 输入文件不存在 -e -"
echo -n "rc="; CNV -e -i /tmp/d2/nonexistent -o zz.bin -a; echo $?; ls -l zz.bin 2>&1 | tail -1
echo "### E) 选项行为"
echo "-- 无 -i/-o:"; CNV -e -a
echo "-- -h:"; CNV -h; echo "rc=$?"
echo "-- 未知选项 -x:"; CNV -x -e -i t.txt -o h.bin; echo "rc=$?"; ls -l h.bin 2>&1 | tail -1
echo "-- 只 -e 不给 -i -o:"; CNV -e; echo "rc=$?"
echo "-- -v:"; CNV -v; echo "rc=$?"
echo "### F) 模拟 FDAT 头字段：手工构造解码为 0100 / 2.00 / 91030019 的输入"
printf '0100' > m1.txt; D -e -i m1.txt -o m1.bin -a; echo "0100 ->"; od -An -tx1 -v m1.bin
printf '2.00' > m2.txt; D -e -i m2.txt -o m2.bin -a; echo "2.00 ->"; od -An -tx1 -v m2.bin
printf '91030019' > m3.txt; D -e -i m3.txt -o m3.bin -a; echo "91030019 ->"; od -An -tx1 -v m3.bin
printf '0000' > m4.txt; D -e -i m4.txt -o m4.bin -a; echo "0000 ->"; od -An -tx1 -v m4.bin
echo "-- 用 shell 手工构造（printf 反转 BCD）与工具产物对比："
printf '\x19\x00\x03\x91' > manual_91030019.bin; cmp manual_91030019.bin m3.bin && echo "  91030019 手工==工具 ✓"
printf '\x00\x01' > manual_0100.bin; cmp manual_0100.bin m1.bin && echo "  0100 手工==工具 ✓"
printf '\x00\x2e' > manual_200.bin; cmp manual_200.bin m2.bin && echo "  2.00 手工==工具 ✓"
echo "-- 对构造文件 -d:"; CNV -d -i manual_200.bin -o md.txt -a >/dev/null; od -An -c -v md.txt
echo "### G) 长度不同的 dat4 会不会被 -d 忽略多余："
printf '2.00' > g.txt; D -e -i g.txt -o g4.bin -a; cp g4.bin g8.bin; printf '\x00\x00\x00\x00' >> g8.bin
echo "4字节:"; od -An -tx1 -v g4.bin; echo "8字节:"; od -An -tx1 -v g8.bin
echo -n "-d 4B rc="; CNV -d -i g4.bin -o g4.txt -a; echo $?; od -An -c -v g4.txt
echo -n "-d 8B rc="; CNV -d -i g8.bin -o g8.txt -a; echo $?; od -An -c -v g8.txt
