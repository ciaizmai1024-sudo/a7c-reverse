#!/usr/bin/env python3
"""L2-B: FileControl(0xff01) 路径存在性/大小矩阵。只读（cmd=2 / cmd=4 探测）。
每个路径都真读（cmd=2）到文件；异常时分类记录。会话死了就退出，由外层 wrap2.sh 重来。"""
import sys, os, struct, time, hashlib, traceback
sys.path.insert(0, '/home/wubin/a7c-jiritsu/tools')
import jiritsu_send as T

OUT = '/home/wubin/a7c-jiritsu/probe2'
PATHS = """
/setting/updater/mode
/setting/updater/mode1
/setting/updater/mode2
/setting/updater/mode3
/setting/updater/mode4
/setting/updater/mode5
/setting/updater/mode6
/setting/updater/comp
/setting/updater/uincomp
/setting/updater/debug
/setting/updater/dat4
/setting/updater/version.txt
/setting/updater/kikilog.dat
/setting/Backup.bin
/setting/updater/Backup.bin
/setting/partinf.conf
/setting/mount.conf
/setting/kemco.txt
/usr/bin/crypter.elf
/usr/bin/udtrbody.bin
/usr/bin/up.sh
/usr/bin/mf
/usr/bin/sauu
/tmp/jiritsu
/tmp/jiritsu/libJit.so
/tmp/jbusy
/tmp/etc/nsswitch.conf
/version.txt
""".split()

class A:
    mock = None; mock_dir = None; verbose = False; msc_pid = None; svc_pid = None
    usb_timeout = 20000; wait_service = 150; allow_danger = False

def local(p):
    return os.path.join(OUT, p.replace('/', '_') + '.bin')

def one(j, p):
    if os.path.exists(local(p)):
        n = os.path.getsize(local(p))
        h = hashlib.sha256(open(local(p), 'rb').read()).hexdigest()
        return f'OK(cached) size={n} sha={h[:16]} 0.0s'
    t0 = time.time()
    try:
        with open(local(p) + '.part', 'wb') as f:
            j.fread(p, outFile=f)
        os.rename(local(p) + '.part', local(p))
        n = os.path.getsize(local(p))
        h = hashlib.sha256(open(local(p), 'rb').read()).hexdigest()
        return f'OK size={n} sha={h[:16]} {time.time()-t0:.1f}s'
    except Exception as e:
        msg = f'{type(e).__name__}: {e}'
        try: os.remove(local(p) + '.part')
        except Exception: pass
        low = msg.lower()
        if 'error 130' in low: cat = 'ERR130(不存在/不可读/未挂载)'
        elif '10000006' in low: cat = 'ERR-10000006'
        elif 'timeout' in low or 'timed out' in low: cat = 'TIMEOUT'
        elif 'no such device' in low or 'usb' in low or 'exception' == type(e).__name__.lower(): cat = 'USB/SESSION-DEAD'
        else: cat = 'ERR'
        return f'{cat} {msg[:120]} {time.time()-t0:.1f}s'

dead = False
j = T.connect(A())
print('== session up ==', flush=True)
for p in PATHS:
    try:
        r = one(j, p)
    except Exception as e:
        r = 'CRASH ' + repr(e)[:120]
    print(f'{p:36s} {r}', flush=True)
    if 'SESSION-DEAD' in r or 'CRASH' in r:
        dead = True
        break
try: j.stop()
except Exception: pass
print('== session down, dead=%s ==' % dead, flush=True)
sys.exit(20 if dead else 0)
