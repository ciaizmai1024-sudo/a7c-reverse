#!/usr/bin/env python3
"""Scan an ARM (Thumb2) ELF's .text for PLT calls + rodata string refs, grouped by function.
usage: sauu_scan.py <elf> [--str 'substring']... [--plt 'symsubstr']..."""
import sys, re, subprocess, struct, collections
import capstone

def elf_secs(p):
    d=open(p,'rb').read()
    e_shoff=struct.unpack_from('<I',d,0x20)[0]; esz=struct.unpack_from('<H',d,0x2e)[0]
    n=struct.unpack_from('<H',d,0x30)[0]; strx=struct.unpack_from('<H',d,0x32)[0]
    sh=[struct.unpack_from('<10I',d,e_shoff+i*esz) for i in range(n)]
    out={}
    for s in sh:
        nm=d[s[0]+sh[strx][4]:].split(b'\0')[0].decode()
        if nm: out[nm]=s
    return d,out

def main():
    p=sys.argv[1]
    strs=[a.split('=',1)[1] for a in sys.argv if a.startswith('--str=')]
    plts=[a.split('=',1)[1] for a in sys.argv if a.startswith('--plt=')]
    d,S=elf_secs(p)
    out=subprocess.run(['objdump','-d',p],capture_output=True,text=True).stdout
    plt={}   # stub vaddr -> sym
    for line in out.splitlines():
        m=re.match(r'^0*([0-9a-f]+) <(.+)@plt>:',line)
        if m: plt[int(m.group(1),16)]=m.group(2)
    # PLT call set: scan whole .text for 32-bit bl/blx encoding
    text=S['.text']; taddr,toff,tsize=text[3],text[4],text[5]
    calls=collections.defaultdict(list)   # plt sym -> [vaddr sites]
    for o in range(0,tsize-3,2):          # thumb: scan all 2-byte alignments
        w=struct.unpack_from('<H',d,toff+o)[0]
        if (w>>11)==0x1F:                 # BL/BL.W first halfword
            w2=struct.unpack_from('<H',d,toff+o+2)[0]
            if (w2>>11) in (0xD1,0x91,0xF1,0xC1):
                s=(w>>10)&1; j1=(w2>>13)&1; j2=(w2>>11)&1
                i1=1-j1; i2=1-j2
                imm10=w&0x3FF; imm11=w2&0x7FF
                imm=((s<<24)|(i1<<23)|(i2<<22)|(imm10<<12)|(imm11<<1))
                if s: imm-= 1<<25
                pc=taddr+((toff+o)-toff)+4
                t=pc+imm
                if t in plt: calls[plt[t]].append(taddr+((toff+o)-toff))
                # blx to non-plt (thumb interwork) target odd
    # also ARM-mode BL for completeness
    for o in range(0,tsize-3,4):
        w=struct.unpack_from('<I',d,toff+o)[0]
        if (w>>24) in (0xFA,0xEB,0xBA,0x9F):
            imm=w&0xFFFFFF
            if imm&0x800000: imm-=0x1000000
            t=taddr+o+8+imm*4
            if t in plt: calls[plt[t]].append(taddr+o)
    print('== PLT call sites (thumb+arm scan) ==')
    for sym,sites in sorted(calls.items(), key=lambda x:-len(x[1])):
        if plts and not any(q in sym for q in plts): continue
        print(f"  {sym:<60} {len(sites)} {list(map(hex,sites[:10]))}")
    print('  total distinct plt syms called:',len(calls))
    # string refs via capstone thumb linear sweep of .text
    ro=S['.rodata']; roff,rova=ro[4],ro[3]
    targets={}
    for s in strs:
        i=d.find(s.encode())
        while i!=-1:
            if roff<=i<roff+ro[5]: targets[rova+(i-roff)]=s
            i=d.find(s.encode(),i+1)
    print('== string vaddrs ==',{hex(k):v for k,v in targets.items()})
    md=capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    code=d[toff:toff+tsize]
    func=None
    # function starts from objdump labels
    labels={}
    for line in out.splitlines():
        m=re.match(r'^([0-9a-f]{4,16}) <',line)
        if m: labels[int(m.group(1),16)]=line.strip()
    ls=sorted(labels)
    import bisect
    for ins in md.disasm(code,taddr):
        if ins.mnemonic in ('ldr',) and '#' in ins.op_str and '[' not in ins.op_str:
            pass
        m=re.search(r'#(0x[0-9a-f]+)', ins.op_str)
        if m:
            v=int(m.group(1),16)
            if v in targets:
                fi=bisect.bisect_right(ls,ins.address)-1
                print(f"  str {targets[v]!r} @ins {ins.address:#x} in {labels[ls[fi]] if fi>=0 else '?'}")
        if ins.mnemonic.startswith('b') and ins.address in [s for ss in calls.values() for s in ss]:
            pass
    # report pc-relative ldr loads of string addresses (literal pools): scan .text words
    print('== literal-pool words pointing into .rodata string targets ==')
    for o in range(0,tsize-3,4):
        w=struct.unpack_from('<I',d,toff+o)[0]
        if w in targets:
            fi=bisect.bisect_right(ls,taddr+o)-1
            print(f"  word@{taddr+o:#x} -> {targets[w]!r} in {labels[ls[fi]].split('<')[1][:70] if fi>=0 else '?'}")
main()
