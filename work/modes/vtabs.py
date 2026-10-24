import struct,sys,json
sys.path.insert(0,'/Users/wubin/pi-cwd/sony/a7creverse/work/modes')
from elfio import parse,cstr_at
f=sys.argv[1]; lo=int(sys.argv[2],0) if len(sys.argv)>2 else 0; hi=int(sys.argv[3],0) if len(sys.argv)>3 else 0xffffffff
d,S=parse(f)
t=next(x for x in S if x['nm']=='.text')
def in_text(v): return t['addr']<=v<t['addr']+t['size'] and v&1
def rd(sec,va):
    return struct.unpack('<I',d[sec['off']+va-sec['addr']:sec['off']+va-sec['addr']+4])[0]
# typeinfo name lookup: _ZTS... strings in rodata; typeinfo structs _ZTV/_ZTI
names={}
for nm in ('.rodata','.data.rel.ro','.data'):
    sec=next((x for x in S if x['nm']==nm),None)
    if not sec: continue
    for va in range(sec['addr'],sec['addr']+sec['size']-8,4):
        v=rd(sec,va)
        # pointer to a _ZTS string
        s=cstr_at(d,S,v,120)
        if s and s.startswith('_ZTS'): names.setdefault(v,va)
        if sec['nm'] in ('.data.rel.ro','.data') and in_text(v):
            pass
for nm in ('.rodata','.data.rel.ro','.data'):
    sec=next((x for x in S if x['nm']==nm),None)
    if not sec: continue
    v=sec['addr']
    while v+40<=sec['addr']+sec['size']:
        if in_text(rd(sec,v)):
            start=v; k=0
            while in_text(rd(sec,start+k*4)): k+=1
            if k>=3 and lo<=start<=hi:
                # print vtable
                print('== vtable-ish @%#x (%s) : %d fn ptrs'%(start,sec['nm'],k))
                for i in range(k):
                    fv=rd(sec,start+i*4)
                    print('   +%#04x  %#x  slot=%#x'%(i*4,fv,start+i*4))
            v=start+k*4
        else:
            v+=4
