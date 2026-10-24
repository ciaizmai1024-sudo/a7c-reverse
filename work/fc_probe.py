#!/usr/bin/env python3
"""L2 探针：一个会话里试多种 FileControl(0xff01) 帧格式，找出 A7C 能接受的写法。只读。"""
import sys, os, struct, time
sys.path.insert(0, os.path.expanduser('~/a7c-jiritsu/tools'))
import jiritsu_send as T

ARGS = None
class A:
    mock=None; mock_dir=None; verbose=True; msc_pid=None; svc_pid=None
    usb_timeout=20000; wait_service=120; allow_danger=False
args=A()

def pad(fn):
    return fn + b'\0' * (4 - len(fn) % 4)

def try_pkt(j, label, pfunc, payload):
    try:
        resp, out = j.pkt(pfunc, payload, retries=0)
        print(f'  [{label}] pfunc=0x{pfunc:04x} payload={payload.hex()} -> resp={resp} len={len(out)} {out[:48].hex()}')
        return resp, out
    except Exception as e:
        print(f'  [{label}] pfunc=0x{pfunc:04x} payload={payload.hex()} -> EXC {type(e).__name__}: {e}')
        return None, None

j = T.connect(args)
print('== connected ==')

# 0) Jiritsu sanity: GET_VERSION(13), MOUNT(2)
for code in (13, 2):
    try:
        r = j.jir(code)
        print('  jir', code, r[0], r[1], r[2][:32])
    except Exception as e:
        print('  jir', code, 'EXC', e)

# 1) GET_FILE2 on /tmp/jiritsu/libJit.so (Jiritsu 通道读)
try:
    r = j.read2('/tmp/jiritsu/libJit.so')
    print('  read2 libJit ->', r[0], r[1], len(r[2]))
except Exception as e:
    print('  read2 EXC', e)

# 2) FileControl variants on a small known file
targets = ['/setting/partinf.conf', '/version.txt', '/tmp/jiritsu/ver.txt']
for t in targets[:2]:
    fn = t.encode('latin1')
    variants = {
        'pmca-pad':   struct.pack('<HH', 2, len(pad(fn))) + pad(fn),
        'nopad':      struct.pack('<HH', 2, len(fn)) + fn,
        'pad-nul':    struct.pack('<HH', 2, len(fn + b'\0')) + pad(fn + b'\0'),
        'cmd4B':      struct.pack('<II', 2, len(pad(fn))) + pad(fn),
        'len-body':   struct.pack('<HH', 2, len(fn)) + pad(fn),
    }
    for k, v in variants.items():
        try_pkt(j, f'fc-{k}:{t}', 0xff01, v)
    time.sleep(0.5)

# 3) 块设备 FileControl
dev = b'/dev/nflasha23'
try_pkt(j, 'fc-dev-pad', 0xff01, struct.pack('<HH', 2, len(pad(dev))) + pad(dev))
# 4) MemoryDump sanity
try_pkt(j, 'memdump', 0xff03, struct.pack('<II', 0xffff0000, 64))
# 5) ProductInfo sanity
try_pkt(j, 'pinfo', 0xff00, struct.pack('<HH', 0x603, 1))
j.stop()
print('== done ==')
