#!/usr/bin/env python3
"""L2-B3: /usr/lib 关键库 + 若干猜测路径 + 两个只读 PFUNC 冒烟。只读。"""
import sys, os, time, hashlib, struct
sys.path.insert(0, '/home/wubin/a7c-jiritsu/tools')
import jiritsu_send as T
OUT='/home/wubin/a7c-jiritsu/probe2'
PATHS="""/usr/lib/libupdaterufp.so
/usr/lib/libupdatertalk.so
/usr/lib/libupdaterufunc.so
/usr/lib/libupdatercommon.so
/usr/lib/libupdatermedia.so
/usr/lib/libJiritsu.so
/usr/lib/libsencore.so
/usr/local/bin/sen.elf
/boot/p1chksum
/boot/dat2
/boot/initrd.img
/history/update.log
/hash
/setting/updater/mode
/setting/updater/mode6
/setting/updater/mode1
""".split()
class A:
    mock=None; mock_dir=None; verbose=False; msc_pid=None; svc_pid=None
    usb_timeout=20000; wait_service=150; allow_danger=False
def local(p): return os.path.join(OUT,p.replace('/','_')+'.bin')
j=T.connect(A()); print('== up ==',flush=True)
for p in PATHS:
    if os.path.exists(local(p)):
        print('%-34s CACHED %d'%(p,os.path.getsize(local(p))),flush=True); continue
    try:
        with open(local(p)+'.part','wb') as f: j.fread(p,outFile=f)
        os.rename(local(p)+'.part',local(p))
        n=os.path.getsize(local(p)); print('%-34s OK size=%d sha=%s'%(p,n,hashlib.sha256(open(local(p),'rb').read()).hexdigest()[:16]),flush=True)
    except Exception as e:
        try: os.remove(local(p)+'.part')
        except Exception: pass
        m=str(e)[:60]; print('%-34s %s'%(p,'ERR130' if '130' in m else m),flush=True)
for lbl,pfunc,payload in [('AdjustControl 0x603 code1',0x0000,struct.pack('<HH',0x603,1)),
                          ('ProductInfo cat0x603 cmd1',0xff00,struct.pack('<HH',0x603,1))]:
    try:
        r,o=j.pkt(pfunc,payload,retries=0)
        print('%-34s resp=%s len=%d %s'%(lbl,r,len(o),o[:32].hex()),flush=True)
    except Exception as e:
        print('%-34s EXC %s'%(lbl,type(e).__name__),flush=True)
try: j.stop()
except Exception: pass
