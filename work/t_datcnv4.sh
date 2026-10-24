#!/bin/sh
# 第四轮：无 -a 模式的精确规则（顺序可辨字节）+ 长度上限 + 解码上限
cp -r /cam /c >/dev/null 2>&1 || true
chmod -R +x /c/lib >/dev/null 2>&1
cd /c/lib
for p in "libc-2.11.2.so libc.so.6" "libm-2.11.2.so libm.so.6" "libdl-2.11.2.so libdl.so.2" \
         "libpthread-2.11.2.so libpthread.so.0" "librt-2.11.2.so librt.so.1" "ld-2.11.2.so ld-linux.so.3"; do
  set -- $p; ln -sf "$1" "$2"; done
cp /u/lib/libstdc++.so.6.0.14 /c/lib/ 2>/dev/null; ln -sf libstdc++.so.6.0.14 /c/lib/libstdc++.so.6
cp /u/lib/libosal_uipc.so /c/lib/ 2>/dev/null
LDR=/c/lib/ld-2.11.2.so
U=/u/bin/ud_datcnv.elf
Q() { $LDR --library-path /c/lib $U "$@" >/dev/null 2>&1; }
H() { od -An -tx1 -v "$1" | tr -d ' \n'; }
mkdir -p /tmp/d4; cd /tmp/d4

echo "### A) 无 -a：输入 = 0x01,0x02,...,0xNN（NN=1..20）"
n=1
while [ $n -le 20 ]; do
  : > in.bin; j=1
  while [ $j -le $n ]; do printf "\\$(printf '%03o' $j)" >> in.bin; j=$((j+1)); done
  Q -e -i in.bin -o out.bin
  echo "L=$n in=$(H in.bin) out(len=$(wc -c < out.bin))=$(H out.bin)"
  n=$((n+1))
done

echo "### B) 无 -a：输入 = 0x11 重复 N 次 + 高位可辨（0xA1,0xB2,0xC3,0xD4,...）"
printf '\241\262\303\324' > b4.bin; Q -e -i b4.bin -o b4o.bin; echo "A1B2C3D4 -> in=$(H b4.bin) out=$(H b4o.bin)"
printf '\241\262\303' > b3.bin; Q -e -i b3.bin -o b3o.bin; echo "A1B2C3   -> in=$(H b3.bin) out=$(H b3o.bin)"
printf '\241\262\303\324\345' > b5.bin; Q -e -i b5.bin -o b5o.bin; echo "A1B2C3D4E5 -> in=$(H b5.bin) out=$(H b5o.bin)"

echo "### C) -a：长度上限（1..20 位数字）"
for n in 14 15 16 17 18 20; do
  s=""; j=0; while [ $j -lt $n ]; do s="${s}$((j % 10))"; j=$((j+1)); done
  printf '%s' "$s" > s.txt; Q -e -i s.txt -o s.bin -a
  echo "len=$n in=$s out=$(H s.bin)"
done
echo "-- 17 位但前导很多 0:"
printf '00000000000000200' > s.txt; Q -e -i s.txt -o s.bin -a; echo "in=$(cat s.txt) out=$(H s.bin)"
printf '00000000000000000200' > s.txt; Q -e -i s.txt -o s.bin -a; echo "in 20char out=$(H s.bin)"
printf '0000000000000000000000200' > s.txt; Q -e -i s.txt -o s.bin -a; echo "in 25char out=$(H s.bin)"
printf '123456789012345678' > s.txt; Q -e -i s.txt -o s.bin -a; echo "18位 out=$(H s.bin)"

echo "### D) -d -a 的输入文件长度上限（构造 1..16 字节文件，看解出多少字符）"
n=1
while [ $n -le 16 ]; do
  : > dd.bin; j=1; while [ $j -le $n ]; do printf "\\$(printf '%03o' $((0x10 + j)))" >> dd.bin; j=$((j+1)); done
  Q -d -i dd.bin -o dd.out -a
  echo "inbytes=$n in=$(H dd.bin) outlen=$(wc -c < dd.out) out=$(od -An -c -v dd.out | tr -s ' ' | tr -d '\n')"
  n=$((n+1))
done
echo "### E) -d 无 -a 的长度扫描（输入 1..16 字节）"
n=1
while [ $n -le 16 ]; do
  : > de.bin; j=1; while [ $j -le $n ]; do printf "\\$(printf '%03o' $((0x10 + j)))" >> de.bin; j=$((j+1)); done
  Q -d -i de.bin -o de.out
  echo "inbytes=$n in=$(H de.bin) out=$(H de.out)"
  n=$((n+1))
done
echo "### F) dat4 里放什么？试试 up.sh 的调用形式：echo '2.00' | 编 → 解回"
printf '2.00\n' > v.txt; Q -e -i v.txt -o v.bin -a; echo "echo '2.00' -> dat $(H v.bin)"; Q -d -i v.bin -o v2.txt -a; echo "解回: [$(cat v2.txt)]"
printf '2.00' > v.txt; Q -e -i v.txt -o v3.bin -a; echo "'2.00'(无换行) -> $(H v3.bin)  cmp:"; cmp v.bin v3.bin && echo "  相同（换行被当奇数位丢弃）"
echo "### G) 用 -e -a 写 4 字节定长？（dat4 大小）"
ls -l v.bin
echo "### H) 输入目录 / 特殊选项组合：-e -d 同时给"
Q -e -d -i v.txt -o both.bin -a; echo "rc(both)=$? size=$(wc -c < both.bin 2>/dev/null) $(H both.bin 2>/dev/null)"
