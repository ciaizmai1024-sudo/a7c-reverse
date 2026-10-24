# 在容器里 source 这个文件，就能用**相机自己的用户态**（busybox v1.29.3 + glibc 2.11.2）。
# 由 tools/camuser.sh 挂载：/cam = 相机 nflasha7 rootfs（只读），/w = 本项目 work/，/t = tools/。
# 相机解包丢了所有符号链接（/bin/sh、/bin/tar、libX.so.N），所以这里现补。
cp -r /cam /c >/dev/null 2>&1 || true
chmod -R +x /c/lib /c/bin 2>/dev/null
cd /c/lib || exit 1
for p in "libc-2.11.2.so libc.so.6" "libm-2.11.2.so libm.so.6" "libdl-2.11.2.so libdl.so.2" \
         "libpthread-2.11.2.so libpthread.so.0" "librt-2.11.2.so librt.so.1" "libcrypt-2.11.2.so libcrypt.so.1" \
         "libnsl-2.11.2.so libnsl.so.1" "libresolv-2.11.2.so libresolv.so.2" "libutil-2.11.2.so libutil.so.1" \
         "libanl-2.11.2.so libanl.so.1" "libnss_files-2.11.2.so libnss_files.so.2" "libnss_dns-2.11.2.so libnss_dns.so.2" \
         "libnss_nis-2.11.2.so libnss_nis.so.2" "ld-2.11.2.so ld-linux.so.3" "libproc-3.2.7.so libproc.so.3.2.7"; do
  set -- $p; ln -sf "$1" "$2"
done
LDR=/c/lib/ld-2.11.2.so
BB() { $LDR --library-path /c/lib /c/bin/busybox "$@"; }
CAM() { p="$1"; shift; $LDR --library-path /c/lib "$p" "$@"; }   # 跑相机自己的 ELF：CAM /c/bin/xxx args…（只有 nflasha7 里的东西，/usr 在另一分区）
