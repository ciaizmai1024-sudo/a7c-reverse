#!/usr/bin/env bash
# 只读会话包装：先 USB 硬复位回到 MSC，再跑 python；失败重试（脚本自身可续跑）。
set -u
cd ~/a7c-jiritsu
RESET='
import usb.core, usb.util, usb.backend.libusb1
try:
    import libusb_package
    p=None
    try: p=libusb_package.get_library_path()
    except Exception: p=None
    be=usb.backend.libusb1.get_backend(find_library=lambda n: str(p)) if p else usb.backend.libusb1.get_backend()
except Exception:
    be=usb.backend.libusb1.get_backend()
for d in usb.core.find(find_all=True, idVendor=0x054c, backend=be):
    print("  found 0x%04x" % d.idProduct)
    try: d.reset()
    except Exception as e: print("  reset fail", e)
    try: usb.util.dispose_resources(d)
    except Exception: pass
'
for attempt in 1 2 3 4 5; do
  echo "### attempt $attempt"
  echo zzz888ZZZ | sudo -S -p "" env PYTHONDONTWRITEBYTECODE=1 python3 -c "$RESET" 2>&1 | tail -4
  for i in $(seq 1 40); do lsusb | grep -q '054c:0d29' && break; sleep 2; done
  lsusb | grep -oE '054c:[0-9a-f]*' | head -2
  echo zzz888ZZZ | sudo -S -p "" env PYTHONDONTWRITEBYTECODE=1 timeout ${TMO:-200} python3 "$@" 2>&1
  rc=${PIPESTATUS[0]}
  echo "### rc=$rc"
  [ $rc -eq 0 ] && exit 0
  sleep 6
done
exit 1
