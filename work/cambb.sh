
cp -r /cam /c >/dev/null 2>&1 || true
chmod -R +x /c/lib /c/bin 2>/dev/null
cd /c/lib
for p in "libc-2.11.2.so libc.so.6" "libm-2.11.2.so libm.so.6" "libdl-2.11.2.so libdl.so.2" "libpthread-2.11.2.so libpthread.so.0" "librt-2.11.2.so librt.so.1" "libcrypt-2.11.2.so libcrypt.so.1" "libnsl-2.11.2.so libnsl.so.1" "libresolv-2.11.2.so libresolv.so.2" "libutil-2.11.2.so libutil.so.1" "libanl-2.11.2.so libanl.so.1" "libnss_files-2.11.2.so libnss_files.so.2" "libnss_dns-2.11.2.so libnss_dns.so.2" "libnss_nis-2.11.2.so libnss_nis.so.2" "ld-2.11.2.so ld-linux.so.3"; do set -- $p; ln -sf $1 $2; done
cd /w
