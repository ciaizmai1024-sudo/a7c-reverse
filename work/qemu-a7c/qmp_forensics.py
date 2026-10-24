#!/usr/bin/env python3
"""Round3 reusable QMP forensics tool.

usage: qmp_forensics.py <sock> <reldir> <final_wait_secs> [snap_every_secs [addr:size[,addr:size...]]]

- Waits, taking periodic *small* snapshots of the kernel log_buf area (default
  PA 0x400000 len 0x100000, which covers .bss log ring at ~0x47d000) so that
  early messages / first oops [#0] are captured before the ring wraps.
- At final_wait: full memory dumps + registers + disasm (round2 compatible), then quits QEMU.
- Post-processes: locates the log_buf ring in every snapshot, extracts text in
  ring order, overlap-merges snapshots chronologically, writes <reldir>/logbuf.txt.

Paths for pmemsave are relative to the QEMU process cwd (this build rejects
leading '/'), so <reldir> must be relative and the tool should be started
from the same dir QEMU was started in (~/qemu-a7c).
"""
import socket, json, sys, time, os, re

sock_path, ddir, wait = sys.argv[1], sys.argv[2], int(sys.argv[3])
snap_every = int(sys.argv[4]) if len(sys.argv) > 4 else 10
snap_specs = sys.argv[5] if len(sys.argv) > 5 else "0x400000:0x100000"
SNAPS = [(int(a.split(":")[0], 16), int(a.split(":")[1], 16)) for a in snap_specs.split(",")]

os.makedirs(ddir, exist_ok=True)

def connect():
    for _ in range(120):
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(sock_path)
            return s
        except OSError:
            time.sleep(1)
    raise SystemExit("no qmp socket")

s = connect()
f = s.makefile("rw")

def send(obj):
    f.write(json.dumps(obj) + "\r\n"); f.flush()

def read():
    line = f.readline()
    return json.loads(line) if line else None

read()
send({"execute": "qmp_capabilities"}); read()

def hmp(cmd):
    send({"execute": "human-monitor-command", "arguments": {"command-line": cmd}})
    while True:
        r = read()
        if r is None:
            return ""
        if "return" in r:
            return r["return"] or ""

log = open(os.path.join(ddir, "forensics.log"), "w")
def P(*a):
    print(*a, flush=True); print(*a, file=log); log.flush()

t0 = time.time()
snap_files = []
while time.time() - t0 < wait:
    time.sleep(min(snap_every, wait - (time.time() - t0)))
    el = int(time.time() - t0)
    for (addr, size) in SNAPS:
        out = "%s/snap_%04d_%x.bin" % (ddir, el, addr)
        r = hmp("pmemsave 0x%X 0x%X %s" % (addr, size, out))
        if "error" in r.lower() or "Error" in r:
            P("snap t=%d 0x%X ERR %r" % (el, addr, r[:120]))
        else:
            snap_files.append((el, addr, out))
    P("snapshots t=%d: %d files" % (el, len(snap_files)))

regs = hmp("info registers")
P("=== info registers (full) ===")
P(regs)

def findreg(regs, pat, fallbacks=()):
    m = re.search(pat, regs, re.I)
    for fb in fallbacks:
        if not m:
            m = re.search(fb, regs, re.I)
        else:
            break
    return int(m.group(1), 16) if m else 0

sp = findreg(regs, r"R13\s*=\s*([0-9a-f]{1,8})", [r"sp\S*\s*=\s*0x([0-9a-f]{1,8})"])
pc = findreg(regs, r"R15\s*=\s*([0-9a-f]{1,8})", [r"pc\s*=\s*0x([0-9a-f]{1,8})"])
lr = findreg(regs, r"R14\s*=\s*([0-9a-f]{1,8})", [r"lr\s*=\s*0x([0-9a-f]{1,8})"])
P("SP=0x%X PC=0x%X LR=0x%X" % (sp, pc, lr))
P("=== x/80i at pc ===")
P(hmp("x /80i 0x%X" % pc))

for addr, size, out in [
        (0x60000000, 0x01200000, "kern.bin"),
        (0x00000000, 0x01000000, "lo.bin"),
        (0x01000000, 0x08000000, "ddra.bin"),
        (0x20000000, 0x00100000, "sram2.bin")]:
    r = hmp("pmemsave 0x%X 0x%X %s" % (addr, size, out))
    P("pmemsave %s 0x%X +%X -> %r" % (out, addr, size, r[:120]))
