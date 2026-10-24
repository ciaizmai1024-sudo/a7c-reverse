#!/usr/bin/env bash
# L2 只读会话包装：确保每次都在"干净的 MSC"上鉴权。
# 用法: sudo ./wrap.sh <python-script> [args...]   或  sudo ./wrap.sh --scan-only
set -u
cd ~/a7c-jiritsu
SW=($(lsusb | grep -oE 'ID 054c:[0-9a-f]{4}'))
poll(){ # 等到 054c 设备重新枚举，返回其 PID
  for i in $(seq 1 40); do
    p=$(lsusb | grep -oE '054c:[0-9a-f]{4}' | head -1)
    [ -n "$p" ] && { echo "$p"; return 0; }
    sleep 1
  done
  return 1
}
clean(){ # USB 硬复位（等价拔插），等回到 MSC 0d29
  echo zzz888ZZZ | sudo -S -p "" env PYTHONDONTWRITEBYTECODE=1 python3 - <<'EOF'
import sys, time, usb.core, usb.util
import usb.backend.libusb1
try:
    import libusb_package
    p=None
    try: p=libusb_package.get_library_path()
    except Exception: p=None
    be=usb.backend.libusb1.get_backend(find_library=lambda n: str(p)) if p else usb.backend.libusb1.get_backend()
except Exception:
    be=usb.backend.libusb1.get_backend()
n=0
for d in usb.core.find(find_all=True, idVendor=0x054c, backend=be):
    print('  found 0x%04x' % d.idProduct)
    try:
        d.reset(); n+=1
    except Exception as e:
        print('  reset fail', e)
    try: usb.util.dispose_resources(d)
    except Exception: pass
print('  reset', n)
EOF
  for i in $(seq 1 40); do
    if lsusb | grep -q '054c:0d29'; then echo "  back to MSC 0d29"; return 0; fi
    sleep 2
  done
  echo "  !! 没回到 0d29: $(lsusb | grep -oE '054c:[0-9a-f]*')"
  return 1
}
for attempt in 1 2 3; do
  echo "### attempt $attempt"
  clean || { sleep 5; continue; }
  echo zzz888ZZZ | sudo -S -p "" env PYTHONDONTWRITEBYTECODE=1 timeout ${TMO:-200} python3 "$@" 2>&1
  rc=$?
  echo "### rc=$rc"
  [ $rc -eq 0 ] && exit 0
  sleep 8
done
exit 1
