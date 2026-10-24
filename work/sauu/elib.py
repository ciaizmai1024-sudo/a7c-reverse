#!/usr/bin/env python3
"""Minimal ARM32 ELF analysis lib (capstone-based) for sauu/mf.

Usage as a module: from elib import ELF
CLI:
  python3 elib.py <elf> syms [filter]
  python3 elib.py <elf> dis <vaddr> [len]
  python3 elib.py <elf> str <substring>
  python3 elib.py <elf> xref <vaddr>          (find literal-pool pointers to vaddr)
  python3 elib.py <elf> strx <substring>      (string -> literal ptrs -> code refs)
  python3 elib.py <elf> pltcall <symname>     (code sites calling a PLT stub)
"""
import sys, struct, re
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
from capstone.arm import *


class ELF:
    def __init__(self, path):
        self.path = path
        self.d = open(path, 'rb').read()
        (self.type, self.machine, self.version, self.entry, self.phoff, self.shoff,
         self.flags, self.ehsize, self.phentsize, self.phnum, self.shentsize,
         self.shnum, self.shstrndx) = struct.unpack_from('<HHIIIIIHHHHHH', self.d, 16)
        self.sh = {}
        self.shlist = []
        so = self.shoff + self.shstrndx * self.shentsize
        self.nmoff = struct.unpack_from('<IIIIIIIIII', self.d, so)[4]
        for i in range(self.shnum):
            o = self.shoff + i * self.shentsize
            x = struct.unpack_from('<IIIIIIIIII', self.d, o)
            name = self._strtab(self.nmoff, x[0])
            self.shlist.append(dict(name=name, type=x[1], flags=x[2], addr=x[3], off=x[4],
                                    size=x[5], link=x[6], info=x[7]) | {'entsize': x[9]})
            self.sh[name] = self.shlist[-1]
        self.dynsym = self.sec('.dynsym')
        self.dynstr = self.sh['.dynstr']
        self.load_plt()
        self.gotname = {}
        self.plt_of = {}
        self.pltsym = {}
        self.load_syms()
        self.cs_t = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        self.cs_t.detail = True
        self.cs_a = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        self.cs_a.detail = True

    def _strtab(self, base, n):
        z = self.d.index(b'\0', base + n)
        return self.d[base + n:z].decode('utf-8', 'replace')

    def sec(self, name):
        return self.sh.get(name)

    def bytes_at(self, vaddr, n):
        p = self.v2p(vaddr)
        if p is None:
            return b''
        return self.d[p:p + n]

    def v2p(self, v):
        for i in range(self.phnum):
            o = self.phoff + i * self.phentsize
            p_off, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from('<IIIII', self.d, o + 4)
            if p_vaddr <= v < p_vaddr + p_filesz:
                return p_off + (v - p_vaddr)
        return None

    def p2v(self, p):
        for i in range(self.phnum):
            o = self.phoff + i * self.phentsize
            p_off, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from('<IIIII', self.d, o + 4)
            if p_off <= p < p_off + p_filesz:
                return p_vaddr + (p - p_off)
        return None

    # ---------- symbols ----------
    def load_syms(self):
        self.syms = []
        byname = {}
        s = self.dynsym
        base = s['off']
        nsym = s['size'] // 16
        strb = self.dynstr['off']
        for i in range(nsym):
            o = base + i * 16
            st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from('<IIIBBH', self.d, o)
            nm = self._strtab(strb, st_name)
            si = dict(idx=i, name=nm, value=st_value, size=st_size, info=st_info,
                      other=st_other, shndx=st_shndx,
                      bind=st_info >> 4, typ=st_info & 0xf)
            self.syms.append(si)
            if nm:
                byname.setdefault(nm, si)
        self.byname = byname
        rd = self.sec('.rel.dyn')
        if rd:
            for i in range(rd['size'] // 8):
                off, info = struct.unpack_from('<II', self.d, rd['off'] + i * 8)
                self.gotname[off] = self.syms[info >> 8]['name']
        # plt stub -> name (via rel.plt)
        rp = self.sec('.rel.plt')
        self.plt_of = {}
        self.pltsym = {}
        if rp:
            n = rp['size'] // 8
            for i in range(n):
                off, info = struct.unpack_from('<II', self.d, rp['off'] + i * 8)
                si = info >> 8
                sym = self.syms[si]
                stub = self.got2stub.get(off)
                if stub is not None:
                    self.plt_of[sym['name']] = stub
                    self.pltsym[stub] = sym['name']

    def load_pltmap(self, fn):
        """load 'name addr' pairs produced from objdump .plt labels"""
        for line in open(fn):
            k, v = line.split()
            nm = k[:-4] if k.endswith('@plt') else k
            self.plt_of[nm] = int(v, 16)
            self.pltsym[int(v, 16)] = nm

    def load_plt(self):
        """ARM EABI PLT: PLT0 = 16 bytes; each entry 8 bytes:
           add.w pc, pc, #imm (2 instr, 8 bytes) ; then ldr pc,[..] hmm.
        Empirically detect: entries of 8 bytes at .plt+16, last word being a
        'ldr' -1 (0xe51ff004-style) is absent in thumb PLT. Instead we decode
        the 2-instruction stub and compute the GOT slot address it loads.
        """
        p = self.sec('.plt')
        self.got2stub = {}
        self.stublen = None
        if p is None:
            return
        start = p['addr']
        raw = self.bytes_at(start, p['size'])
        # PLT0 16 bytes, then each entry:  add pc,pc,#0xXX000000 ; ldr pc,[pc,#imm] (4+4)
        i = 16
        while i + 8 <= p['size']:
            w0 = struct.unpack_from('<I', raw, i)[0]
            w1 = struct.unpack_from('<I', raw, i + 4)[0]
            # add r12, pc, #(shifted)  : 0x28f00000-ish ; ldr pc,[r12,#imm] : 0x8fdfx000
            if (w0 & 0x00fff000) not in (0x08f00000, 0x00f00000) and (w0 >> 24) not in (0x28, 0x38, 0x2c, 0x3c, 0x34, 0x24):
                pass
            # compute the base A = pc(=start+i)+immed8 and the loaded slot = A + imm12*?
            a = (start + i) + ((w0 & 0x000000ff) << 8) + (w0 & 0x000f0000)
            slot = None
            if (w1 & 0xfff0f000) == 0x8df0f000:
                imm = w1 & 0x00000fff
                slot = a + imm
            elif (w1 & 0x0f00000) == 0 and (w1 >> 24) == 0xe5 and (w1 & 0x0000f000) == 0x1000:
                slot = a + (w1 & 0x00000fff)
            if slot is not None:
                self.got2stub[slot] = start + i
            i += 8
        self.stublen = 8

    # ---------- strings ----------
    def all_strings(self, minlen=4):
        out = []
        for name in ('.rodata', '.dynstr', '.data'):
            s = self.sec(name)
            if not s:
                continue
            raw = self.bytes_at(s['addr'], s['size']) or b''
            for m in re.finditer(rb'[\x20-\x7e]{%d,}' % minlen, raw):
                out.append((s['addr'] + m.start(), m.group().decode()))
        return out

    def findstr(self, pat, sections=('.rodata', '.data')):
        rx = re.compile(pat if isinstance(pat, str) else pat.decode())
        res = []
        for name in sections:
            s = self.sec(name)
            if not s:
                continue
            raw = self.bytes_at(s['addr'], s['size']) or b''
            for m in re.finditer(rb'[\x20-\x7e]{3,}', raw):
                st = m.group().decode()
                if rx.search(st):
                    res.append((s['addr'] + m.start(), st))
        return res

    # ---------- literal pools / xrefs ----------
    def xrefs_to(self, v):
        """scan .text for literal pool words equal to v, and report the pc-relative
        ldr sites that load them (approximate: report pool addr + all ldr [pc,#k] pointing there)."""
        res = []
        text = self.sec('.text')
        for secname in ('.text', '.data', '.rodata', '.init_array', '.got'):
            s = self.sec(secname)
            if not s:
                continue
            raw = self.bytes_at(s['addr'], s['size'])
            for i in range(0, len(raw) - 3, 4):
                if struct.unpack_from('<I', raw, i)[0] == v:
                    res.append(('poolword', s['addr'] + i))
        # code that does ldr rN,[pc,#k] where the target is one of those poolwords
        code = []
        p = self.v2p(text['addr'])
        raw = self.d[p:p + text['size']]
        for ins in self.cs_t.disasm(raw, text['addr']):
            if ins.mnemonic == 'ldr' and '[pc,' in ins.op_str or ins.mnemonic == 'ldr' and ins.op_str.endswith(', #0]'):
                m = re.search(r'\[pc,\s*#(-?0x[0-9a-f]+|-?\d+)\]', ins.op_str)
                if m:
                    k = int(m.group(1), 0)
                    tgt = ((ins.address + 4) & ~3) + k
                    if any(t[0] == 'poolword' and t[1] == tgt for t in res):
                        code.append(ins.address)
        return res, code

    def dis(self, v, n=256, thumb=None):
        if thumb is None:
            t = self.sec('.text')
            thumb = True if (t and t['addr'] <= v < t['addr'] + t['size']) else bool(v & 1)
        addr = v & ~1
        p = self.v2p(addr)
        if p is None:
            print('(no file offset for %08x)' % addr); return
        raw = self.d[p:p + n]
        cs = self.cs_t if thumb else self.cs_a
        import itertools
        def gen():
            a = addr
            i = 0
            while i < len(raw):
                got = False
                for ins in cs.disasm(raw[i:], addr + i, 1):
                    yield ins; got = True; i += ins.size
                if not got:
                    yield 'data', raw[i:i + 2], i
                    i += 2
        for ins in gen():
            if isinstance(ins, tuple):
                print('%08x  .short 0x%04x' % (addr + ins[2], struct.unpack('<H', ins[1])[0]))
                continue
            ann = ''
            if ins.mnemonic in ('ldr', 'ldrlsx') and re.search(r'\[pc[,\]]', ins.op_str):
                m = re.search(r'\[pc,?\s*(?:#(-?0x[0-9a-f]+|-?\d+))?\]', ins.op_str)
                k = int(m.group(1), 0) if m and m.group(1) else 0
                tgt = ((ins.address + 4) & ~3) + k
                tp = self.v2p(tgt)
                pv = struct.unpack_from('<I', self.d, tp)[0] if tp else 0
                s = self.cstr(pv) if pv else None
                ann = '  ; [%08x] = %08x' % (tgt, pv)
                if pv:
                    nm = self.pltsym.get(pv) or self.gotname.get(pv)
                    if nm:
                        ann += '  <%s>' % nm
                    if s:
                        ann += '  %r' % s
            if ins.mnemonic in ('bl', 'blx', 'b') and ins.op_str.startswith('#'):
                t = int(ins.op_str.lstrip('#'), 0)
                nm = self.pltsym.get(t) or self.sym_at(t)
                if nm:
                    ann = '  ; <%s>' % nm
            if ins.mnemonic == 'add' and ', pc' in ins.op_str:
                m = re.search(r'#(-?0x[0-9a-f]+|-?\d+)$', ins.op_str)
                if m:
                    ann += '  ; ~ %08x' % (ins.address + 4 + int(m.group(1), 0))
            print('%08x  %-8s %-30s %s' % (ins.address, ins.mnemonic, ins.op_str, ann))
        return

    def cstr(self, v, n=120):
        p = self.v2p(v)
        if p is None:
            return None
        z = self.d.index(b'\0', p) if b'\0' in self.d[p:p + n] else p + n
        raw = self.d[p:z]
        if raw and all(32 <= b < 127 for b in raw):
            return raw.decode()
        return None

    def sym_at(self, v):
        for s in self.syms:
            if s['value'] == v and s['name']:
                return s['name']
        return None

    def code_iter(self, secname='.text'):
        s = self.sec(secname)
        p = self.v2p(s['addr'])
        raw = self.d[p:p + s['size']]
        return self.cs_t.disasm(raw, s['addr'])

    def callers_of(self, target):
        return [i.address for i in self.code_iter()
                if i.mnemonic in ('bl', 'blx', 'b') and i.op_str.startswith('#')
                and int(i.op_str.lstrip('#'), 0) == target]

    def got_loads(self, slot):
        """code sites that ldr a literal whose value == slot (GOT load of an imported func)"""
        out = []
        for i in self.code_iter():
            if i.mnemonic == 'ldr' and re.search(r'\[pc[,\]]', i.op_str):
                m = re.search(r'\[pc,?\s*(?:#(-?0x[0-9a-f]+|-?\d+))?\]', i.op_str)
                k = int(m.group(1), 0) if m and m.group(1) else 0
                tgt = ((i.address + 4) & ~3) + k
                pv = self.v2p(tgt)
                if pv is not None and struct.unpack_from('<I', self.d, pv)[0] == slot:
                    out.append(i.address)
        return out

    def symtab_plt(self):
        return sorted(self.plt_of.items(), key=lambda x: x[1])


if __name__ == '__main__':
    e = ELF(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == 'syms':
        f = sys.argv[3] if len(sys.argv) > 3 else ''
        for k, v in e.symtab_plt():
            if f.lower() in k.lower():
                print('PLT %08x  %s' % (v, k))
        print('--- undefined/others matching filter')
        for s in e.syms:
            if s['shndx'] == 0 and f.lower() in s['name'].lower():
                print('UND %s' % s['name'])
    elif cmd == 'dis':
        e.dis(int(sys.argv[3], 16), int(sys.argv[4], 16) if len(sys.argv) > 4 else 256)
    elif cmd == 'str':
        for a, s in e.findstr(sys.argv[3]):
            print('%08x  %r' % (a, s))
    elif cmd == 'xref':
        v = int(sys.argv[3], 16)
        res, code = e.xrefs_to(v)
        for t, a in res:
            print('%s %08x' % (t, a))
        print('code sites:', [hex(x) for x in code])
    elif cmd == 'strx':
        for a, s in e.findstr(sys.argv[3]):
            print('STR %08x  %r' % (a, s))
            res, code = e.xrefs_to(a)
            for t, x in res:
                print('   pool %08x' % x)
            for c in code:
                print('   code %08x' % c)
    elif cmd == 'pltcall':
        nm = sys.argv[3]
        st = e.plt_of.get(nm)
        print('stub', hex(st) if st else None)
        if st:
            for c in e.callers_of(st):
                print('  caller %08x' % c)
