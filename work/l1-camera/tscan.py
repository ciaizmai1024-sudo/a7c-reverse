#!/usr/bin/env python3
"""Thumb2 .text scanner: PLT calls (PLT stubs parsed from objdump @plt labels) + string refs.
usage: tscan.py <elf> [--str=SUB ...]"""
import sys, re, subprocess, struct, collections, bisect
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
    d,S=elf_secs(p)
    out=subprocess.run(['objdump','-d',p],capture_output=True,text=True).stdout
    stub={}          # vaddr -> sym
    for line in out.splitlines():
        m=re.match(r'^0*([0-9a-f]+) <(.+)@plt>:',line)
        if m: stub[int(m.group(1),16)]=m.group(2)
    labels={}
    for line in out.splitlines():
        m=re.match(r'^0*([0-9a-f]+) <([^>0][^>]*)>:',line)
        if m: labels[int(m.group(1),16)]=m.group(2)
    ls=sorted(labels)
    text=S['.text']; taddr,toff,tsize=text[3],text[4],text[5]
    md=capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    code=d[toff:toff+tsize]
    calls=collections.defaultdict(list)
    strrefs=collections.defaultdict(list)
    n=0
    for ins in md.disasm(code,taddr):
        n+=1
        if ins.mnemonic.startswith('bl') or ins.mnemonic=='b':
            m=re.search(r'(0x[0-9a-f]+)', ins.op_str)
            if m:
                t=int(m.group(1),16)
                if t in stub: calls[stub[t]].append(ins.address)
    # string vaddrs
    ro=S['.rodata']; roff,rova=ro[4],ro[3]
    strv={}; stroff={}
    for s in strs:
        i=d.find(s.encode())
        while i!=-1:
            if roff<=i<roff+ro[5]:
                strv[rova+(i-roff)]=s; stroff[s]=i
            i=d.find(s.encode(),i+1)
    # second pass for string refs (strv now populated)
    for ins in md.disasm(code,taddr):
        m=re.search(r'#(0x[0-9a-f]+)', ins.op_str)
        if m:
            v=int(m.group(1),16)
            if v in strv:
                fi=bisect.bisect_right(ls,ins.address)-1
                strrefs[strv[v]].append((hex(ins.address), labels[ls[fi]] if fi>=0 else '?'))
    print(f'disassembled {n} thumb insns in .text ({tsize} bytes)')
    print('== PLT/branch targets of interest ==')
    for sym,sites in sorted(calls.items(), key=lambda x:-len(x[1])):
        print(f'  {sym:<62} {len(sites):<4} {[hex(x) for x in sites[:6]]}')
    print('== string references ==')
    for s,vv in stroff.items():
        print(f'  {s!r} fileoff={vv:#x} vaddr={hex(rova+(vv-roff))} refs={strrefs.get(s,[])[:6]}')
main()
