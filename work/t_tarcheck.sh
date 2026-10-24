. /t/camprefix.sh
BB | head -1
echo "=== 相机 busybox 看我们的载荷:"; BB tar tvf /w/jiritsu_firm.dat
rm -rf /tmp/jiritsu; mkdir -p /tmp/jiritsu
BB tar xpf /w/jiritsu_firm.dat ./ -C /tmp/jiritsu; echo "★xpf rc=$?"
ls -l /tmp/jiritsu
echo "=== 解出的 libJit.so 与源文件字节一致吗:"; cmp /tmp/jiritsu/libJit.so /w/payload/libJit.so && echo "byte-identical OK"
