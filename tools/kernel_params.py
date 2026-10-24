#!/usr/bin/env python3
"""Dump kernel command-line parameter names and the KEMCO.txt parser facts.

Usage:
    python3 kernel_params.py /path/to/vmlinux.bin [--json]

The raw ARM32 vmlinux.bin used for this analysis is the one extracted from
a3 /system (link base 0x60108000).  Addresses printed are link-time VAs;
file offsets are what you need for hex editors.
"""
import json
import re
import sys
from pathlib import Path

BASE = 0x60108000          # link base of this vmlinux
KEMCO_PATCH_OFF = 0x391BF4  # setup_arch() KEMCO override patch
KEMCO_STRING_OFF = 0x347BF4 # "kemco"
KEMCO_PA = 0x60103000       # physical buffer the loader fills
KEMCO_LIMIT = 0x1000        # bytes scanned by the patch
STD_START = b"rdinit=\x00init=\x00loglevel\x00"
STD_END = b"ip=\x00"

CUSTOM_PREFIXES = (
    "warm", "wbi_cmpr", "cfg", "wdt", "pcie", "tmonitor", "pm", "bam",
    "pmon", "cmpr", "rmon", "hwbp", "hwbp_ctrl", "page_alloc", "mmu",
    "cache_l2x0", "pgd", "adrs_conv", "snsc_workqueue", "manage",
    "softirq", "exception", "klog", "alog", "basic", "stack_usage",
    "mmap", "dma_mapping", "printk", "spurious", "trace_kmalloc",
    "cxd900x0", "error", "exec", "time", "slab", "smp",
)


def va_off(va):
    return va - BASE


def cstr(d, off, maxlen=128):
    if off < 0 or off >= len(d):
        return None
    end = d.find(b"\x00", off, min(len(d), off + maxlen))
    if end < 0:
        return None
    try:
        return d[off:end].decode("ascii")
    except UnicodeDecodeError:
        return None


def standard_params(d):
    start = d.find(STD_START)
    if start < 0:
        return [], None, None
    end = d.find(STD_END, start)
    if end < 0:
        return [], None, None
    end += len(STD_END)
    names = []
    for raw in d[start:end].split(b"\x00"):
        if not raw:
            continue
        try:
            s = raw.decode("ascii")
        except UnicodeDecodeError:
            continue
        if re.fullmatch(r"[A-Za-z0-9_.-]+=?", s):
            names.append(s)
    return names, start, end


def custom_params(d):
    text = d.decode("latin1")
    toks = set()
    for m in re.finditer(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+=?", text):
        t = m.group()
        if len(t) >= 48:
            continue
        if t.endswith((".c", ".h", ".o", ".S")):
            continue
        if t.split(".")[0] in CUSTOM_PREFIXES:
            toks.add(t)
    return sorted(toks)


def kemco_facts(d, with_disasm=False):
    facts = {
        "patch_file_off": f"0x{KEMCO_PATCH_OFF:x}",
        "patch_va": f"0x{BASE + KEMCO_PATCH_OFF:08x}",
        "magic_file_off": f"0x{KEMCO_STRING_OFF:x}",
        "magic_va": f"0x{BASE + KEMCO_STRING_OFF:08x}",
        "physical_buffer": f"0x{KEMCO_PA:08x}",
        "max_scan_bytes": KEMCO_LIMIT,
    }
    # sanity check: literal pool at patch+0x500 holds PA 0x103000 and PA 0x103005
    lit = KEMCO_PATCH_OFF + 0x500
    lit0 = int.from_bytes(d[lit:lit + 4], "little")
    lit1 = int.from_bytes(d[lit + 4:lit + 8], "little")
    facts["patch_bytes_ok"] = (lit0 == KEMCO_PA and lit1 == KEMCO_PA + 5)
    facts["magic_bytes_ok"] = d[KEMCO_STRING_OFF:KEMCO_STRING_OFF + 5] == b"kemco"
    code = d[KEMCO_PATCH_OFF:KEMCO_PATCH_OFF + 0x50]
    if with_disasm:
        try:
            from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
        except ImportError:
            facts["disasm"] = "capstone not installed"
            return facts
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        facts["disasm"] = [
            f"{i.address:08x}: {i.mnemonic} {i.op_str}"
            for i in md.disasm(code, BASE + KEMCO_PATCH_OFF)
        ]
    return facts


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    d = Path(args[0]).read_bytes()
    std, s, e = standard_params(d)
    cus = custom_params(d)
    out = {
        "image": args[0],
        "size": len(d),
        "standard_params": std,
        "standard_blob_file_off": f"0x{s:x}" if s is not None else None,
        "standard_blob_end": f"0x{e:x}" if e is not None else None,
        "custom_param_tokens": cus,
        "kemco": kemco_facts(d, with_disasm="--disasm" in sys.argv),
        "notes": [
            "standard_params = Linux __setup string blob; 'single' is NOT present",
            "custom_param_tokens = dotted Sony names found in vmlinux strings; "
            "the exact acceptance/validation table was not fully reconstructed",
            "KEMCO.txt must begin with 'kemco' (lowercase) at PA 0x103000; "
            "the kernel parses the bytes after it",
        ],
    }
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
    else:
        print(f"image: {args[0]}  ({len(d)} bytes)")
        print(f"\nstandard kernel params ({len(std)}):")
        print("  " + " ".join(std))
        print(f"\ncustom/Sony param tokens ({len(cus)}):")
        for i in range(0, len(cus), 6):
            print("  " + " ".join(cus[i:i + 6]))
        print("\nKEMCO parser:")
        for k, v in out["kemco"].items():
            if k != "disasm":
                print(f"  {k}: {v}")
        if "disasm" in out["kemco"]:
            print("  disassembly:")
            for line in out["kemco"]["disasm"]:
                print("    " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
