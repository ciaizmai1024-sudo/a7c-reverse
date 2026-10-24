#!/usr/bin/env python3
import sys, os, struct
sys.path.insert(0,'/home/wubin/a7c-jiritsu/tools')
import jiritsu_send as T
OUT='/home/wubin/a7c-jiritsu/probe2'
PATHS='/usr/bin/sen.elf /usr/sbin/sen.elf /usr/bin/sauu.elf /usr/bin/mf.elf /usr/bin/udtrmain.sh /usr/bin/us_mkfs.sh /usr/bin/us_remove_modes.sh /usr/bin/change_mode.sh /usr/bin/endupdate.sh /usr/bin/us_crc32sum_appli.sh /usr/bin/ud_lerase.elf /usr/bin/ud_fsys_format.elf /usr/tool/libkmcsup.so'.split()
class A:
    mock=None; mock_dir=None; verbose=False; msc_pid=None; svc_pid=None
    usb_timeout=20000; wait_service=150; allow_danger=False
def local(p): return os.path.join(OUT,p.replace('/','_')+'.bin')
j=T.connect(A()); print('== up ==',flush=True)
for p in PATHS:
    try:
        with open(local(p)+'.part','wb') as f: j.fread(p,outFile=f)
        os.rename(local(p)+'.part',local(p))
        n=os.path.getsize(local(p)); print('%-32s OK %d'%(p,n),flush=True)
    except Exception as e:
        try: os.remove(local(p)+'.part')
        except Exception: pass
        print('%-32s %s'%(p,'ERR130' if '130' in str(e) else str(e)[:60]),flush=True)
import hashlib
for lbl,payload in [('AC 0x603 code1 (no data)',struct.pack('<HH',0x603,1)),
                    ('AC 0x603 code1 +4zero',struct.pack('<HH',0x603,1)+b'\0'*4),
                    ('AC 0x601 code0x1f',struct.pack('<HH',0x601,0x1f)),
                    ('PI cat0x0000 cmd0',struct.pack('<HH',0,0)),
                    ('PI 0x603 code1 read_hasp',struct.pack('<HH',0x603,1))]:
    for pf in (0x0000,0x0040,0xff07):
        try:
            r,o=j.pkt(pf,payload,retries=0)
            print('%-26s pfunc=0x%04x resp=%s len=%d %s'%(lbl,pf,r,len(o),o[:24].hex()),flush=True)
        except Exception as e:
            print('%-26s pfunc=0x%04x EXC %s'%(lbl,pf,type(e).__name__),flush=True)
try: j.stop()
except Exception: pass
