#!/usr/bin/env python3
"""Small ARM32 ELF helper built on capstone (Thumb-2 + ARM).

Subcommands:
  syms [REGEX]                 list dynamic symbols (defined + imported)
  funcs [REGEX]                defined function symbols with size
  relocs                       dynamic relocations with symbol names
  plt                          PLT stub address -> imported symbol
  dis START END [--arm]        annotated disassembly
  func NAME|ADDR               disassemble a function by symbol size
  xref VALUE                   find literal-pool words equal to VALUE
  strings [REGEX]              strings with virtual addresses
  data ADDR SIZE               dump bytes with reloc annotations
"""
import argparse
import re
import struct
import sys

from capstone import (Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB,
                      CS_OP_IMM, CS_OP_REG, CS_OP_MEM)
from capstone.arm import ARM_REG_PC, ARM_REG_IP


def arm_dp_imm(word):
    """Effective immediate of an ARM data-processing instruction."""
    imm8 = word & 0xFF
    rot = (word >> 8) & 0xF
    if rot == 0:
        return imm8
    return ((imm8 >> (2 * rot)) | (imm8 << (32 - 2 * rot))) & 0xFFFFFFFF


class ELF:
    def __init__(self, path):
        self.path = path
        self.data = open(path, "rb").read()
        d = self.data
        (self.e_type, self.e_machine, _ver, self.e_entry, self.e_phoff,
         self.e_shoff, self.e_flags, self.e_ehsize, self.e_phentsize,
         self.e_phnum, self.e_shentsize, self.e_shnum,
         self.e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", d, 16)
        self.phdrs = []
        for i in range(self.e_phnum):
            o = self.e_phoff + i * self.e_phentsize
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
                struct.unpack_from("<IIIIIIII", d, o)
            self.phdrs.append(dict(type=p_type, off=p_offset, vaddr=p_vaddr,
                                   paddr=p_paddr, filesz=p_filesz,
                                   memsz=p_memsz, flags=p_flags, align=p_align))
        self.shdrs = []
        for i in range(self.e_shnum):
            o = self.e_shoff + i * self.e_shentsize
            (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link,
             sh_info, sh_addralign, sh_entsize) = struct.unpack_from("<IIIIIIIIII", d, o)
            self.shdrs.append(dict(name_off=sh_name, type=sh_type, flags=sh_flags,
                                   addr=sh_addr, off=sh_offset, size=sh_size,
                                   link=sh_link, info=sh_info,
                                   align=sh_addralign, entsize=sh_entsize))
        shstr = self.shdrs[self.e_shstrndx]
        shstr_data = d[shstr["off"]:shstr["off"] + shstr["size"]]
        for sh in self.shdrs:
            end = shstr_data.find(b"\0", sh["name_off"])
            sh["name"] = shstr_data[sh["name_off"]:end].decode("latin1")
        self.sections = {s["name"]: s for s in self.shdrs}
        self._load_dynsym()
        self._load_relocs()
        self.plt_map = self._build_plt_map()

    def section(self, name):
        return self.sections.get(name)

    def vaddr_to_off(self, va):
        for p in self.phdrs:
            if p["type"] == 1 and p["vaddr"] <= va < p["vaddr"] + p["filesz"]:
                return p["off"] + (va - p["vaddr"])
        # fall back to section mapping
        for s in self.shdrs:
            if s["addr"] and s["addr"] <= va < s["addr"] + s["size"]:
                return s["off"] + (va - s["addr"])
        return None

    def read(self, va, size):
        off = self.vaddr_to_off(va)
        if off is None:
            return b"\0" * size
        chunk = self.data[off:off + size]
        if len(chunk) < size:
            chunk += b"\0" * (size - len(chunk))
        return chunk

    def u32(self, va):
        return struct.unpack("<I", self.read(va, 4))[0]

    def string_at(self, va, maxlen=300):
        if not va:
            return None
        off = self.vaddr_to_off(va)
        if off is None:
            return None
        end = self.data.find(b"\0", off, off + maxlen)
        if end < 0:
            end = off + maxlen
        raw = self.data[off:end]
        if not raw:
            return ""
        if all(32 <= c < 127 or c in (9, 10, 13) for c in raw):
            return raw.decode("latin1")
        return None

    def _dynstr(self, idx):
        sh = self.section(".dynstr")
        if not sh:
            return ""
        off = sh["off"] + idx
        end = self.data.find(b"\0", off)
        return self.data[off:end].decode("latin1", "replace")

    def _load_dynsym(self):
        self.syms = []
        self.sym_by_idx = []
        sh = self.section(".dynsym")
        if not sh:
            return
        n = sh["size"] // 16
        for i in range(n):
            o = sh["off"] + i * 16
            st_name, st_value, st_size, st_info, st_other, st_shndx = \
                struct.unpack_from("<IIIBBH", self.data, o)
            name = self._dynstr(st_name)
            entry = dict(idx=i, name=name, value=st_value,
                         size=st_size, info=st_info, other=st_other,
                         shndx=st_shndx,
                         bind=st_info >> 4, type=st_info & 0xF)
            self.sym_by_idx.append(entry)
            if not name:
                continue
            self.syms.append(entry)
        self.sym_by_addr = {}
        for s in self.syms:
            if s["shndx"] != 0 and s["value"]:
                self.sym_by_addr.setdefault(s["value"] & ~1, s)
        self.sym_by_name = {}
        for s in self.syms:
            self.sym_by_name.setdefault(s["name"], s)

    def _load_relocs(self):
        self.relocs = []
        for secname in (".rel.dyn", ".rel.plt", ".rela.dyn", ".rela.plt"):
            sh = self.section(secname)
            if not sh:
                continue
            entsize = sh["entsize"] or (8 if secname.startswith(".rel.") else 12)
            n = sh["size"] // entsize
            for i in range(n):
                o = sh["off"] + i * entsize
                r_offset, r_info = struct.unpack_from("<II", self.data, o)
                symidx = r_info >> 8
                rtype = r_info & 0xFF
                name = ""
                if symidx < len(self.sym_by_idx):
                    name = self.sym_by_idx[symidx]["name"]
                self.relocs.append(dict(offset=r_offset, type=rtype,
                                        symidx=symidx, name=name,
                                        section=secname))
        self.reloc_by_offset = {r["offset"]: r for r in self.relocs}

    def _build_plt_map(self):
        sh = self.section(".plt")
        if not sh:
            return {}
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        md.detail = True
        start = sh["addr"]
        end = sh["addr"] + sh["size"]
        out = {}
        code = self.data[sh["off"]:sh["off"] + sh["size"]]
        for rel in range(start + 20, end, 4):
            off = rel - start
            if off + 12 > len(code):
                break
            ins = list(md.disasm(code[off:off + 12], rel))
            if len(ins) != 3:
                continue
            a, b, c = ins
            if a.mnemonic != "add" or len(a.operands) < 3:
                continue
            if not (a.operands[0].type == CS_OP_REG and
                    a.reg_name(a.operands[0].reg) == "ip" and
                    a.operands[1].type == CS_OP_REG and
                    a.reg_name(a.operands[1].reg) == "pc"):
                continue
            if b.mnemonic != "add" or len(b.operands) != 3:
                continue
            if not (b.operands[0].type == CS_OP_REG and
                    b.reg_name(b.operands[0].reg) == "ip" and
                    b.operands[1].type == CS_OP_REG and
                    b.reg_name(b.operands[1].reg) == "ip" and
                    b.operands[2].type == CS_OP_IMM):
                continue
            if c.mnemonic != "ldr" or len(c.operands) != 2:
                continue
            if not (c.operands[0].type == CS_OP_REG and
                    c.reg_name(c.operands[0].reg) == "pc" and
                    c.operands[1].type == CS_OP_MEM and
                    c.reg_name(c.operands[1].mem.base) == "ip"):
                continue
            w1, w2 = struct.unpack_from("<II", code, off)
            ip = rel + 8 + arm_dp_imm(w1) + arm_dp_imm(w2)
            got = ip + c.operands[1].mem.disp
            r = self.reloc_by_offset.get(got)
            if r and r["name"]:
                out[rel] = r["name"]
        return out

    def nearest_symbol(self, va):
        best = None
        for a, s in self.sym_by_addr.items():
            if a <= va and (best is None or a > best[0]):
                best = (a, s)
        if not best:
            return None
        a, s = best
        if s["size"] and va >= a + s["size"]:
            return "%s+0x%x" % (s["name"], va - a)
        return s["name"] + ("+0x%x" % (va - a) if va > a else "")

    def in_rodata(self, va):
        s = self.section(".rodata")
        return bool(s and s["addr"] <= va < s["addr"] + s["size"])

    def disasm(self, start, end, arm=False):
        mode = CS_MODE_ARM if arm else CS_MODE_THUMB
        md = Cs(CS_ARCH_ARM, mode)
        md.detail = True
        self._pool_track = {}
        off = self.vaddr_to_off(start)
        code = self.data[off:off + (end - start)]
        lines = []
        pos = 0
        step = 4 if arm else 2
        while pos < len(code):
            found = False
            for ins in md.disasm(code[pos:], start + pos):
                found = True
                note = self._note(ins, arm)
                lines.append((ins.address, ins.bytes.hex(), ins.mnemonic,
                              ins.op_str, note))
                pos += ins.size
                if pos >= len(code):
                    break
            if not found:
                pos += step
        return lines

    def _note(self, ins, arm):
        notes = []
        mn = ins.mnemonic
        ops = ins.operands
        # direct branch to PLT / function
        if mn in ("bl", "blx", "b", "b.w", "bl.w") and ops and ops[0].type == CS_OP_IMM:
            tgt = ops[0].imm
            if tgt in self.plt_map:
                notes.append("-> PLT " + self.plt_map[tgt])
            elif self.section(".text") and self.section(".text")["addr"] <= tgt < self.section(".text")["addr"] + self.section(".text")["size"]:
                sym = self.nearest_symbol(tgt)
                if sym:
                    notes.append("-> " + sym)
        # pc-relative literal load
        if mn.startswith("ldr") and len(ops) >= 2 and ops[1].type == CS_OP_MEM \
                and ops[1].mem.base == ARM_REG_PC:
            if arm:
                pool = ins.address + 8 + ops[1].mem.disp
            else:
                pool = ((ins.address + 4) & ~3) + ops[1].mem.disp
            val = self.u32(pool)
            notes.append("pool@0x%x=%s" % (pool, self._describe_word(val)))
            if ops and ops[0].type == CS_OP_REG:
                self._pool_track[ops[0].reg] = val
        # adr / add rX, pc, #imm
        if mn == "adr" and len(ops) >= 2 and ops[1].type == CS_OP_IMM:
            notes.append("addr " + self._describe_word(ops[1].imm))
        # add rX, pc  (Thumb idiom: ldr rX,[pc,#pool]; add rX, pc)
        if mn == "add" and len(ops) == 2 and ops[1].type == CS_OP_REG \
                and ops[1].reg == ARM_REG_PC and ops[0].type == CS_OP_REG \
                and ops[0].reg in self._pool_track:
            base = ins.address + 4 if not arm else ins.address + 8
            tgt = base + self._pool_track[ops[0].reg]
            notes.append("str@0x%x %s" % (tgt, self._describe_word(tgt)))
        if mn == "add" and len(ops) == 3 and ops[1].type == CS_OP_REG \
                and ops[1].reg == ARM_REG_PC and ops[2].type == CS_OP_IMM:
            if arm:
                tgt = ins.address + 8 + ops[2].imm
            else:
                tgt = ins.address + 4 + ops[2].imm
            notes.append("addr " + self._describe_word(tgt))
        # immediate constants worth surfacing
        for op in ops:
            if op.type == CS_OP_IMM and op.imm > 0xffff:
                notes.append("imm=0x%x" % op.imm)
        return "; ".join(notes)

    def _describe_word(self, val):
        r = self.reloc_by_offset.get(val)
        if r and r["name"]:
            return "[GOT %s]" % r["name"]
        s = self.string_at(val)
        if s is not None and self.in_rodata(val):
            return '"%s"' % s.replace("\n", "\\n")[:110]
        if self.in_rodata(val):
            return "rodata+0x%x" % (val - self.section(".rodata")["addr"])
        return "0x%x" % val


def parse_int(s):
    return int(s, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--arm", action="store_true")
    a = ap.parse_args()
    e = ELF(a.elf)

    if a.cmd == "syms":
        pat = re.compile(a.args[0]) if a.args else None
        for s in sorted(e.syms, key=lambda x: (x["shndx"] == 0, x["value"])):
            if pat and not pat.search(s["name"]):
                continue
            print("0x%08x %6d %s %s" % (s["value"], s["size"],
                                         "UND" if s["shndx"] == 0 else "DEF",
                                         s["name"]))
    elif a.cmd == "funcs":
        pat = re.compile(a.args[0]) if a.args else None
        for s in sorted(e.syms, key=lambda x: x["value"]):
            if s["shndx"] == 0 or s["type"] != 2:
                continue
            if pat and not pat.search(s["name"]):
                continue
            print("0x%08x %6d %s" % (s["value"] & ~1, s["size"], s["name"]))
    elif a.cmd == "relocs":
        for r in e.relocs:
            if r["name"]:
                print("0x%08x type=%d %s" % (r["offset"], r["type"], r["name"]))
    elif a.cmd == "plt":
        for addr in sorted(e.plt_map):
            print("0x%08x %s" % (addr, e.plt_map[addr]))
    elif a.cmd == "dis":
        start, end = parse_int(a.args[0]), parse_int(a.args[1])
        for addr, raw, mn, op, note in e.disasm(start, end, a.arm):
            print("0x%08x  %-12s %-8s %-32s %s" % (addr, raw, mn, op, note))
    elif a.cmd == "func":
        key = a.args[0]
        s = e.sym_by_name.get(key)
        if s is None:
            s = next((x for x in e.syms if "0x%x" % (x["value"] & ~1) == key), None)
        if s is None:
            raise SystemExit("symbol not found: " + key)
        start = s["value"] & ~1
        end = start + (s["size"] or 0x200)
        for addr, raw, mn, op, note in e.disasm(start, end, a.arm):
            print("0x%08x  %-12s %-8s %-32s %s" % (addr, raw, mn, op, note))
    elif a.cmd == "xref":
        val = parse_int(a.args[0])
        pat = struct.pack("<I", val)
        for name in (".text", ".rodata", ".data", ".data.rel.ro", ".got"):
            sh = e.section(name)
            if not sh:
                continue
            blob = e.data[sh["off"]:sh["off"] + sh["size"]]
            i = 0
            while True:
                j = blob.find(pat, i)
                if j < 0:
                    break
                va = sh["addr"] + j
                print("0x%08x  %s  word=0x%x  %s" % (va, name, e.u32(va),
                                                     e.string_at(val) or ""))
                i = j + 1
    elif a.cmd == "strings":
        pat = re.compile(a.args[0]) if a.args else None
        for s in e.shdrs:
            if not s["addr"] or s["type"] == 8:
                continue
            blob = e.data[s["off"]:s["off"] + s["size"]]
            for m in re.finditer(rb"[\x20-\x7e\t\r\n]{4,}", blob):
                text = m.group().decode("latin1")
                if pat and not pat.search(text):
                    continue
                print("0x%08x  %s  %s" % (s["addr"] + m.start(), s["name"], text[:160]))
    elif a.cmd == "data":
        addr = parse_int(a.args[0])
        size = parse_int(a.args[1]) if len(a.args) > 1 else 64
        raw = e.read(addr, size)
        for i in range(0, len(raw), 16):
            chunk = raw[i:i + 16]
            words = []
            for j in range(0, len(chunk), 4):
                if j + 4 <= len(chunk):
                    w = struct.unpack_from("<I", chunk, j)[0]
                    r = e.reloc_by_offset.get(addr + i + j)
                    tag = ("[%s]" % r["name"]) if r and r["name"] else ""
                    words.append("%08x%s" % (w, tag))
            print("0x%08x  %-47s  %s" % (addr + i, " ".join(words),
                                         "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))
    else:
        raise SystemExit("unknown command: " + a.cmd)


if __name__ == "__main__":
    main()
