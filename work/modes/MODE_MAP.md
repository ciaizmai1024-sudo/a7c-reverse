# A7C (ILCE-7C v2.00, CXD90045) — flag files ⇄ `UPDATER_ACTION_MODE` numbers

Static analysis only; nothing in the firmware tree was modified.
Generated artefacts (all read-only outputs) live in `work/modes/`:
`disasm.py`, `pltfix.py`, `pltgen.py`, `elfio.py`, `vtabs.py`,
`{body,common,ufp,crypter}_text.asm`, `plt_{body,common,ufp,crypter}.json`.

Analysed objects (Thumb-2, 32-bit ARM ELFs):

| object | path (under `firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/`) | `.text` |
|---|---|---|
| `libupdaterbody.so` | `bin/udtrbody.bin_unpacked/bodylib/libupdaterbody.so` | 0xe0e4–0x16138 |
| `libupdatercommon.so` | `lib/libupdatercommon.so` | (flag-file classes) |
| `libupdaterufp.so` | `lib/libupdaterufp.so` | 0x10cc–0x27aa |
| `crypter.elf` | `usr/bin/crypter.elf` | 0xab40–0xe790 (ET_EXEC, base 0x8000) |

> **Address caveat.** Disassembly is linear from each `.text` start; branch targets
> (switch arms, virtual calls) can land 2 bytes "inside" a 32-bit Thumb instruction, so pcrel
> string annotations are sometimes ±2 off (e.g. printed `0x16573` → real `0x16575`).
> Function addresses quoted below are **confirmed against `.dynsym`** (`nm -D --defined-only`),
> which resolves all naming ambiguities: e.g. `StartUpdate = 0x14e48`,
> `ShellPlugin::Execute = 0x13de8`, `FlagFirmwareInformationHandler ctor = 0x15c28`.

---

## 1. Canonical numeric enum (`UPDATER_ACTION_MODE`)

Independent cross-check from the shell side (the number arrives as `$1` and in the env):

```
us_mkfs.sh      : 1 PRODUCT, 2 LOADER_UPDATER, 3 USER, 4 SERVICE, 5 MINOR, 6 MSCRYPT, 7 VERSKIP
body_common.sh  : 3 = user update, 4 = service update, 5 = minor update
common.src      : (OLDER numbering, used only for *flag-file names*)
                  MODE_USER=0, MODE_PROD=1, MODE_SERVICE=2, MODE_MINOR=3, MODE_VERSKIP=6
```

## 2. Flag-file names (single source of truth)

`libupdatercommon.so .rodata`, all relative to a mount-point argument:
```
0x7ada "updater/mode"   0x7ae7 "updater/mode1"  0x7af5 "updater/mode2"
0x7b03 "updater/mode3"  0x7b11 "updater/mode5"  0x7b1f "updater/mode6"
0x7b2d "updater/comp"   (+ 0x789b "updater/dat4", 0x78a8 "dat2", 0x78ad "dat3")
```
Constructors (`BaseFlagFile(dir,name)`, PLT `0x5078`): `ModeFlagFile 0x6b46`,
`Mode1FlagFile 0x6b76`, `Mode2FlagFile 0x6ba2`, `Mode3FlagFile 0x6bcc`,
`Mode5FlagFile 0x6bf8`, `Mode6FlagFile 0x6c24`, `CompleteFlagFile 0x6c50`.
**There is no `mode4` file and no `Mode4FlagFile` class** (`nm` confirms).
`BaseFlagFile::Create` = `open`+`fsync`+`close` (FlagFiles.cpp 0x1d/0x22/0x25, code `0x6a28`);
`Delete` = `unlink` (line 0x31, `0x69bc`); `IsValid` = existence test
(`0x6996`: `add r0,#4; GetCharString; bl 0x77fc; rsbs r0,r0,#1`).

## 3. Q1 — THE numeric ⇄ flag-file mapping

### 3.1 Definitive translation site (body, forward direction)

