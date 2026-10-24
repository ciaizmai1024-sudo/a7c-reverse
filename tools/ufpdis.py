#!/usr/bin/env python3
"""纯 python ELF32(ARM) 注释型反汇编器（不依赖 r2）。

功能：
  * 自己解析 ELF 头 / phdr / shdr / shstrtab / .dynsym / .dynstr / .rel.dyn / .rel.plt / .plt
  * bl/blx -> PLT 桩（桩 = .plt+0x14+12*i，顺序 = .rel.plt 条目顺序）=> 导入符号名
  * ldr rN,[pc,#k] (+ add rN,pc [+ ldr rN,[rB,#k] / [rB,rI]]) 链
        -> GOT 槽名（.rel.dyn GLOB_DAT）/ .bss+.data 全局名 / .rodata 字符串
  * 字面量池按数据打印（两遍：第一遍收集所有被 ldr[pc] 引用的池地址）
  * mov/movw/movt 常量跟踪，cmp/mov 处直接给出十进制/尺寸提示

用法:
  python3 tools/ufpdis.py <elf> <start> <end> [--fns fns.txt] [--mode thumb|arm]
"""
import sys, struct, argparse
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB


class ELF:
    def __init__(self, path):
        self.B = open(path, 'rb').read()
        B = self.B
        assert B[:4] == b'\x7fELF' and B[4] == 1, 'not ELF32'
        (self.etype, self.emach, self.eversion, self.entry, self.phoff, self.shoff, self.flags,
         self.ehsize, self.phentsize, self.phnum, self.shentsize, self.shnum,
         self.shstrndx) = struct.unpack_from('<HHIIIIIHHHHHH', B, 0x10)
        self.ph = [struct.unpack_from('<IIIIIIII', B, self.phoff + i * self.phentsize)
                   for i in range(self.phnum)]
        self.sh = [struct.unpack_from('<IIIIIIIIII', B, self.shoff + i * self.shentsize)
                   for i in range(self.shnum)]
        shstr = self.sh[self.shstrndx]
        self.shname = {}
        for i, s in enumerate(self.sh):
            o = shstr[4] + s[0]
            self.shname[i] = B[o:B.index(b'\0', o)].decode('latin1')
        self.byname = {self.shname[i]: i for i in range(self.shnum)}

    def sec(self, nm):
        return self.sh[self.byname[nm]] if nm in self.byname else None

    def v2p(self, v):
        for t in self.ph:                      # (type off vaddr paddr filesz memsz flags align)
            if t[0] == 1 and t[2] <= v < t[2] + t[4]:
                return t[1] + (v - t[2])
        for s in self.sh:                      # (name type flags addr off size link info align entsize)
            if s[3] and s[1] != 8 and s[3] <= v < s[3] + s[5]:
                return s[4] + (v - s[3])
        return None

    def rd(self, v, n=4):
        p = self.v2p(v)
        if p is None or p + n > len(self.B):
            return None
        return int.from_bytes(self.B[p:p + n], 'little')

    def cstr(self, v, mx=140):
        sc = self.secname(v)
        if sc not in ('.rodata', '.data.rel.ro', '.data'):
            return None          # 只把真正的数据段地址当字符串，避免噪声
        p = self.v2p(v)
        if p is None:
            return None
        e = self.B.find(b'\0', p, p + mx + 1)
        if e < 0:
            return None
        t = self.B[p:e]
        try:
            t = t.decode('utf-8')
        except Exception:
            return None
        return t if t and all(32 <= ord(c) < 127 for c in t) else None

    def secname(self, v):
        for i, s in enumerate(self.sh):
            if s[3] and s[3] <= v < s[3] + max(s[5], 1) and s[1] != 0:
                return self.shname[i]
        return None


