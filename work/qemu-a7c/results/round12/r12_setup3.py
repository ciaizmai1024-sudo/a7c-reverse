#!/usr/bin/env python3
import struct, os
base = "/home/wubin/qemu-a7c"
d12 = base + "/r12/tree/r12"
def hdr(pri=0x02e80000, cookie=0xaaaaaaaa, wc=1, ver=b"BK4\x00", cnt_init=0,
        cnt=1, id1=0, csum=0, extra=None):
    h = bytearray(0x100)
    h[0:4] = struct.pack("<I", pri)
    h[4:8] = struct.pack("<I", cookie)
    h[8:12] = struct.pack("<I", wc)
    h[12:16] = ver
    h[0x10:0x14] = struct.pack("<I", cnt_init)
    h[0x2c:0x30] = struct.pack("<I", cnt)
    h[0x20:0x24] = struct.pack("<I", id1)
    h[0x38:0x3c] = struct.pack("<I", csum)
    if extra:
        for off, val in extra.items():
            if isinstance(val, bytes): h[off:off+len(val)] = val
            else: h[off:off+4] = struct.pack("<I", val)
    return h
def w(name, data):
    open(os.path.join(d12, name), "wb").write(bytes(data))
# v1: 256-byte minimal, count_init=0
h1 = hdr(cnt_init=0, cnt=1)
w("v1.bin", h1); w("v1.bak", h1)
# v2: count_init=1 + one 6-byte record at 0x100
h2 = bytearray(hdr(cnt_init=1, cnt=1)); h2 += bytes([0x34,0x12,0x00,0x00,0x00,0x00])
w("v2.bin", h2); w("v2.bak", bytes(h2))
# v3: BK2 version string (rev-2 dump path)
h3 = bytearray(hdr(cnt_init=1, cnt=1, ver=b"BK2\x00")); h3 += bytes(6)
w("v3.bin", h3); w("v3.bak", bytes(h3))
# v4: cookie 9000e1a0 (sanity)
h4 = bytearray(hdr(cnt_init=1, cnt=1, cookie=0x9000e1a0)); h4 += bytes(6)
w("v4.bin", h4); w("v4.bak", bytes(h4))
# v5: hdr+12 = "BK5" (bad version -> Data_init strcmp fail expected)
h5 = bytearray(hdr(cnt_init=1, cnt=1, ver=b"BK5\x00")); h5 += bytes(6)
w("v5.bin", h5); w("v5.bak", bytes(h5))
# v6: pri=v2, sec=zeros(0x100) -> Data_check must pick branch via pri cookie
w("v6.bin", bytes(h2)); w("v6.bak", bytes(0x100))
print("variants written")
p = base + "/r12/tree/usr/bin/insmod.sh"
s = open(p).read()
old = 'for V in ctrl e1 e2 e3 ; do'
assert old in s
s = s.replace(old, 'for V in v1 v2 v3 v4 v5 v6 ; do')
open(p, "w").write(s)
print("insmod.sh loop list updated")