`Updater::FlagFirmwareInformationHandler::StartUpdate()` — **`libupdaterbody.so` 0x14e48**
(`FlagFirmwareInformationHandler.cpp`, `__FILE__` string at `.rodata 0x16eb2`):

```
14e54 MountPoint ctor
14e5e blx [this]+0x30        ; guard virtual: non-zero -> skip everything (0x1503e)
14e6c MountPoint::Initialize("/tmp_updater/updater/current")      ; .rodata 0x16575
14e7c MountPoint::Mount("/dev/nflasha2", 0x410)                   ; .rodata 0x16412
14e82 ldr r3,[this,#4]       ; r3 = UPDATER_ACTION_MODE (stored by the ctor)
14e84 subs r2,r3,#1 ; cmp r2,#1 ; bls 0x1503e   ; mode 1,2 -> no flag handling at all
14e8c cmp r3,#4     ; beq 0x1503e               ; mode 4 (SERVICE) -> none at all
14e98 printf ; ApiException(0x3000e, line 0x66)  ; mount-failure path (0x14ec4 = ok branch)
14edc StringHandler::SetString(mp, "/" /*0x16f80*/, "updater" /*0x165a8*/)
14ee4 DirectoryHandler::Create -> mkdir <mp>/updater  (creates the flag dir on nflasha2)
14ee8 ldr  r3,[this,#4]
14eea subs r3,#3 ; cmp r3,#4 ; bhi 0x14fd6       ; only modes 3..7 reach the switch
14ef0 tbb  [pc,r3]           ; table bytes @0x14ef4 = 63 71 03 1c 35
       mode 3 -> 0x14fba | mode 4 -> 0x14fd6 | mode 5 -> 0x14efa
       mode 6 -> 0x14f2c | mode 7 -> 0x14f5e
14efa/0x14f0e ModeFlagFile(mp)+Create  then  Mode3FlagFile(mp)+Create   ; MODE 5
14f2c/0x14f48 ModeFlagFile(mp)+Create  then  Mode5FlagFile(mp)+Create   ; MODE 6
14f5e/0x14f7a ModeFlagFile(mp)+Create  then  Mode6FlagFile(mp)+Create   ; MODE 7
          + 14f9a mount("/dev/nflasha2","/setting","vfat",0xc0ed0010,"posix_attr")
            14fa4 blx [this]+0x14 (r1=0)  ; dat4/version touch, only for VERSKIP
            14fac umount("/setting")
14fba          ModeFlagFile(mp)+Create only                            ; MODE 3
14fd6 (all arms) CompleteFlagFile(mp); IsValid() -> Delete()           ; clear "comp"
14ff6 MountPoint::Umount()   ; failure -> ApiException(0x3000f, line 0x9b)
```
(mp = `/tmp_updater/updater/current`, i.e. nflasha2 mounted there; flag path =
`<mp>` + `/updater/modeN` → `updater/modeN` **inside the nflasha2 filesystem**.)

### 3.2 ANSWER TABLE

| flag files present in `nflasha2:/updater/` | meaning | `UPDATER_ACTION_MODE` | producer |
|---|---|---|---|
| `mode` | USER | **3** | `up.sh user`; UFP header modeType `'U'` |
| `mode` + `mode3` | MINOR (up.sh calls it *serv*) | **5** | `up.sh serv` |
| `mode` + `mode5` | MSCRYPT | **6** | `up.sh ms`; UFP `'M'` |
| `mode` + `mode6` | VERSKIP | **7** | `up.sh ver`; UFP header modeType `'O'` |
| — (no flag written) | SERVICE | **4** | service/loader path only |
| `mode1` (+`mode4`) | PRODUCT / keep-backup variant | **1 / 2** | `up.sh` (no arg), `up.sh keep` |
| `mode2` | (legacy SERVICE flag, only ever deleted) | – | – |
| `comp` | update completed | – | body 0x15600-ish (`CompleteUpdate`) |

