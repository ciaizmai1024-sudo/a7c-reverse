#!/usr/bin/env python3
"""Tiny ARM/Thumb disassembler for the extracted 32-bit ELF files.

Annotates PC-relative literal loads with the literal value and any ASCII
string it points at, plus BL/BLX targets resolved through dynsym/symtab.

Usage:
  ./dis_arm.py FILE SYMBOL [--thumb|--arm] [--len N] [--all]
"""
import struct
import sys

from capstone import (CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_LITTLE_ENDIAN,
                      CS_MODE_THUMB, Cs)


class Elf:
    def __init__(self, path):
        self.d = open(path, "rb").read()
        assert self.d[:4] == b"\x7fELF" and self.d[4] == 1, "ELF32 only"
        e_shoff = struct.unpack_from("<I", self.d, 0x20)[0]
        e_shentsize = struct.unpack_from("<H", self.d, 0x2E)[0]
        e_shnum = struct.unpack_from("<H", self.d, 0x30)[0]
        e_shstrndx = struct.unpack_from("<H", self.d, 0x32)[0]
        self.secs = []
        for i in range(e_shnum):
            o = e_shoff + i * e_shentsize
            name, typ, flags, addr, off, size, link, info, align, ent = \
                struct.unpack_from("<10I", self.d, o)
            self.secs.append({"name_off": name, "type": typ, "flags": flags,
                              "addr": addr, "off": off, "size": size,
                              "link": link, "ent": ent})
        shstr = self.secs[e_shstrndx]
        base = shstr["off"]
        for s in self.secs:
            end = self.d.index(b"\0", base + s["name_off"])
            s["name"] = self.d[base + s["name_off"]:end].decode()
        self.syms = {}
        self.dynsyms = {}
        self.symlist = []
        self.plt_names = {}
        for s in self.secs:
            if s["type"] in (2, 11):  # SYMTAB, DYNSYM
                strtab = self.secs[s["link"]]
                n = s["size"] // s["ent"]
                lst = []
                for i in range(n):
                    o = s["off"] + i * s["ent"]
                    nm, val, sz, info, other, shndx = struct.unpack_from("<IIIBBH", self.d, o)
                    end = self.d.index(b"\0", strtab["off"] + nm)
                    name = self.d[strtab["off"] + nm:end].decode("utf-8", "replace")
                    if s["type"] == 11:
                        self.dynsyms[i] = name
                    if name and val:
                        lst.append((val & ~1, name, sz, shndx))
                        self.syms.setdefault(name, val & ~1)
                lst.sort()
                self.symlist = lst
        # map ARM PLT stubs to imported symbol names
        rel = next((s for s in self.secs if s["name"] == ".rel.plt"), None)
        plt = next((s for s in self.secs if s["name"] == ".plt"), None)
        if rel and plt:
            stubs = []
            for i in range(plt["size"] // 4):
                a = plt["addr"] + i * 4
                w = struct.unpack_from("<I", self.d, plt["off"] + i * 4)[0]
                if w == 0xE28FC600:  # add r12, pc, #0
                    q = struct.unpack_from("<II", self.d, plt["off"] + i * 4 + 4)
                    if q[0] == 0xE28CCA0D:
                        got = a + 8 + 0xD000 + (q[1] & 0xFFF)
                        stubs.append((got, a))
            rels = []
            for i in range(rel["size"] // 8):
                off, info = struct.unpack_from("<II", self.d, rel["off"] + i * 8)
                rels.append((off, self.dynsyms.get(info >> 8, "?")))
            relmap = dict(rels)
            for got, a in stubs:
                self.plt_names[a] = relmap.get(got, "plt?")

    def read(self, addr, n):
        for s in self.secs:
            if s["addr"] <= addr < s["addr"] + s["size"] and s["type"] != 8:
                return self.d[s["off"] + addr - s["addr"]:s["off"] + addr - s["addr"] + n]
        return b""

    def cstr(self, addr, maxlen=80):
        raw = self.read(addr, maxlen)
        out = []
        for b in raw:
            if b == 0:
                break
            if 32 <= b < 127:
                out.append(chr(b))
            else:
                return None
        return "".join(out) if len(out) >= 2 else None

    def fileoff(self, addr):
        for s in self.secs:
            if s["addr"] <= addr < s["addr"] + s["size"]:
                return s["off"] + addr - s["addr"]
        return None


def find_sym(elf, name, starts):
    for a, n, sz, sh in elf.symlist:
        if n == name:
            bigger = [x[0] for x in elf.symlist if x[0] > a]
            nxt = bigger[0] if bigger else a + 512
            end = min(a + sz, nxt) if sz else nxt
            return a, end
    return None


def dis(elf, start, end, thumb):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    code = elf.read(start, end - start)
    regs = {}
    for ins in md.disasm(code, start):
        note = ""
        ops = ins.operands
        pcv = ins.address + (4 if thumb else 8)
        # ldr rX, [pc, #imm] -> literal
        if ins.mnemonic.startswith("ldr") and len(ops) == 2 and ops[1].type == 3 \
                and md.reg_name(ops[1].mem.base) == "pc" and ops[0].type == 1:
            base = (ins.address + 4) & ~3 if thumb else ins.address + 8
            target = base + ops[1].mem.disp
            raw = elf.read(target, 4)
            if len(raw) == 4:
                val = struct.unpack("<I", raw)[0]
                regs[ops[0].reg] = val
                note = " ; lit@0x%x=0x%x" % (target, val)
                s = elf.cstr(val)
                if s:
                    note += ' "%s"' % s
        # add rX, pc -> position independent: literal is an offset
        elif ins.mnemonic == "add" and len(ops) == 2 and ops[1].type == 1 \
                and md.reg_name(ops[1].reg) == "pc" and ops[0].type == 1:
            if ops[0].reg in regs:
                val = (regs[ops[0].reg] + (ins.address + 4)) & 0xFFFFFFFF
                regs[ops[0].reg] = val
                s = elf.cstr(val)
                note = " ; ->0x%x" % val
                if s:
                    note += ' "%s"' % s
        elif ins.mnemonic in ("adr", "adr.w") and len(ops) == 2 and ops[0].type == 1:
            if ops[1].type == 2:
                regs[ops[0].reg] = ops[1].imm
                s = elf.cstr(ops[1].imm)
                note = " ; ->0x%x" % ops[1].imm
                if s:
                    note += ' "%s"' % s
        if ins.mnemonic in ("bl", "blx") and ops and ops[0].type == 2:
            t = ops[0].imm
            nm = elf.syms.get(t) or elf.plt_names.get(t)
            if nm:
                note += " ; -> %s" % nm
        print("  %04x: %-8s %-28s %s" % (ins.address, ins.bytes.hex(), ins.mnemonic + " " + ins.op_str, note))


def main():
    path, name = sys.argv[1], sys.argv[2]
    thumb = "--arm" not in sys.argv
    if "--thumb" in sys.argv:
        thumb = True
    elf = Elf(path)
    starts = dict((a, 1) for a, _, _, _ in elf.symlist)
    r = find_sym(elf, name, starts)
    if not r:
        raise SystemExit("symbol not found: " + name)
    start, end = r
    if "--len" in sys.argv:
        start = start
        end = start + int(sys.argv[sys.argv.index("--len") + 1])
    print("== %s %s 0x%x..0x%x ==" % (name, "thumb" if thumb else "arm", start, end))
    dis(elf, start, end, thumb)


if __name__ == "__main__":
    main()