def parse(a):
    e = ELF(a.elf)
    B = e.B
    dstr = e.sec('.dynstr')
    dsym = e.sec('.dynsym')
    esz = dsym[9] or 16

    def sname(i):
        o = dstr[4] + i
        return B[o:B.index(b'\0', o)].decode('latin1')

    syms = []
    for i in range(dsym[5] // esz):
        o = dsym[4] + i * esz
        st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from('<IIIHBB', B, o)
        syms.append(dict(name=sname(st_name), value=st_value, size=st_size,
                         info=st_info, shndx=st_shndx, bind=st_info >> 4, typ=st_info & 0xf))
    relplt, reldyn = [], {}
    for sec, tgt in (('.rel.plt', relplt), ('.rel.dyn', reldyn)):
        s = e.sec(sec)
        if not s:
            continue
        for i in range(s[5] // 8):
            off, info = struct.unpack_from('<II', B, s[4] + i * 8)
            k = info >> 8
            nm = syms[k]['name'] if k < len(syms) else f'sym{k}'
            (tgt.append((off, nm, info & 0xff)) if isinstance(tgt, list) else tgt.__setitem__(off, (nm, info & 0xff)))
    plt = e.sec('.plt')
    got, bss, dat, dro = e.sec('.got'), e.sec('.bss'), e.sec('.data'), e.sec('.data.rel.ro')
    slot, bssn, gsize = {}, {}, {}
    for addr, (nm, rt) in reldyn.items():
        for s, d in ((got, slot), (bss, bssn), (dat, bssn), (dro, bssn)):
            if s and s[3] <= addr < s[3] + max(s[5], 1):
                d[addr] = nm
                break
    symval = {}
    for s in syms:
        if s['value'] and s['name']:
            symval.setdefault(s['value'] & ~1, s['name'])
        if s['typ'] == 1 and s['value'] and s['name']:      # OBJECT 全局（.bss/.data）
            gsize[s['value'] & ~1] = s['size']
            bssn[s['value'] & ~1] = s['name']
    symaddr = {s2['name']: s2['value'] for s2 in syms if s2['typ'] == 1 and s2['value']}
    stub, stubslot = scan_plt(e, relplt)
    return e, B, syms, relplt, reldyn, plt, stub, stubslot, slot, bssn, symval, gsize, symaddr


def _rotimm(w):
    rot = (w >> 8) & 0xf
    i4 = w & 0xf
    if not rot:
        return i4
    r = 2 * rot
    return ((i4 >> r) | (i4 << (32 - r))) & 0xffffffff


def _is_add_imm(w, rn, rd):     # ADD(imm) Rd, Rn, #imm12(rot)
    return (w >> 28) == 0xe and ((w >> 25) & 1) == 1 and ((w >> 21) & 0xf) == 4 \
        and ((w >> 20) & 1) == 0 and ((w >> 16) & 0xf) == rn and ((w >> 12) & 0xf) == rd


def _is_ldr_pc(w):             # LDR pc, [ip, #imm] (带写回)
    return (w >> 28) == 0xe and ((w >> 25) & 7) == 0b010 and ((w >> 20) & 1) == 1 \
        and ((w >> 16) & 0xf) == 12 and ((w >> 12) & 0xf) == 15


def scan_plt(e, relplt):
    """扫描 .plt 里的 ARM 模式 3 指令桩 (add ip,pc / add ip,ip / ldr pc,[ip,#k]!)，
    用算出来的 GOT 槽反查 .rel.plt 的符号名 —— 不靠“桩=基址+0x14+12*i”的假设（这里有个 4 字节缝隙会错位）。"""
    stub, stubslot, B = {}, {}, e.B
    if not e.sec('.plt'):
        return stub, stubslot
    p = e.sec('.plt')
    byslot = {off: nm for off, nm, rt in relplt}
    for A in range(p[3], p[3] + p[5] - 8, 4):
        w1, w2, w3 = struct.unpack_from('<III', B, A)
        if not (_is_add_imm(w1, 15, 12) and _is_add_imm(w2, 12, 12) and _is_ldr_pc(w3)):
            continue
        off3 = w3 & 0xfff
        if not (w3 >> 23) & 1:
            off3 = -off3
        got = (A + 8 + _rotimm(w1) + _rotimm(w2) + off3) & 0xffffffff
        if got in byslot:
            stub[A] = byslot[got]
            stubslot[A] = got
    if len(stub) < len(relplt):          # 扫不出来时退回简单假设
        for i, (off, nm, rt) in enumerate(relplt):
            sa = p[3] + 0x14 + i * 12
            stub.setdefault(sa, nm)
            stubslot.setdefault(sa, off)
    return stub, stubslot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('elf')
    ap.add_argument('start')
    ap.add_argument('end')
    ap.add_argument('--fns', default=None)
    ap.add_argument('--mode', default='thumb')
    a = ap.parse_args()
    (e, B, syms, relplt, reldyn, plt, stub, stubslot,
     slot, bssn, symval, gsize, symaddr) = parse(a)

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if a.mode == 'thumb' else CS_MODE_ARM)
    md.detail = True
    lo, hi = int(a.start, 0), int(a.end, 0)

    fns = {}
    if a.fns:
        for ln in open(a.fns):
            p = ln.split()
            if len(p) >= 2 and p[0].startswith('0x'):
                fns[int(p[0], 16)] = p[1].replace('sym.', '').replace('fcn.', '')

    fstarts = sorted(fns)

    def nextfn(x):
        for s in fstarts:
            if s > x:
                return s
        return None

    def name_of(x):
        if x is None:
            return None
        return slot.get(x) or bssn.get(x) or symval.get(x) or fns.get(x)

    def tag_addr(x, pre=''):
        s = f'{pre}{x:#x}'
        sn = name_of(x)
        if sn:
            s += f' <{sn}>'
        if x in gsize:
            s += f' (大小 {gsize[x]})'
        st = e.cstr(x)
        if st:
            s += f' = "{st}"'
        sc = e.secname(x)
        if sc and sc not in ('',):
            s += f' [{sc}]'
        return s

    def num(v):
        if v is None:
            return ''
        extra = ''
        for known in (0x10020, 65568, 0x10000, 24, 4, 0x18):
            pass
        return f' = {v} (0x{v:x})'

    # ---------- 两遍：先收集字面量池地址 ----------
    instub = set()
    for s0 in stub:
        instub |= {s0, s0 + 4, s0 + 8}

    def run(emit, pools=None):
        pool, base, mv = {}, {}, {}
        seen = set()
        addr = lo
        while addr < hi:
            if addr in fns:
                pool, base = {}, {}   # 跨函数不延续寄存器取值跟踪, 避免假的注释
            if pools is not None and addr in pools and addr % 4 == 0:
                if emit is not None:
                    v = e.rd(addr)
                    nm = name_of(v)
                    st = e.cstr(v)
                    txt = f'0x{v:08x}'
                    if nm:
                        txt += f'  <{nm}>'
                    if st:
                        txt += f'  -> "{st}"'
                    if v in slot:
                        txt += f'  GOT槽 <{slot[v]}>'
                    emit(f'{addr:#08x}  .word    {txt}')
                addr += 4
                continue
            nxt = None
            for ins in md.disasm(B[addr:addr + 8], addr):
                m, ops = ins.mnemonic, ins.op_str
                note = ''
                inplt = ins.address in instub
                if m in ('bl', 'blx'):
                    try:
                        t = int(ops.lstrip('#'), 16)
                    except ValueError:
                        t = None
                    if t is not None:
                        if t in stub:
                            note = f'  /* ==> {stub[t]}()   [PLT 桩 {t:#x}, GOT 槽 {stubslot[t]:#x}] */'
                        else:
                            nm2 = name_of(t & ~1)
                            note = f'  /* ==> {nm2 or hex(t)} */'
                elif m in ('b', 'b.w', 'bx', 'bl') and 'lr' in ops and m == 'bx':
                    note = ''
                elif inplt and m.startswith('ldr') and '[' in ops and 'pc' in ops[ops.index('['):ops.index(']')]:
                    pass
                elif m == 'ldr' and '[' in ops and 'pc' in ops[ops.index('['):ops.index(']')]:
                    dst = ops.split(',')[0].strip()
                    inner = ops[ops.index('[') + 1:ops.index(']')]
                    kk = inner.split(',')[1].strip().lstrip('#') if ',' in inner else '0'
                    try:
                        k = int(kk, 0)
                    except ValueError:
                        k = 0
                    la = ((ins.address + (8 if a.mode == 'arm' else 4)) & ~3) + k
                    seen.add(la)
                    val = e.rd(la)
                    pool[dst] = val
                    if val is not None:
                        note = f'  ;; 字面量池 @{la:#x} = {val:#x}'
                        nm2 = name_of(val) or slot.get(val)
                        if nm2:
                            note += f' <{nm2}>'
                        st = e.cstr(val)
                        if st:
                            note += f' -> "{st}"'
                        if val < 0x200:
                            note += f'  (小常数 {val}, 常作 GOT 索引/偏移)'
                elif m == 'add' and 'pc' in ops:
                    p = [x.strip() for x in ops.split(',')]
                    dst = p[0]
                    v = pool.get(dst, 0)
                    if v is None:
                        v = 0
                    if v >= 0x80000000:            # 负的 PC 相对偏移
                        v -= 0x100000000
                    imm = 0
                    if len(p) > 2:
                        try:
                            imm = int(p[2].lstrip('#'), 0)
                        except ValueError:
                            imm = 0
                    x = ins.address + (8 if a.mode == 'arm' else 4) + v + imm
                    base[dst] = x
                    pool[dst] = x
                    note = '' if inplt else '  ;; ==> ' + tag_addr(x)
                elif m in ('add', 'sub') and '[' not in ops:
                    p = [x.strip() for x in ops.split(',')]
                    if len(p) == 3 and p[1] in base and p[2] in pool and isinstance(pool[p[2]], int) \
                            and pool[p[2]] < 0x10000:
                        x = base[p[1]] + (pool[p[2]] if m == 'add' else -pool[p[2]])
                        base[p[0]] = x
                        pool[p[0]] = x
                        note = '  ;; ==> ' + tag_addr(x)
                    elif len(p) == 3 and p[1] in pool and p[2] in pool and \
                            isinstance(pool[p[1]], int) and isinstance(pool[p[2]], int):
                        pool[p[0]] = pool[p[1]] + pool[p[2]] if m == 'add' else pool[p[1]] - pool[p[2]]
                        note = f'  ;; = {pool[p[0]]:#x}'
                elif m in ('mov', 'mov.w', 'movw', 'movt', 'movs'):
                    p = [x.strip() for x in ops.split(',')]
                    if len(p) == 2 and p[1].startswith('#'):
                        try:
                            v = int(p[1].lstrip('#'), 0)
                        except ValueError:
                            v = None
                        if v is not None:
                            if m == 'movt':
                                mv[p[0]] = mv.get(p[0], 0) | (v << 16)
                            else:
                                mv[p[0]] = v
                            pool[p[0]] = mv[p[0]]
                            note = f'  ;; = {mv[p[0]]} (0x{mv[p[0]]:x})'
                            st = e.cstr(mv[p[0]])
                            if st:
                                note += f' -> "{st}"'
                            if mv[p[0]] in slot:
                                note += f' GOT槽 <{slot[mv[p[0]]]}>'
                elif m in ('cmp', 'subs', 'sub', 'cmp.w') and ops.rstrip().endswith(('#0', '')) is None:
                    pass
                elif m in ('cmp', 'subs', 'sub.w'):
                    p = [x.strip() for x in ops.split(',')]
                    if len(p) == 2 and p[1].startswith('#'):
                        note = f'  ;; 比较常数 {int(p[1].lstrip("#"),0)}'
                elif (m.startswith(('ldr', 'str', 'ldrb', 'strb', 'ldrh', 'strh', 'ldrsb', 'ldrsh',
                                    'ldrd', 'strd', 'ldm', 'stm', 'pld'))) and '[' in ops and \
                        'pc' not in ops[ops.index('['):ops.index(']')]:
                    dst = ops.split(',')[0].strip()
                    inner = ops[ops.index('[') + 1:ops.index(']')]
                    pp = [x.strip() for x in inner.split(',')]
                    b = pp[0]
                    k = 0
                    ok = True
                    if len(pp) > 1:
                        t2 = pp[1].lstrip('#')
                        if t2[:1].isdigit():
                            try:
                                k = int(t2, 0)
                            except ValueError:
                                ok = False
                        elif t2 in pool and isinstance(pool[t2], int) and pool[t2] < 0x100000:
                            k = pool[t2]
                        else:
                            ok = False
                    if ok:
                        if b in base:
                            x = base[b] + k
                            nm2 = name_of(x) or slot.get(x)
                            note = f'  ;; [{b}={x:#x}]' + (f' <{nm2}>' if nm2 else '') + \
                                   ('  <= 写入' if m.startswith(('str', 'stm')) else '')
                            if nm2 and m.startswith(('str', 'stm')):
                                note += f'  /* 写 {nm2} */'
                            if m.startswith(('ldr', 'ldm', 'ldr')):
                                val = e.rd(x)
                                if val in (0, None) and x in slot and slot[x] in symaddr:
                                    val = symaddr[slot[x]]        # 运行时 GOT 槽里放的是全局变量的地址
                                    note += f'  => 运行时 = {val:#x} (&{slot[x]})'
                                    pool[dst] = val
                                    base[dst] = val
                                if val is not None:
                                    note += f'  内存值 {val:#x}'
                                    nm3 = name_of(val) or slot.get(val)
                                    if nm3:
                                        note += f' <{nm3}>'
                                    st = e.cstr(val) or e.cstr(x)
                                    if st:
                                        note += f' -> "{st}"'
                                    if e.secname(x) in ('.bss', '.data') or val is not None:
                                        pool[dst] = val
                                elif nm2 and gsize.get(x if isinstance(x, int) else 0) is not None:
                                    note += ''
                        elif b in pool and isinstance(pool[b], int) and pool[b] > 0x100:
                            x = pool[b] + k
                            nm2 = name_of(x) or slot.get(x)
                            note = f'  ;; [{x:#x}]' + (f' <{nm2}>' if nm2 else '')
                            if m.startswith('ldr'):
                                val = e.rd(x)
                                if val is not None:
                                    note += f'  内存值 {val:#x}'
                                    nm3 = name_of(val) or slot.get(val)
                                    if nm3:
                                        note += f' <{nm3}>'
                                    st = e.cstr(val) or e.cstr(x)
                                    if st:
                                        note += f' -> "{st}"'
                                    pool[dst] = val
                if inplt:
                    note = ''
                if addr in stub and emit is not None:
                    emit(f'  ;; ---- PLT 桩 {addr:#x} -> 导入 {stub[addr]} (GOT {stubslot[addr]:#x})')
                if addr in fns and emit is not None:
                    emit('')
                    emit(f'/* ================= {fns[addr]} @ {addr:#x} ================= */')
                if emit is not None:
                    emit(f'{ins.address:#08x}  {m:9s} {ops:34s}{note}')
                nxt = ins.address + ins.size
                break
            if nxt is None:
                w = int.from_bytes(B[addr:addr + 2], 'little')
                if emit is not None:
                    emit(f'{addr:#08x}  .short   0x{w:04x}            ;; 无法解码')
                nxt = addr + 2
            # 重新同步: 若下一个函数入口点在附近, 则把中间剩下的字节当作字面量池, 直接跳到函数入口
            S = nextfn(addr)
            if S is not None and nxt != S and S - nxt <= 8:
                q = nxt
                while q < S:
                    w = int.from_bytes(B[q:q + 4], 'little')
                    if emit is not None:
                        nm = name_of(w)
                        emit(f'{q:#08x}  .word    0x{w:08x}' + (f'  <{nm}>' if nm else '') +
                             (f'  -> "{e.cstr(w)}"' if e.cstr(w) else ''))
                    q += 4
                nxt = S
            addr = nxt
        return seen

    pools = run(None)
    pools |= run(None, pools)
    out = []
    run(out.append, pools)
    print('\n'.join(out))


if __name__ == '__main__':
    main()