Flag-file *suffix numbers* = the **old `common.src` numbering** (USER=0 → no numbered file,
SERVICE=2, MINOR=3, MSCRYPT=5, VERSKIP=6); the runtime enum is the new 1..7 numbering.
`StartUpdate()` above is the only translator present in these four objects.

### 3.3 Flag files are also produced by `crypter.elf` (pre-reboot stage)

`crypter.elf`, class `CurrentFirmware`, vtable `.rodata 0xf550`:
```
+0x08 -> 0xdc99 : if CompleteFlagFile.IsValid() -> Delete mode6 / mode3 / mode ; else Create mode
+0x0c -> 0xda80 : mount(flag 0x410) ; ModeFlagFile+Create                 -> {mode}
+0x10 -> 0xdb70 : mount ; ModeFlagFile+Create ; Mode5FlagFile+Create      -> {mode,mode5}
+0x14 -> 0xd970 : mount ; ModeFlagFile+Create ; Mode6FlagFile+Create      -> {mode,mode6}
+0x1c -> 0xd83c : mount nflasha2 + CompleteFlagFile IsValid (0xd88c)
PLT: 0xaa10 ModeFlagFile C1, 0xa938 Mode5FlagFile C1, 0xa904 Mode6FlagFile C1,
     0xa880 CompleteFlagFile C1, 0xaac0 BaseFlagFile::Create, 0xa874 BaseFlagFile::IsValid
```

### 3.4 Where the number handed to the body comes from (crypter → body)

`crypter.elf` dlopen's the body and calls its C entry point
(`BaseBodyLoaderModule.cpp`, lines 0x12c–0x166):
```
c54a/c556/c55a  DllHandler::Open("/tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so", 2)
c562            DllHandler::GetSymbol("GetBody")     -> r12/sl
c56a            DllHandler::GetSymbol("ReleaseBody") -> r8
c598            ldrb r4,[this,#0x5c]         ; bool argument
c5a0            ldr r3,[vtable,#0x58] ; blx r3     ; <-- numeric action mode (see below)
c5ac            blx sl                 ; GetBody(bool, UPDATER_ACTION_MODE, information&)
c5ae            str  r0,[this,#0x60]   ; body handle ; c5da ReleaseBody
```
The virtual at **vtable `0xecc8`/`0xf070` slot +0x58 = function `0xc00c`** is the mapping:
```
c012/c016  bl 0xc002          ; r0 = FDAT-header[+0x14]  (modeType char)
c01a       ldr r3,[this,#0x58]
c01c       cmp r3,#1 ; bne 0xc02a      ; if not "1" -> return it verbatim
c020       cmp r0,#0x4c ; ite ne ; movne r0,#1 ; moveq r0,#2   ; 'L' -> 2, else 1
```
i.e. `action_mode = this[+0x58]`, except mode-1 requests become **2 (LOADER_UPDATER)** when the
package header says `'L'` (loader), else **1 (PRODUCT)**.
`this[+0x58]`/`this[+0x5c]` are written by `BaseBodyLoaderModule::Initialize(mode,bool)`
**@0xca24**: `bl 0xd048; str r5,[this,#0x58]; strb r6,[this,#0x5c]; str vtable 0xf070,[this]`,
called from the manager ctor `0xb594` (`ldr r1,[this,#0x1c]; movs r2,#1; bl 0xb594` @0xb0fe–0xb104)
— the mode value is supplied as `[obj+0x1c]` by crypter's caller (not from argv; `main 0xabc0`
only parses `chunk=fdat|full`, `fs=fsys` and the input file name into globals 0x19834/0x19838/0x1983c).

Receiver side (`libupdaterbody.so`):
```
0xfa84 GetBody(bool,UPDATER_ACTION_MODE,information&) -> operator new 0x2c
0xf488 UpdaterBody(bool,UPDATER_ACTION_MODE,information&) ; str r5(mode) -> [this+0x20]
0xf4f4 UpdaterBody::Execute(RingBuffer*,CallbackInterface*)
0xf556   -> FlagFirmwareInformationHandler(mode)   (ctor 0x15c28: str r1,[this,#4])
same mode also passed to MountEntryHandler(0x11fc8), XmlConfigHandler(0x138c0),
                            ThreadPlugin(0x1458c)
```

