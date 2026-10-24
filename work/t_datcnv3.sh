#!/bin/sh
# 第三轮：字符->半字节映射表、长度扫描、无 -a 的精确规则、手工构造对比（八进制 printf）
cp -r /cam /c >/dev/null 2>&1 || true
chmod -R +x /c/lib >/dev/null 2>&1
cd /c/lib
for p in "libc-2.11.2.so libc.so.6" "libm-2.11.2.so libm.so.6" "libdl-2.11.2.so libdl.so.2" \
         "libpthread-2.11.2.so libpthread.so.0" "librt-2.11.2.so librt.so.1" "ld-2.11.2.so ld-linux.so.3"; do
  set -- $p; ln -sf "$1" "$2"; done
cp /u/lib/libstdc++.so.6.0.14 /c/lib/ 2>/dev/null; ln -sf libstdc++.so.6.0.14 /c/lib/libstdc++.so.6
cp /u/lib/libosal_uipc.so /c/lib/ 2>/dev/null
LDR=/c/lib/ld-2.11.2.so
Q() { $LDR --library-path /c/lib /u/bin/ud_datcnv.elf "$@" >/dev/null 2>&1; }
mkdir -p /tmp/d3; cd /tmp/d3

echo "### 1) 字符 -> 半字节映射（-e -a，输入 2 字符 'X0'，输出 1 字节 = nibble(X)<<4）"
i=32
while [ $i -le 126 ]; do
  c=$(printf "\\$(printf '%03o' $i)")
  printf "%s0" "$c" > c.txt
  Q -e -i c.txt -o c.bin -a
  b=$(od -An -tx1 -v c.bin | tr -d ' \n')
  printf 'chr %02x(%s) -> %s\n' $i "$c" "${b:-EMPTY}"
  i=$((i+1))
done

echo "### 2) 长度扫描 (-e -a)"
for n in 1 2 3 4 5 6 8 10 12 14 16 18 20 22 24 30 32 33 40 64; do
  s=$(printf '%0*d' $n 0 2>/dev/null)
  s=""; j=0; while [ $j -lt $n ]; do s="$s$j"; j=$((j+1)); done
  s=$(echo "$s" | cut -c1-$n)
  printf '%s' "$s" > n.txt
  Q -e -i n.txt -o n.bin -a
  echo "in=$n out=$(wc -c < n.bin) bytes=$(od -An -tx1 -v n.bin | tr -d ' \n')"
done
echo "-- 纯数字 200 / 0200 / 00200 / 0000000000000000200 / 99999999 --"
for s in 20 200 0200 00200 0000000000000000200 99999999 9999999999 99999999999999999999 65535; do
  printf '%s' "$s" > d.txt; Q -e -i d.txt -o d.bin -a
  echo "'$s' -> len=$(wc -c < d.bin) $(od -An -tx1 -v d.bin | tr -d ' \n')"
done

echo "### 3) 无 -a 精确规则（输入任意字节）"
printf 'A' > r1.bin; Q -e -i r1.bin -o r1o.bin; echo "1B(41) -> $(od -An -tx1 -v r1o.bin | tr -d ' \n')"
printf 'ABC' > r3.bin; Q -e -i r3.bin -o r3o.bin; echo "3B(414243) -> $(od -An -tx1 -v r3o.bin | tr -d ' \n')"
printf '0200' > r4.bin; Q -e -i r4.bin -o r4o.bin; echo "4B(30323030) -> $(od -An -tx1 -v r4o.bin | tr -d ' \n')"
printf 'ABCDE' > r5.bin; Q -e -i r5.bin -o r5o.bin; echo "5B -> $(od -An -tx1 -v r5o.bin | tr -d ' \n')"
printf 'ABCDEFGH' > r8.bin; Q -e -i r8.bin -o r8o.bin; echo "8B -> $(od -An -tx1 -v r8o.bin | tr -d ' \n')"
printf '\000\001\002\003' > rb.bin; od -An -tx1 -v rb.bin; Q -e -i rb.bin -o rbo.bin; echo "raw4 -> $(od -An -tx1 -v rbo.bin | tr -d ' \n')"
echo "-- 无 -a 解码这些编码结果 --"
for f in r1o r3o r4o r5o r8o rbo; do Q -d -i $f.bin -o ${f}d.out; echo "$f -> $(od -An -tx1 -v ${f}d.out | tr -d ' \n')"; done
echo "-- 直接 -d 原始字节序列（不先 -e）--"
printf '\000\002' > q.bin; Q -d -i q.bin -o qd.out; echo "-d(0002) 无a -> $(od -An -tx1 -c -v qd.out | tr -s ' ')"

echo "### 4) 手工构造 vs 工具（八进制 printf）"
printf '0100' > f1.txt; Q -e -i f1.txt -o f1.bin -a; printf '\000\001' > h1.bin
printf '2.00' > f2.txt; Q -e -i f2.txt -o f2.bin -a; printf '\000\056' > h2.bin
printf '91030019' > f3.txt; Q -e -i f3.txt -o f3.bin -a; printf '\031\000\003\221' > h3.bin
printf '0000' > f4.txt; Q -e -i f4.txt -o f4.bin -a; printf '\000\000' > h4.bin
for p in 1 2 3 4; do echo -n "case$p 工具=$(od -An -tx1 -v f$p.bin | tr -d ' \n') 手工=$(od -An -tx1 -v h$p.bin | tr -d ' \n') "; cmp f$p.bin h$p.bin && echo "== ✓" || echo "≠"; done
echo "-- 手工文件 -d -a 的文本输出 --"
for p in 1 2 3 4; do Q -d -i h$p.bin -o hd$p.txt -a; echo "h$p.bin -> $(cat hd$p.txt)"; done
echo "### 5) 奇数字节文件 -d -a"
printf '\000\002\003' > odd.bin; Q -d -i odd.bin -o od1.out -a; echo "3B -> len=$(wc -c < od1.out) [$(cat od1.out)]"
echo "### 6) 40 字符异常复现（-e -a，明确报错?）"
printf '0123456789012345678901234567890123456789' > long.txt
$LDR --library-path /c/lib /u/bin/ud_datcnv.elf -e -i long.txt -o long.bin -a; echo "rc=$? out=$(wc -c < long.bin)"
printf '01234567890123456789' > l20.txt
$LDR --library-path /c/lib /u/bin/ud_datcnv.elf -e -i l20.txt -o l20.bin -a; echo "rc=$? out=$(wc -c < l20.bin) $(od -An -tx1 -v l20.bin | tr -d ' \n')"