P("=== 2nd regs sample (+10s) ===")
time.sleep(10)
P(hmp("info registers"))
hmp("quit")
print("qemu quit", flush=True)
log.close()

# ---------------- post-process: extract + merge log_buf text ----------------
PRINTABLE = set(range(0x20, 0x7f)) | {0x09}

def lines_of(fn):
    """printable lines in raw address order (ring order within one snapshot)"""
    data = open(fn, "rb").read()
    out = []
    for chunk in re.split(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]+", data):
        pass
    # split strictly on newline-preserving walk to keep line order by offset
    pos = 0
    n = len(data)
    raw_lines = []
    cur = bytearray()
    for b in data:
        if b == 0x0a or b > 0x7f or (b < 0x20 and b != 0x09):
            if len(cur) >= 5:
                raw_lines.append(cur.decode("latin1").rstrip())
            cur = bytearray()
        else:
            cur.append(b)
    if len(cur) >= 5:
        raw_lines.append(cur.decode("latin1").rstrip())
    return [l for l in raw_lines if sum(c in PRINTABLE for c in l) >= len(l) * 0.9]

TS = re.compile(r"^\[\s*(\d+\.\d+)\]")

def wrap_rotate(lines):
    """ring may have wrapped once inside a snapshot: rotate at biggest ts drop"""
    tss = []
    last = None
    for l in lines:
        m = TS.match(l)
        if m:
            last = float(m.group(1))
        tss.append(last)
    worst, wi = 0.0, None
    for i in range(1, len(tss)):
        if tss[i] is not None and tss[i - 1] is not None:
            d = tss[i - 1] - tss[i]
            if d > worst:
                worst, wi = d, i
    if wi is not None and worst > 1.0:
        return lines[wi:] + lines[:wi]
    return lines

def merge(G, S):
    """overlap-merge: find largest k with S[:k] == suffix of G, append rest"""
    maxk = min(len(G), len(S), 4000)
    for k in range(maxk, 0, -1):
        if G[-k:] == S[:k]:
            return G + S[k:]
    # fuzzy: try dropping up to 3 lines at the seam
    for k in range(maxk, 0, -1):
        g, s = G[-k:], S[:k]
        mism = sum(1 for a, b in zip(g, s) if a != b)
        if mism <= 3:
            return G + S[k:]
    return G + ["--(no overlap)--"] + S

per_snap = []
for (el, addr, fn) in sorted(snap_files):
    ls = wrap_rotate(lines_of(fn))
    per_snap.append((el, fn, ls))
    P("snap %s t=%d: %d lines" % (fn, el, len(ls)))

G = []
for el, fn, ls in per_snap:
    if not ls:
        continue
    G = ls if not G else merge(G, ls)

out = os.path.join(ddir, "logbuf_raw.txt")
with open(out, "w") as fh:
    fh.write("\n".join(G) + "\n")
P("wrote %s (%d lines)" % (out, len(G)))

# clean view: only kernel-log-looking lines (timestamps, backtraces, oops context)
KEY = re.compile(r"(Linux version|Booting Linux|Machine|Memory|CPU|slab|SLUB|BUG|Oops|Unable to handle|Internal error|kernel BUG|init|VFS|Freeing|Run /init|Mounted|ramdisk|initrd|nflash|Udtr|kernel panic|try to access|Accesses|pgd|workqueue|Kernel command line)", re.I)
keep, inblk = [], False
for l in G:
    if TS.match(l) or l.startswith("<") or l.startswith("[<") or l.startswith("Exception stack") or l.startswith("Code:"):
        inblk = KEY.search(l) is not None or inblk
        keep.append(l)
    elif inblk and (l.strip() == "" or l.startswith("r") or l.startswith("pc :") or l.startswith("lr :") or l.startswith("sp :") or l.startswith("ips :") or l.startswith("psr :")):
        keep.append(l)
    elif l.startswith("2.6.") or l.startswith("3.0.") or l.startswith("CPU: "):
        keep.append(l)
out2 = os.path.join(ddir, "logbuf.txt")
with open(out2, "w") as fh:
    fh.write("\n".join(keep) + "\n")
P("wrote %s (%d lines kept)" % (out2, len(keep)))
