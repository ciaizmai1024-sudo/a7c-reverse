#!/usr/bin/env python3
"""Function-aware string xrefs / PLT call resolution for ARM32 ELF.

Usage:
  python3 elfxref.py refs <elf> <literal>...     # who references a string
  python3 elfxref.py pltcalls <elf> <regex>      # who calls imported symbol(s)
  python3 elfxref.py imports <elf> <regex>       # list imported symbols
  python3 elfxref.py dis <elf> <addr> [n] [arm|thumb]
"""
import re
import struct
import sys

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

STT_FUNC = 2
PT_LOAD = 1


class Elf:
    def __init__(self, path):
        self.path = path
        self.d = open(path, "rb").read()
        d = self.d
        assert d[:4] == b"\x7fELF" and d[4] == 1, "ELF32 only"
        (self.e_type, self.e_machine, _, self.e_entry, self.e_phoff, self.e_shoff,
         self.e_flags, _, self.e_phentsize, self.e_phnum, self.e_shentsize,
         self.e_shnum, self.e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", d, 16)
        self.secs = []
        for i in range(self.e_shnum):
            o = self.e_shoff + i * self.e_shentsize
            v = struct.unpack_from("<IIIIIIIIII", d, o)
            self.secs.append({"name_off": v[0], "type": v[1], "flags": v[2], "addr": v[3],
                              "off": v[4], "size": v[5], "link": v[6], "info": v[7],
                              "align": v[8], "entsize": v[9]})
        shstr = self.secs[self.e_shstrndx]["off"]

        def nm(o):
            e = d.find(b"\0", shstr + o)
            return d[shstr + o:e].decode("latin1")
        for s in self.secs:
            s["name"] = nm(s["name_off"])
        self.seg = []
        for i in range(self.e_phnum):
            o = self.e_phoff + i * self.e_phentsize
            t, off, va, pa, fs, ms, fl, al = struct.unpack_from("<IIIIIIII", d, o)
            if t == PT_LOAD:
                self.seg.append((off, va, fs))
        self.syms = self._syms(2) + self._syms(11)
        self.syms.sort(key=lambda s: (s["value"] & ~1))
        self.imports = [s for s in self._syms(11) if s["shndx"] == 0 and s["name"]]

    def _syms(self, typ):
        out = []
        for s in self.secs:
            if s["type"] != typ or not s["entsize"]:
                continue
            st = self.secs[s["link"]]
            base, sb = st["off"], s["off"]
            for o in range(sb, sb + s["size"], s["entsize"]):
                name, value, size, info, other, shndx = struct.unpack_from("<IIIBBH", self.d, o)
                e = self.d.find(b"\0", base + name)
                out.append({"name": self.d[base + name:e].decode("latin1"),
                            "value": value, "size": size, "type": info & 0xF,
                            "bind": info >> 4, "shndx": shndx})
        return out

    def va2off(self, va):
        for off, va0, fs in self.seg:
            if va0 <= va < va0 + fs:
                return off + (va - va0)
        return None

    def off2va(self, off):
        for o, va0, fs in self.seg:
            if o <= off < o + fs:
                return va0 + (off - o)
        return None

    def funcs(self):
        if getattr(self, "_funcs", None):
            return self._funcs
        named = {}
        for s in self.syms:
            a = s["value"] & ~1
            if s["type"] == STT_FUNC and a not in named:
                named[a] = s
        # .ARM.exidx gives reliable ranges even for local/stripped functions
        ex = next((s for s in self.secs if s["name"] == ".ARM.exidx"), None)
        ranges = {}
        if ex and ex["size"]:
            starts = []
            for o in range(ex["off"], ex["off"] + ex["size"], 8):
                w, info = struct.unpack_from("<II", self.d, o)
                place = ex["addr"] + (o - ex["off"])
                off = w & 0x7FFFFFFF
                if off & 0x40000000:
                    off -= 0x80000000
                starts.append(((place + off) & 0xFFFFFFFF) & ~1)
            starts = sorted(set(starts))
            for i, a in enumerate(starts):
                end = starts[i + 1] if i + 1 < len(starts) else a + 0x1000
                ranges[a] = max(4, end - a)
        out = []
        for a in sorted(set(named) | set(ranges)):
            s = named.get(a) or {"name": "sub_%x" % a, "value": a, "size": 0,
                                 "type": STT_FUNC, "shndx": 0}
            a2 = s["value"] & ~1
            size = max(s["size"], ranges.get(a, 0))
            if not size:
                continue
            # synthetic (exidx-only) code in these binaries is Thumb-2
            flag = (s["value"] & 1) if a in named else 1
            out.append({"name": s["name"], "value": (a2 | flag),
                        "size": size, "type": STT_FUNC, "shndx": s["shndx"]})
        out.sort(key=lambda s: s["value"] & ~1)
        self._funcs = out
        return out

    def func_at(self, addr):
        best = None
        for s in self.funcs():
            a = s["value"] & ~1
            if a <= addr < a + s["size"] and (best is None or a > (best["value"] & ~1)):
                best = s
        return best

    def disasm(self, start, size, thumb):
        off = self.va2off(start)
        if off is None:
            return []
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        return list(md.disasm(self.d[off:off + size], start))

    def string_va(self, needle):
        off = self.d.find(needle.encode())
        return None if off < 0 else self.off2va(off)

    def literal_slots(self, va, exec_only=False):
        pat = struct.pack("<I", va)
        out = []
        for s in self.secs:
            if s["type"] == 8 or not s["size"]:
                continue
            if exec_only and not (s["flags"] & 4):
                continue
            data = self.d[s["off"]:s["off"] + s["size"]]
            p = 0
            while True:
                i = data.find(pat, p)
                if i < 0:
                    break
                out.append(s["addr"] + i)
                p = i + 4
        return out

    def str_refs(self, needle):
        """Return [(func, insn_addr, how)] for all code that materialises string VA."""
        va = self.string_va(needle)
        if va is None:
            return None, []
        slots = self.literal_slots(va)
        hits = []
        wanted = set(slots) | {va}
        for f in self.funcs():
            a = f["value"] & ~1
            if not f["size"] or a == 0:
                continue
            thumb = bool(f["value"] & 1)
            insns = self.disasm(a, f["size"], thumb)
            for i, ins in enumerate(insns):
                tgt = None
                how = ""
                if ins.mnemonic in ("ldr", "ldr.w") and len(ins.operands) >= 2 \
                        and ins.operands[0].type == ARM_OP_REG:
                    mem = ins.operands[1]
                    if mem.type == ARM_OP_MEM and mem.mem.base == ARM_REG_PC:
                        pool = (((ins.address + 4) & ~3) + mem.mem.disp if thumb
                                else ins.address + 8 + mem.mem.disp)
                        if pool in wanted:
                            tgt, how = pool, "literal@%#x" % pool
                        else:
                            # GCC PIC: pool holds an offset, next insn is add rX, pc
                            off = self.va2off(pool)
                            nxt = insns[i + 1] if i + 1 < len(insns) else None
                            if off is not None and nxt and nxt.mnemonic.startswith("add"):
                                ops = nxt.operands
                                same = ops and ops[0].type == ARM_OP_REG and \
                                    ops[0].reg == ins.operands[0].reg
                                has_pc = any(o.type == ARM_OP_REG and o.reg == ARM_REG_PC
                                             for o in ops)
                                if same and has_pc:
                                    w = struct.unpack_from("<I", self.d, off)[0]
                                    bases = [(nxt.address + 4) & ~3, nxt.address + 4] if thumb \
                                        else [nxt.address + 8]
                                    for base in bases:
                                        cand = (base + w) & 0xFFFFFFFF
                                        if cand in wanted:
                                            tgt, how = cand, "pc+pooloff"
                                            break
                elif ins.mnemonic in ("adr", "adr.w") and len(ins.operands) >= 2 \
                        and ins.operands[-1].type == ARM_OP_IMM:
                    imm = ins.operands[-1].imm
                    tgt = ((ins.address + 4) & ~3) + imm if thumb else ins.address + 8 + imm
                    how = "adr"
                elif ins.mnemonic.startswith("add") and ins.operands:
                    # add rX, pc, #imm  -> address of literal string
                    regs = [o.reg for o in ins.operands if o.type == ARM_OP_REG]
                    if ARM_REG_PC in regs and len(ins.operands) > 1 and ins.operands[-1].type == ARM_OP_IMM:
                        imm = ins.operands[-1].imm
                        tgt = ((ins.address + 4) & ~3) + imm if thumb else ins.address + 8 + imm
                        how = "pc+imm"
                if tgt in wanted:
                    hits.append((f, ins.address, how or ("literal@%#x" % tgt)))
        return va, hits

    def plt_map(self):
        """stub address -> imported symbol name (ARM PLT)."""
        plt = next((s for s in self.secs if s["name"] == ".plt"), None)
        rel = next((s for s in self.secs if s["name"] in (".rel.plt", ".rela.plt")), None)
        if not plt or not rel:
            return {}
        dynsym = next(s for s in self.secs if s["name"] == ".dynsym")
        dstr = self.secs[dynsym["link"]]["off"]
        relocs = []
        esz = rel["entsize"] or 8
        for o in range(rel["off"], rel["off"] + rel["size"], esz):
            r_off, r_info = struct.unpack_from("<II", self.d, o)
            symi = r_info >> 8
            so = dynsym["off"] + symi * (dynsym["entsize"] or 16)
            name_off = struct.unpack_from("<I", self.d, so)[0]
            e = self.d.find(b"\0", dstr + name_off)
            relocs.append((r_off, self.d[dstr + name_off:e].decode("latin1")))
        # ARM PLT: PLT0 = 20 bytes, then 12-byte stubs; the linker may insert
        # 4-byte ARM/Thumb veneers (bx pc; nop), so scan instead of striding.
        # `add ip, ip, #imm, #rot` carries a rotated immediate (e.g. #24,#20 = 0x18000).
        def eff_imm(op):
            if len(ins_ops) >= 4 and ins_ops[3].type == ARM_OP_IMM:
                rot = ins_ops[3].imm & 0x3F
                v = op.imm & 0xFFFFFFFF
                return ((v >> rot) | (v << (32 - rot))) & 0xFFFFFFFF if rot else v
            return op.imm
        got2sym = {got: name for got, name in relocs}
        out, cur, end = {}, plt["addr"] + 20, plt["addr"] + plt["size"]
        while cur < end:
            ins = self.disasm(cur, 12, False)
            if len(ins) >= 3 and ins[0].mnemonic == "add" and ins[2].mnemonic.startswith("ldr"):
                try:
                    ins_ops = ins[0].operands
                    imm0 = eff_imm(ins_ops[2])
                    ins_ops = ins[1].operands
                    imm1 = eff_imm(ins_ops[2])
                    mem = next(o for o in ins[2].operands if o.type == ARM_OP_MEM)
                    slot = cur + 8 + imm0 + imm1 + mem.mem.disp
                except Exception:
                    slot = None
                if slot in got2sym:
                    out[cur] = got2sym[slot]
                    cur += 12
                    continue
            cur += 4
        return out

    def calls_to(self, targets):
        """Return [(func, insn_addr, target)] for bl/blx to target addresses."""
        hits = []
        for f in self.funcs():
            a = f["value"] & ~1
            if not f["size"] or a == 0:
                continue
            thumb = bool(f["value"] & 1)
            for ins in self.disasm(a, f["size"], thumb):
                if ins.mnemonic in ("bl", "blx", "b", "b.w") and ins.operands and \
                        ins.operands[0].type == ARM_OP_IMM:
                    t = ins.operands[0].imm & ~1
                    if t in targets:
                        hits.append((f, ins.address, t, ins.mnemonic))
        return hits


def main():
    cmd = sys.argv[1]
    e = Elf(sys.argv[2])
    if cmd == "refs":
        for needle in sys.argv[3:]:
            va, hits = e.str_refs(needle)
            print("### %r va=%s" % (needle, hex(va) if va is not None else "NOT FOUND"))
            seen = set()
            for f, at, how in hits:
                key = (f["value"] & ~1, at)
                if key in seen:
                    continue
                seen.add(key)
                print("  %s+0x%x  at %#x  (%s)" % (f["name"], at - (f["value"] & ~1), at, how))
    elif cmd == "pltcalls":
        pat = re.compile(sys.argv[3])
        pm = e.plt_map()
        want = {k: v for k, v in pm.items() if pat.search(v)}
        print("PLT stubs matched: %s" % {hex(k): v for k, v in want.items()})
        hits = e.calls_to(set(want))
        for f, at, t, mn in hits:
            print("  %s+0x%x  %#x %s -> %s" % (f["name"], at - (f["value"] & ~1), at, mn, want[t]))
    elif cmd == "imports":
        pat = re.compile(sys.argv[3])
        for s in e.imports:
            if pat.search(s["name"]):
                print(s["name"])
    elif cmd == "dis":
        addr = int(sys.argv[3], 0)
        n = int(sys.argv[4], 0) if len(sys.argv) > 4 else 128
        mode = sys.argv[5] if len(sys.argv) > 5 else ("thumb" if (e.func_at(addr) or {}).get("value", 0) & 1 else "arm")
        f = e.func_at(addr)
        pm = e.plt_map()
        print("; func=%s" % (f["name"] if f else "?"))
        thumb = mode == "thumb"
        pend = {}
        for ins in e.disasm(addr, n, thumb):
            note = ""
            ops = ins.operands
            if ins.mnemonic.startswith("ldr") and len(ops) >= 2 and ops[0].type == ARM_OP_REG \
                    and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
                lit = ((ins.address + 4) & ~3) + ops[1].mem.disp if thumb else ins.address + 8 + ops[1].mem.disp
                off = e.va2off(lit)
                if off is not None and off + 4 <= len(e.d):
                    pend[ops[0].reg] = struct.unpack_from("<I", e.d, off)[0]
            if ins.mnemonic.startswith("add") and ops and ops[0].type == ARM_OP_REG \
                    and any(o.type == ARM_OP_REG and o.reg == ARM_REG_PC for o in ops):
                w = pend.get(ops[0].reg)
                if w is not None:
                    cand = (ins.address + 4 + w) & 0xFFFFFFFF
                    o2 = e.va2off(cand)
                    if o2 is not None:
                        sb = e.d[o2:o2 + 64].split(b"\0")[0]
                        if len(sb) >= 3 and all(32 <= c < 127 for c in sb):
                            note = "  = %r" % sb.decode()
            if ins.mnemonic in ("bl", "blx", "b", "b.w") and ops and ops[0].type == ARM_OP_IMM:
                t = ops[0].imm & ~1
                if t in pm:
                    note = "  -> %s" % pm[t]
                else:
                    g = e.func_at(t)
                    if g:
                        note = "  -> %s" % g["name"]
            elif ins.mnemonic.startswith("ldr") and len(ops) >= 2 and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
                if thumb:
                    lit = ((ins.address + 4) & ~3) + ops[1].mem.disp
                else:
                    lit = ins.address + 8 + ops[1].mem.disp
                off = e.va2off(lit)
                if off is not None and off + 4 <= len(e.d):
                    w = struct.unpack_from("<I", e.d, off)[0]
                    note = "  ; [%#x]=%#x" % (lit, w)
                    o2 = e.va2off(w)
                    if o2 is not None:
                        s = e.d[o2:o2 + 64].split(b"\0")[0]
                        if len(s) >= 3 and all(32 <= c < 127 for c in s):
                            note += " = %r" % s.decode()
            print("%08x  %-10s %s %s%s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str, note))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
