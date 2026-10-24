#!/usr/bin/env python3
"""L2-B2: 第二轮路径探测 + 小分区 dump（a1/a6/a13）。只读。"""
import sys, os, struct, time, hashlib
sys.path.insert(0, '/home/wubin/a7c-jiritsu/tools')
import jiritsu_send as T

OUT = '/home/wubin/a7c-jiritsu/probe2'
DUMP = '/home/wubin/a7c-jiritsu/work/l2'
PATHS = """
/tmp/nsswitch.conf
/tmp/kikilog.dat
/tmp/uipc_set.txt
/tmp/toprc
/tmp/protoc.conf
/tmp/services
/tmp/resolve.conf
/tmp/mtab.dat
/tmp/config.spec
/version.txt
/dat1
/dat2
/dat3
/dat4
/p1chksum
/Backup.bin
/kemco.txt
/partinf.conf
/mount.conf
/updater/comp
/updater/dat4
/system/setting/kemco.txt
/system/updater/comp
/PMBP/PMHOME
/lens
/setting
/tmp
/usr
""".split()
DEVS = ['nflasha1', 'nflasha6', 'nflasha13']

class A:
    mock=None; mock_dir=None; verbose=False; msc_pid=None; svc_pid=None
    usb_timeout=20000; wait_service=150; allow_danger=False

def local(p): return os.path.join(OUT, p.replace('/', '_') + '.bin')

def one(j, p):
    if os.path.exists(local(p)):
        n=os.path.getsize(local(p)); h=hashlib.sha256(open(local(p),'rb').read()).hexdigest()
        return f'OK(cached) size={n} sha={h[:16]}'
    t0=time.time()
    try:
        with open(local(p)+'.part','wb') as f: j.fread(p, outFile=f)
        os.rename(local(p)+'.part', local(p))
        n=os.path.getsize(local(p)); h=hashlib.sha256(open(local(p),'rb').read()).hexdigest()
        return f'OK size={n} sha={h[:16]} {time.time()-t0:.1f}s'
    except Exception as e:
        try: os.remove(local(p)+'.part')
        except Exception: pass
        m=f'{type(e).__name__}: {e}'
        cat='ERR130' if 'error 130' in m else 'USB/SESSION-DEAD' if 'no such device' in m.lower() or 'GenericUsb' in m else 'ERR'
        return f'{cat} {m[:100]} {time.time()-t0:.1f}s'

j=T.connect(A()); print('== session up ==', flush=True)
dead=False
for p in PATHS:
    try: r=one(j,p)
    except Exception as e: r='CRASH '+repr(e)[:100]
    print(f'{p:30s} {r}', flush=True)
    if 'SESSION-DEAD' in r or 'CRASH' in r: dead=True; break
if not dead:
    for d in DEVS:
        try:
            T.read_dev_twice(j, '/dev/'+d, os.path.join(DUMP, d+'.bin'), 2)
            print(f'== dump {d} done ==', flush=True)
        except Exception as e:
            print(f'== dump {d} FAIL {type(e).__name__}: {e} ==', flush=True); dead=True; break
try: j.stop()
except Exception: pass
print('== down dead=%s ==' % dead)
sys.exit(20 if dead else 0)
