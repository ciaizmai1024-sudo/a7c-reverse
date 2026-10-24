# A7C QEMU updater-boot-chain attempt (2026-10-23, remote build on 172.22.22.131)

## TL;DR
- QEMU 5.1.0 (ma1co/qemu + zve10 bionz/sd-cid patches + our A7C edits) **builds and runs** on Ubuntu 24.04; `cxd90045` machine present.
- A7C eMMC image built to device-exact layout (1,288 MiB sparse, 439 MiB real).
- First visible result: **`Uncompressing Linux.... done, booting the kernel.`** then silence;
  QMP probe shows kernel decompressed to its compile-time link address **0x60000000** and spins
  forever in a lock/poll loop at **0x603643bc** (LDREX/STREX + "wait until [r4]!=0", r4 -> kernel
  data containing a `"ttyAM"` string). Zero `-d unimp` hits.

## QEMU build (remote ~/qemu-a7c/qemu-sony)
- base: `refs/zve10-qemu/patches/qemu/{bionz.patch,sd-cid.patch}` applied, A7C edits pre-done
  (TEXT_OFFSET 0x108000, INITRD 0x700000, cmdline written to 0x103000+0x133000, load_wbi disabled,
  ATAGS + bootloader r1=3497).
- **Additional fixes made in this session** (all in `hw/arm/bionz.c` unless noted):
  1. `0x133000` cmdline write disabled for A7C: the kernel blob (0x108000..0x2A6534) overlaps it,
     and 5.1's `rom_check_and_register_reset()` aborts on rom overlap ("rom: requested regions
     overlap"). A direct-RAM write would be wiped by rom_reset re-copy (rom_reset registers after
     machine init in vl.c). Left `cxd90045_write_cmdline_mem()` in tree for a future mr-based fix.
  2. `CXD90045_DDR0_SIZE 0x40000000 -> 0x80000000`: A7C zImage decompresses to link addr 0x60000000
     (inside the old 1G-2G hole); with 1G DDR0 the kernel ran on unmapped memory (all reads 0).
  3. added 2 MiB RAM at **0x20000000** ("sram2"): real kernel reserves `memrsv=0x20000000@0x20000000:uc`
     and uses 0x20021xxx (wbi_memclr/em_console); unmapped = writes dropped = self-poll deadlock.
  4. `stubs/machine-init-done.c`: definitions marked `__attribute__((weak))` — 5.1.0 (ma1co master)
     has the vl.c/stub multiple-definition link bug under gcc-13/binutils; tools still get the stub.
  5. `ui/keycodemapdb` submodule was empty; cloned master first, then pinned to v5.1.0's gitlink
     commit **6b3d716** (master's keymap-gen CLI is incompatible: `invalid choice: 'glib2'`).
- configure: `./configure --target-list=arm-softmmu --disable-docs --disable-werror --extra-cflags="-fcommon -Wno-error"`
  needed extra apt pkgs: libpixman-1-dev libslirp-dev device-tree-compiler libjpeg-dev zlib1g-dev
  libpng-dev libmad0-dev libfdt-dev git (slirp=system, fdt=system).
- **gcc-13.3 worked; gcc-11 NOT required** (installed as fallback but unused). Full build ~8 min at -j6.
- Artifact: `~/qemu-a7c/qemu-sony/arm-softmmu/qemu-system-arm`; `-machine help | grep cxd90045` ->
  `cxd90045  Sony BIONZ CXD90045`.

## eMMC image (remote ~/qemu-a7c/a7c_emmc.img, built by build_emmc_a7c.py)
Device-exact layout from partinf.conf (parsed); md5 f89d5f165fc7b95655ff17a9e972aca2:
| part | offset | size | source |
|---|---|---|---|
| (EXBL/boot0) | 0x00000000 | 0x10000 | zeros (**we still lack this dump**) |
| a1 | 0x00010000 | 7.94M | **camera** nflasha1.bin |
| a2 | 0x00800000 | 20M | **camera** |
| a3 | 0x01C00000 | 48M | pkg nflasha3 (30.3M used) |
| a4 | 0x04C00000 | 12M | **camera** |
| a5 | 0x05800000 | 60M | pkg nflasha5 (32.6M used) |
| a6 | 0x09400000 | 16M | **camera** |
| a7 | 0x0A400000 | 8M | pkg nflasha7 (4.99M) — **no camera a7 dump exists** (task sheet's "a7 8MB camera" not in l2-camera) |
| a10 | 0x0AC00000 | 12M | **camera** |
| a11 | 0x0B800000 | 500M | zeros (risk: updater may want vfat /log) |
| a12 | 0x2AC00000 | 40M | zeros (no source) |
| a13 | 0x2D400000 | 4M | **camera** |
| a15 | 0x2D800000 | 300M | **camera** nflasha15.bin |
| a16/a17/a18 | ... | | zeros (no source) |
| a23 | 0x50800000 | 2M | **camera** |
- end = 0x50A00000 (1,352,663,040 B).

## Runs (run_qemu_a7c.sh; `-serial file:run_a.log`, eMMC via `-drive if=mtd`)
1. plain: QEMU abort `rom: requested regions overlap (rom cmdline, free=0x2a6534 addr=0x133000)` -> fix #1.
2. after fix #1: serial `Uncompressing Linux.... done, booting the kernel.` (zImage magic OK, atags/
   MACH_TYPE 3497 OK!) then nothing; -d unimp log **empty**.
3. QMP probe: PC stuck 0x603643bc, SP 0x604399xx — i.e. kernel runs at PA 0x60000000 (zImage
   CONFIG_ZRELADDR), in the DDR hole -> fix #2 (DDR0=2G).
4. after fix #2: same serial stop, but code at PC is real: spin `ldrex/strex [r4]` + `ldr [r4];cmp 0;beq`
   at 0x60364350..0x603643d4, r4=0x6047e5dc, memory there has `ttyA|tyAM` string bytes; PSR I/F masked;
   identical across samples -> deterministic spin, not slow boot.
5. trimmed cmdline (drop wbi_memclr/em_console/stack_usage): no change.
6. after fix #3 (sram2@0x20000000): no change; -d unimp still 0 lines; klog buffer 0x034A0000 window readable but zero-filled.

## What's missing / next steps
- **EXBL (0x00000000-0x00010000) not dumped yet** -> EXBL boot route (`-bios`-less loader2 path)
  still impossible; keep using -kernel.
- **A7C WBI (9 segments, table in nflasha5 "WBI1" header, hdrlen 0x290)**: loader in bionz.c is
  ZV-E10's 7-seg table and disabled. If updater needs backup.ko data, implement WBI1-table loader
  (src offset = a5 start 0x05800000 + header; dst addrs incl. 0x2002xxxx/0x20200000 need sram2-style maps).
- **The hang at 0x603643bc**: kernel spins waiting for a flag in a structure containing "ttyAM".
  Candidates: (a) waiting on a kthread/IRQ-driven completion (watchdog wdt, hwtimer, SD/eMMC IRQ path);
  (b) console/ttyAM registration handshake Sony kernels do via SRAM flags; (c) percpu/lock init
  issue. Next: arm the Sony `wdt.timeout=500` (panic after 500s guest) or `-watchdog-timer`,
  and bisect by stubbing; also try `-d in_asm` tail to identify the function (0x60364340/0x60361f8c)
  against a System.map from the updater kernel if one can be extracted.
- a11 /log is zeros — updater may reject non-vfat /log later (known risk, cheap to fix: mkfs.vfat fill).
- eMMC access in guest: kernel socemmc/cxd driver maps nflasha* from this raw backing at partinf
  offsets (boot0 area is first 64K of the file in our layout).

## Files
- `build_emmc_a7c.py` (this dir) — runs on remote, writes ~/qemu-a7c/a7c_emmc.img
- `run_qemu_a7c.sh` (this dir) — on remote ~/qemu-a7c/, cmdline = kemco.txt minus `kemco`/`*` lines
- `qmp_probe.py` — QMP HMP sampler (info registers / x/i)
- `results/` — build.log, configure.log, run_a.log* (all serial logs), qmp_probe.log, unimp2.log.try7 (empty), run*.out
- patched sources live in local `qemu-sony/` (identical to remote ~/qemu-a7c/qemu-sony; keep them in sync)

---

# Round 2 (2026-10-24): readable diagnosis + device-exact eMMC

## T1 image fixes (build_emmc_a7c.py, rebuilt a7c_emmc.img)
- **a7 (/rootfs) = real camera dump** work/l1-camera/nflasha7.bin (8,388,608 B @ img off 0x0A400000).
  Byte-identical to pkg copy for first 4,992,000 B; rest is slot padding. **Correction to task sheet:
  raw partitions have NO 0x400 header** - ext2 magic EF53 sits at partition offset 0x438 = standard
  superblock at FS offset 0x400 with FS at partition offset 0 (superblock fields sane: 4.99 MB fs,
  1K blocks, uuid 0000...0020:0020). So mpr driver must eat the whole partition raw with FS at 0.
- **a11(/log,500MB @0x0B800000), a12(/cert,40MB @0x2AC00000), a17(/android/data,100MB @0x49000000),
  a18(/lens,20MB @0x4F400000) = fresh valid vfat** (mkfs.vfat -n M, exact slot size, mkdosfs-default
  geometry - the camera's real vfats a2/a6/a10/a13 are all "mkdosfs" FAT12 1K clusters, NOT the
  ClusterSize 16384 from mount.conf; mount.conf cluster size is a mount-time parameter only).
- a16 (/android/system): no pkg/camera copy exists in firmware.tar -> still zeros. a3 = pkg nflasha3
  (30,290,944 B of 50,331,648 slot; confirmed pkg is shorter than device). image end 0x50A00000.

## T2/T3 THE HANG IS DECODED: kernel log_buf found, kernel oops-loops, then spins on console mutex
- Registers identical at t=120s and t=140s: PC=0x603643bc LR=0x603643e8 R13(sp_und)=0x60439980
  R4=0x6047e5dc, PSR=200001d3 (IRQ+FIQ masked, svc32). QEMU 5.1 gotchas learned: HMP `pmemsave`
  rejects filenames starting with '/' (use relative paths); `x`/`info registers` use VAs (MMU is ON:
  VA 0x60xxxxxx -> PA 0x00xxxxxx, PAGE_OFFSET=0x60000000, "nl" kernel). The old klog probe at
  0x034A0000 failed because klog= is Sony's own console-replay buffer, unused here; real log_buf
  is in kernel .bss around **PA 0x0047d000-0x004bd000** (found via strings on PA 0..16MB dump).
- Kernel identity: **Linux 3.0.27_nl-rt106 SMP PREEMPT RT, #1 May 14 2020, gcc 4.5.1 Sony CE 8.2.6.0**,
  text 0x60108000-0x6041c024, .bss ends 0x604bd918, lowmem 0x60000000-0xdf800000 (2040MB).
- Last readable log_buf (chronological, key lines - full text in results/round2/forensics.log
  + analysis/strings_sorted.txt around 0x48EF22..0x48F340):
    [<6042d818>] (kmem_cache_init) from [<6041d6b8>] (start_kernel+0x16c/0x444)
    [<601a6c28>] (kmem_cache_create+0x3a8/0x43c) from kmem_cache_init+0x274
    [<60356910>] (setup_cpu_cache+0xc8/0x194) from kmem_cache_create
    [<601a4114>] (kmem_cache_alloc_node+0x120/0x1a8) from setup_cpu_cache
    [<601a3fd4>] (____cache_alloc_node+0x0/0x140)  <- DataAbort (do_translation_fault, DFSC 0x805)
    Exception stack(0x60447e80...): df000000 ... r8:df000000 r4:601a4074; r4=7fc001c0 r8=7fc01160
    -> die() -> panic() (because pid 0 swapper) -> **kernel BUG at kernel/panic.c:106!** ->
    that oops faulted again (NULL+0, then 0x000000cc, then 5d6aec2c) -> recursive oops
    (Oops #12, #13 ... each re-prints full register/stack dump through vprintk, timestamps
    0.137..0.1527 in main run; 0.207..0.230 in maxcpus/fullroot runs).
- Spin loop decoded (from monitor x/80i, confirmed identical semantics):
    0x603643bc: ldr r3,[r4]; cmp 0; beq 0x60364350 ; mutex->owner==0 -> try acquire
    0x603643c8: ldr r3,[r4,#4]; cmp 0; bne 0x603643bc ; owner!=0 && waiters!=0 -> spin forever
    (0x60364414-0x6036443c = mutex trylock with ldrex/strex + cp15 per-cpu lock-depth [r3,#4],
     0x60361f8c called when lock has waiters flag bit2 -> that is the rt-mutex/slow-path waiter queue)
  i.e. **mutex_lock slowpath waiting for the owner of a mutex at 0x6047e5dc whose adjacent field
  (+8) is the string 'ttyAM' -> the console/ttyAM0 port mutex**. The console-flush path re-enters
  the lock the oops-killer already holds -> classic 3.0-rt oops-vs-console deadlock. Root fault is
  the slab-init abort, NOT the spin.
- Poor-man's backtrace (live): sp(und)=0x60439980 dump words in text range: none (stale und-bank);
  authoritative backtrace is the kernel's own from log_buf (above). log_buf read/wrap pointers:
  not exported as symbols in this non-kallsyms... actually kallsyms IS present (traces show names).
  log_buf ring content spans ~0x6047d000-0x60490000, ring apparently small (only 0.10-0.15s kept).
## T4 results (results/round2/fwdump_maxcpus0, fwdump_fullroot)
- (a) maxcpus=0: identical crash, same spin PC, same kmem_cache_init trace. No change.
- (b) Sony bootparam names: not available yet (sony-src agent), skipped.
- (c) full-root boot (NO initrd, root=/dev/nflasha7): identical crash at slab init BEFORE any VFS
  message; no 'VFS: Unable to mount root' because kernel never reaches mount. So mpr/nflash partition
  driver question is still untestable with this updater kernel.
## What full-system boot still needs (order of operations)
1) fix the slab-init translation fault (likely memory map mismatch: try DDR0=1GB + 1GB *alias*
   window at 0x40000000-0x80000000 (memory_region_init_alias over first 1GB, matching the real
   CXD90045 mirror that makes link-at-0x60000000 == PA 0 work) + DDR1 RAM at 0x80000000 sized
   >=1016MB; current flat 2GB DDR0 may not match the nl-kernel's bank expectations).
2) then console must flush (ttyAM UART modeled - it emitted only the decompressor line so far;
   kernel console writes go through the ttyAM driver that is deadlocking - watch after fix 1).
3) then /dev/nflasha* from mtd/mpr driver against our partinf-exact image (all vfat slots now
   valid, a7 has real rootfs with /init? check a7_ext2_tree.txt in l1-camera for init binary).
4) EXBL/boot0 dump still missing for the true updater flow.
## Next-round hooks
- `run_sony_kernel.sh` (this dir): skeleton for the GPL kernel from sony-src agent; set SONY_KERNEL=.
- `qmp_forensics.py`: wait N sec then regs+disasm+PA dumps (relative-path pmemsave, works on this build).
- `run_round2.sh [wait] [-append=... [NOINITRD]] [extra qemu args]`; `analyze_round2.sh` = strings/
  forensics pipeline over fwdump/. `t4_round2.sh` = the two experiment runs.
- Artifacts here: results/round2/{forensics.log, analysis/{strings_*.txt,hits.txt,spin_disasm.txt},
  fwdump_maxcpus0/, fwdump_fullroot/} (remote: ~/qemu-a7c/fwdump*, round2_*.log).