## 4. Q2 — how `UPDATER_ACTION_MODE` gets into the shell environment

**Concatenated shell string + `system()`; no `setenv`/`putenv` anywhere** (checked the PLT maps:
`plt_body.json` has no setenv/putenv; body's only exec helper is `system` = PLT `0xd5bc`).

Template, `libupdaterbody.so .rodata` (exact bytes verified):
```
0x16b45 "$1"
0x16b48 "export EXTRACT_ROOT=/tmp_updater/updater/update; export PATH=/tmp_updater/updater/update/program:/tmp_updater/updater/bodyfs/bin:/usr/bin:$PATH; export UPDATER_ACTION_MODE="  (NUL at 0x16bf4)
0x16bf5 ";"      0x16bf7 " "
```
Site A — **`Updater::ShellPlugin::Execute(UPDATER_ACTION_MODE, const char*, Xml::DomElement const*)` @0x13de8**:
```
13e28 queryStringAttribute("module", &p)      ; .rodata 0x16a65 "module"
13e76 strcmp(x, "$1") -> key := cmd          ; .rodata 0x16b45 "$1"
13e8c cmp r6,#9 ; bls 0x13ebe                 ; else printf + ApiException(0x3001a, Plugin.cpp:0x56)
13ec4 strh #0 (buf); 13ec6 adds r6,#0x30 ; 13ed0 strb r6,[r2,#-4]!   ; one ASCII digit
13ed8 StringHandler::SetString(0x16b48 template, digit, ";")
13ef8 / 13f16 SetString(env, ";", key, ...)   ; 3-arg @PLT 0xddc4 / 4-arg @PLT 0xdd34
13f20 system(cmd)
13f26 errno==10 (ECHILD) ignored (Plugin.cpp) ; tst r0,#0x7f -> signalled -> 0x3000d ;
                                              ; exit code (r5>>8)&0xff, 0x8f special (0x13f80)
```
Site B — **`Updater::BuildInPlugin::execute(const char*, UPDATER_ACTION_MODE)` @0x147b4**:
same pattern (`cmp r6,#9` guard @0x147de → 0x3001a at Plugin.cpp:0x56; digit 0x14802–0x1480a;
`SetString` 0x14814/0x14832; **`system()` 0x1483c**; errno / `tst #0x7f` / `0x8f` at 0x14848–0x148a8).
Wrappers: `BuildInPlugin::EndUpdate(mode)` **0x1498c** →
`/tmp_updater/updater/bodyfs/bin/endupdate.sh` (`.rodata 0x16c60`),
`BuildInPlugin::StartUpdate(mode)` **0x149b8** →
`/tmp_updater/updater/bodyfs/bin/startupdate.sh` (0x16c8c); both stat via
`0x1612c`, then `execute(path, mode)`. `DllPlugin::Execute(mode,…)` **0x140c4**,
`Plugin::Execute(mode, DomNode*)` **0x14308**, `ThreadPlugin::Execute` **0x13d14**.
So every `<shell>`/`<run>` entry of `config.xml`, `startupdate.sh`, `endupdate.sh`,
`/setting/updater/update.sh`, `keepupdate.sh` receive the number as `$1` *and* exported.

## 5. Q3 — version comparison, `set_version` source, and the bypass

`libupdaterufp.so` — GOT names recovered from `.rel.dyn`/`.dynsym` (imported **data** symbols):
`+0xc4 verskip`, `+0xd8 set_model`, `+0xe8 set_region`, `+0xf0 firm_model`, `+0xf4 firm_version`,
`+0xfc set_version`, `+0xc0 firm_region`, `+0xd0 off_flag`, `+0xe4 ac_flag`, `+0xec acsy_flag`, …

Sources:
* **`set_version` ← `/setting/updater/dat4`**, 2-byte raw read: function **0x14fe–0x1546**
  (`open("/setting/updater/dat4")` @0x150c, `read(fd,buf,2)` @0x1518, `ldrh/strh` @0x152a–0x1530).
* `set_model` ← `/mnt/dat2`, `set_region` ← `/mnt/dat3`, after
  `mount("/dev/nflasha1","/mnt","vfat",0xc0ed0001,"posix_attr")`: function **0x2150–0x21ec**
  (mount @0x216a, open/read 4 bytes → store `set_model` @0x2190–0x2198,
  same for `set_region` @0x21d2–0x21da, umount @0x21e2, then `bl 0x14fe` for `set_version` @0x21e6).
* `firm_version/model/region` ← package FDAT header: `0x1b6c–0x1b8a` (and 0x2048–0x2062) copies
  `hdr[+0x24]→firm_version (u16)`, `hdr[+0x28]→firm_model (u32)`, `hdr[+0x2c]→firm_region (u32)`.

**Comparison — `libupdaterufp.so` 0x127a–0x1336** (called from 0x168c, 0x1968, 0x1e66):
```
12c6: firm_model != set_model    -> result 0x140
12d2: firm_region != set_region  -> result 0x141
12de: ldr r3,[GOT+0xc4]; ldr r0,[verskip]; cmp r0,#1; beq 0x1310   -> OK, version check SKIPPED
12e8: r0 = firm_version
12ee: r3 = set_version (ldrh, 2 bytes LE from dat4)
12f4: cmp r0,r3 ; ite ls ; movls r0,#0x142 ; movhi r0,#1
```
→ **the package version must be strictly greater than the stored version, else error 0x142.**
`verskip` is set to 1 only at 0x1bf4/0x1c02–0x1c0a: either from IPC reply
(`0x1bca bl 0x1338`, msg-id 0x4b0233, `[r7+0x118]==1`) or from the package header
`hdr[+0x14]=='O'`; `'U'` leaves it 0; any other char → ApiException 0x1031
(0x1bd8/0x1c12, and 0x1b8c–0x1b98 requires `'O'`/`'U'`).
Model/region checks are **never** bypassed.
Body-side helpers: `FlagFirmwareInformationHandler::setVersion(u32)` **0x159dc**,
`getVersion(u32*,u32*)` **0x15a14** (`VersionFile` class, `updater/dat4`), and the VERSKIP arm of
`StartUpdate()` (0x14f5e) is the only arm that additionally mounts nflasha2 at `/setting` and
calls virtual `[this]+0x14` (0x14fa4) — the dat4 touch.
Shell side: `up.sh modver` rewrites `dat4` with `ud_datcnv -a -m w`, `us_mkfs.sh` writes
`/setting/updater/dat4`.

## 6. Q4 — rejection of combinations

* **No code rejects a combination of flag files.** Acceptance is purely by *mode number*, and
  out-of-range numbers are silently ignored: `libupdaterbody.so 0x14e84–0x14e8e`
  (modes 1, 2, 4 → `0x1503e`, no flags at all) and `0x14eea cmp #4 / bhi 0x14fd6`
  (mode 0 / >7 → no flag creation, only `comp` cleanup).
* Mode numbers > 9 are hard-rejected: `ApiException(0x3001a)` at `Plugin.cpp:0x56`/`0x39`
  (`libupdaterbody` 0x13e8c, 0x147de) because the env template embeds **one decimal digit**.
* Flags are *cleared*, not validated:
  – `CompleteUpdate(const information&)` **0x1516c**: mount nflasha2@current (0x15370),
    virtual `[cb]+0x1c` to fetch the package's model/version (0x153c2), umount (0x153c8),
    compare with `this[+4]/this[+8]` (0x15402–0x15414) → mismatch `ApiException(0x30004, line 0x11c)`;
    match → completion block **0x154d0–0x15600**: mount, then for each of
    `mode1`(0x15526) `mode2`(0x15544) `mode3`(0x15562) `mode5`(0x15580) `mode6`(0x1559e)
    `IsValid()`→`Delete()`, then **unconditionally `CompleteFlagFile.Create()`** (0x155ce),
    then `ModeFlagFile.Delete()` (0x155da/0x155e2), then `Umount()` (0x155ea).
    (`mode4`/`Mode4FlagFile` does not exist, so nothing deletes a `mode4` file.)
  – `CompleteFlagAreaFormat()` **0x15728**: re-creates any missing flag among
    `mode1,mode2,mode3,mode5,mode` (resume path, lines …0x12x).
  – crypter `CurrentFirmware +0x08` (0xdc99): if `comp` exists → `Delete mode6/mode3/mode` first.
* Producers never leave combinations: `up.sh` does `rm -f $UPDIR/mode*` then `touch`es exactly one
  set; `us_remove_modes.sh` = `rm -f /setting/updater/mode*`.
* Per-entry rejection exists elsewhere: `XmlConfigHandler::executeGuard` **0x13450** reads
  `<guard>` (`.rodata 0x16a56`), runs it through `DllPlugin::Execute`/`ShellPlugin::Execute`
  (0x13498/0x134aa) and tests the child's exit status: `0` = accept (0x1354a),
  `0xff` = skip entry (0x1355c), anything else → `ApiException` (`XmlConfigHandler.cpp:0x59`).
  Also `BaseKeyTag::isUpdaterSkip()` **0xfe10**.
* The only throwing guards on the flag path are mount/umount failures:
  `ApiException(0x3000e|0x3000f, FlagFirmwareInformationHandler.cpp:0x66|0x9b|0x124|0x143)`.

## 7. UFP (USB) side — the flag producers for the "update from PC" flow

`libupdaterufp.so .data.rel.ro` argv tables handed to `stm_system(cmd,argv,n)` (PLT 0x100c):
```
0xaa94 { "/usr/bin/up.sh", "user", NULL }      (dup @0xaaa0)
0xaac4 { "/usr/bin/up.sh", "ver",  NULL }
0xaad4 { "/usr/bin/up.sh", "ms",   NULL }
0xaaa8 { "/usr/bin/crypter.elf", "/tmp_updater/Firm.dat", NULL }   (dup @0xaab8)
call sites: 0x18e2, 0x1dd8, 0x1fe6, 0x20a6
strings: 0x288c "/usr/bin/up.sh", 0x289b "user", 0x28a0 "ver", 0x28a4 "ms",
         0x28a7 "/usr/bin/crypter.elf", 0x27b4 "/setting/updater/dat4",
         0x2855 "/dev/nflasha1", 0x2878 "/mnt/dat2", 0x2882 "/mnt/dat3",
         0x2834 "/tmp_updater/Firm.dat", 0x284a "ufp_reboot", 0x28d9 "FDAT"
```
plus `Backup_write(0x4b…)`+`Backup_sync_subsystem` (0x2070/0x2086) and tmpfs
`mount /tmp_updater (size=5M)`.

## 8. Open points / risks
1. The *reader* that turns existing flag files into the number used at boot is **not** in these
   four objects — it is the boot/second-stage (`/init`, ramdisk / `nflasha1`), which is not part of
   `firmware.tar`. Table §3.2 is therefore derived from the body's forward translator (§3.1) plus
   the script numbering, and the two agree exactly for modes 3/5/6/7.
2. Where crypter's `[obj+0x1c]` mode value is chosen (its caller/factory) was not fully traced;
   the consumer chain (`0xca24` → `this[+0x58]/[+0x5c]` → `0xc00c` → `GetBody`) is fully resolved.
3. Body `.rodata` pcrel annotations can be ±2 (see caveat); `.rodata` byte dumps were used to fix
   every quoted string.
4. One PLT stub in body (`0xd2a4`) remains unresolved; it is not on any quoted path.
