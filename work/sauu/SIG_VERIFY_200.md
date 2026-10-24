# `libsdfileinputupdaterapi.so` / `execWriteFirm` / `VerifySignature` 在 A7C **2.00** 上的可达性

> ## ⚠ 2025-10-24 需复核：本文漏了 `sauu` 自身的 `RSA_verify` 导入（历史正文未改写）
>
> 结论 **A（"只有 MSCRYPT/mode5 一条路验签"）** 与 B 节里那句
> （"`sauu` 两版都 import RSA_verify/PEM_read/RSA_free/SHA256（stub 0xb60c/0xbb84/0xbae4/0xb940）但 **.text 里 0 个调用点**（2.00 与 2.03 都是死代码）—— 注意连 2.03 的 USER 路径也不验"）
> 以及 §A.2 末尾的"（跟 sauu 里的 SignatureVerification 一样）"，**已被推翻**：`sauu`（两版都一样）里 `RSA_verify` 有 **恰好 1 个调用点**：
> `fcn.000104e0`(`SignatureVerification::VerifySignature`) @**0x10568**，
> 由 `UFPDecryptorModule::virtual_60` @**0x10b0e** 无条件调用（再上溯 `virtual_12` @0x138a6 `ldr r3,[r3,0x3c]; blx r3`），
> 组 `verify_info{ data=缓冲基址, len=total_data_size-0x100, sig=+(total-0x100), siglen=0x100, key="/etc/VerificationKey.pem" }`，
> 失败 printf `"Signature Verification Error"` + `ApiException 0x30002`（`UFPDecryptorModule.cpp:97`）+ `__cxa_throw`。
> 也就是说 **PC/USB 的 USER(0)/SERVICE(2) 裸 `sauu` 路径在 2.00 也验签**（覆盖"整块 body 影像去掉尾 0x100"）。
>
> 为什么旧文档会漏：`work/sauu/pltmap.py` 把 section **vaddr 当文件偏移**用，对 ET_EXEC 的 `sauu`
> （vaddr = off + 0x8000）解出 **0 条 PLT 条目** ⇒ 当时看不到 `RSA_verify@plt 0xb60c` 的真实入口，
> 于是按"0 调用点"判了死代码。（对 vaddr==off 的 PIE 库无此问题，故本文 §A.2/§B 的库侧地址仍然正确。
> 复核用解析器 = `work/sauu/elfplt.py`，vaddr↔off 感知；复算 `libsdfileinputupdaterapi.so` 得 283 条，与本文 0xad2c/0xb6fc/0xb380/0xb65c/0xab7c 一致。）
>
> 详见 **`work/sauu/SIG_RECHECK_200.md`**（含六模式判定表、覆盖字节、2.00/2.03 `sauu` 差分、`/root/IAMSIGNENABLED`
> 只存在于 2.03 a1 且被 2.03 `libupdater0604.so` 的 `udtr_adjcmd_get_verifysign` 读取）。全部仍为 **E0 静态**。

离线静态（无 USB / 无相机 / 无 ssh）。全部地址 = **文件 vaddr**（这些 PIE 库 vaddr==paddr）。
工具：`work/sauu/pltmap.py`（本次新写：把 PLT 入口 `add ip,pc / add ip,ip / ldr pc,[ip,#off]!` 解码成
GOT 槽再查 `.rel.plt`，因为 r2/rabin2 把 `rsym.<name>:` 标在入口的**中间**那条指令上，
所以 r2 反汇编里的 `blx fcn.0000ab7c` 光看名字读不出是谁 —— 这就是之前 0xc69a/0xcc32 只能靠字串猜的原因）、
`work/sauu/a_scan.py`（bl/b 目标计数）、`work/sauu/elib.py`、`r2 -e bin.baddr=0 -e anal.timeout=120 -c 'aaa; …'`。
产物清单：`work/sauu/lib_sdfile.pltsym.txt`（283 条 stub→import 映射）、`lib_sdfile.text.asm`、
`lib_sdfile.plt.asm`、`lib_sdfile.fns.txt`。

## A. 谁让 `libsdfileinputupdaterapi.so` / `execWriteFirm` 跑起来 —— **只有 MSCRYPT(mode5) 一条路，而它不在 PC 通道上**

### A.1 谁引用这个名字（全仓扫，字串 + `DT_NEEDED` + dlopen）

| 集合 | `sdfileinput` / `updaterapi` / `UFPDecryptorModule` / `execWriteFirm` / `SignatureVerification` |
|---|---|
| (a) 机身 2.00 `work/l1-camera/a1_initrd` | 只有 2 个文件：`usr/bin/sdfileinput.elf`（**DT_NEEDED 里有 `libsdfileinputupdaterapi.so`**，这是全固件唯一 NEEDED 者）、`usr/lib/libsdfileinputupdaterapi.so` 自身；`usr/bin/execute_ufp.sh` 里只有可执行文件名 `sdfileinput.elf` |
| (b) 2.03 `work/v203/a1_initrd` | 同上，一模一样（**两份 `sdfileinput.elf` 逐字节相同**：`cmp -l` 0 处差异） |
| (c) 包里 a15 解包（2.00 `firmware.tar_unpacked/…/nflasha15_unpacked`、2.03 `work/v203/n15/nflasha15_203`） | **全 0 命中**（含 `libIMDB.so` 的插件表：表里有 `libupdaterufp/libupdatertalk/libupdatermedia/libupdaterufunc`，**没有** sdfileinput）；`mode5` 只出现在 `bin/up.sh` 与 `lib/libupdatercommon.so`（旗标名） |
| (c2) 更新体（`updater.img_unpacked` = `nflasha15/bin/udtrbody.bin`、`work/v203/body20{0,3}`） | **0 命中** |
| (d) 原始镜像 `strings -a` | `work/l1-camera/nflasha1.bin`：`sdfileinput.elf`(第 481 条)、`libsdfileinputupdaterapi.so`(第 553 条) —— **只有 CRAMFS inode 名**；`nflasha1_203.bin` 多一条 `IAMSIGNENABLED`(432)；`nflasha6/7`、`nflasha15`(两版)：**0 命中**。注：CRAMFS 数据块是 deflate，所以 `strings` 在 raw 上搜不到库内部字串（这不代表没有），权威是已解包的 initrd |
| dlopen | 库内确实有 `Updater::DllHandler::Open/GetSymbol`（PLT 0xaa0c/0xaa24），但它只 dlopen `"/tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so"`（字串 0x11…）；**没有任何模块 dlopen `"libsdfileinputupdaterapi.so"`**（全树该字串只在它自己的 SONAME 和 sdfileinput.elf 的 `.dynstr` 里） |

### A.2 库内部：SD 侧是活的，UFP 侧是死的

```
GetSDFileInputModeUpdater @0xc138  (导出; sdfileinput.elf 只 import 这个 + ReleaseSDFileInputUpdater@0xc15a)
  └ SDFileInputUpdaterManager::Initialize(char const*,char const*) @0xbfd8
        0xc01e: blx [PLT SDDecryptorModule::SDDecryptorModule() @0xac6c]   ← 构造 SD 解密模块
        （SDDecryptorModuleC1@0xcb40 里 0xcb48: blx [PLT UFPDecryptorModule::C2 @0xb35c] ⇒ UFP 只是 SD 的基类子对象）
  └ SDFileInputUpdaterManager::BurnFirmware @0xbb18
        0xbb3a: blx [PLT SDDecryptorModule::execWriteFirm() @0xab70]
             └ SDDecryptorModule::execWriteFirm @0xcba4 (744 B)
                   0xcbf2 blx r3 (GetWorkBuffer 之类虚调用) → sl = 数据缓冲尾指针
                   0xcc06-0xcc2a: 组 verify_info_t{ data = sl-0x100, siglen = 0x100(=256 B 尾签名),
                                                   key = "/etc/VerificationKey.pem" (rodata 0x110d7) }
                   0xcc32: blx [PLT SignatureVerification::VerifySignature() @0xab7c]   ← 无条件、无旗标 gate
                   0xcc36 cbz → 0xcc64 ; 失败: printf "\"Signature Verification Error\"" (rodata 0x11101)
                            + ApiException **0x30002** @ SDDecryptorModule.cpp:0x50(80)
VerifySignature @0xdd6c (280 B, 导出)  ← 真身，2.00 机身里就在
  0xdddc blx PEM_read_RSA_PUBKEY(stub 0xb6fc) ; 0xddf8 blx SHA256(stub 0xb380)
  0xde0c blx RSA_verify(stub 0xad2c)          ; 0xde32 blx RSA_free(stub 0xb65c)
  NEEDED: libcrypto.so.1.1（两版 a1 里 /usr/lib/libcrypto.so.1.1 都存在 ⇒ 2.00 也能载入）
UFPDecryptorModule::exec_write_firm @0xc600 (0xc69a 同样 blx VerifySignature-stub 0xab7c)
  ⇒ 它的 PLT stub 0xaac0 **全库 0 个调用点**，全固件也没有任何模块 import `UFPDecryptorModule15exec_write_firm`
  ⇒ UFP 变体在 A7C 上是死代码（跟 sauu 里的 SignatureVerification 一样）
```

### A.3 文字调用图（PC → 相机 → 会不会到 execWriteFirm/VerifySignature）

```
PC/Mac 官方 .dat ──USB──> 运行中的 a15 系统：libIMDB 插件表 dlopen "libupdaterufp.so" (udtr_ufp_init 门禁
      model/region/version + modeType 只收 'U'/'O') → crypter.elf(解密 + CrcChecker + 写 /setting/updater/mode*)
      ⇒ 头 modeType 'U' ⇒ 只写 "mode"（USER）；'O' ⇒ mode+mode6；工厂/服务用 up.sh 才写 mode1/mode2/mode3/mode5
      ↓ 重启进更新模式（boot 从 nflasha1 取 vmlinux+initrd）
a1 initrd: init → /usr/bin/UdtrMain.sh:getCurrentMode (旗标→MODE_*, a1 编号 USER=0 PROD=1 SERVICE=2
           MINOR=3 MSCRYPT=5 VERSKIP=6; 无旗标/IAMLDUDWRT → 强制 PROD)
  ├ PROD(1) → execute_prod.sh: `mf &` + `sen.elf &`
  └ 其余   → execute_ufp.sh:  MINOR→sauu -m | VERSKIP→copyCurrentFirmwareInfo + sauu -s |
                             MSCRYPT→insmod mcmn/mmc(_drv)[2.03 加 ms_drv] + **sdfileinput.elf** | 默认→sauu
                                     ↓
                     sdfileinput.elf ─NEEDED→ libsdfileinputupdaterapi.so
                                     → SDDecryptorModule::execWriteFirm@0xcba4 → 0xcc32 VerifySignature
                                     → RSA_verify@0xde0c   ✅ 2.00 也会验！
```
**但 `mode5` 旗标的唯一写点 = `/usr/bin/up.sh ms`（`func_mscrypt(): rm -f mode*; touch mode mode5`，
a15 与 a1 两份 `up.sh` 逐字节相同；a15 侧只有这条；2.00 的 PC/更新体侧 `FlagFirmwareInformationHandler`
只写 mode/mode1/mode3/mode6）⇒ 官方 PC 通道永远不会进 MSCRYPT ⇒ 2.00 上 `execWriteFirm/VerifySignature`
在 PC 通道里 **不可达**；要跑它必须有机身 shell（服务/工厂菜单）+ 卡上的更新文件。**`UFPDecryptorModule::execWriteFirm` 全链 0 命中。**

## B. 2.00 vs 2.03 `libsdfileinputupdaterapi.so` 的差异：**实测 5 个字节 / 3 处，没有一处与 crypto 有关**

`cmp -l`（1-based）：`53351,53352` / `55903` / `55999` / `74783` ⇒ 0-based 文件=vaddr：
`0xD066-0xD067`、`0xDA5E`、`0xDA9E`、`0x1243E`。两文件同为 82,788 B，节表相同（`.text 0xb718-0x10de8`、
`.rodata 0x10de8-0x11f4c`、`.ARM.extab 0x11f4c-0x12c50`）。

1. **`.text`，函数 `Updater::BufferManager::Initialize()` @0xd040，T32 指令 @0xD064（4 字节，改动落在低 2 字节 0xD066/0xD067）**
   ```
   0x0000d049 movs r0, #0x1e          ; sysconf(30)  (= _SC_PAGESIZE, 4096)
   0x0000d04d blx  [PLT sysconf @0xb2d8]
   0x0000d053 mov.w r3, #-1           ; fd = -1
   0x0000d057 movs r2, #3             ; PROT_READ|PROT_WRITE
   0x0000d059 stm.w sp, {r3, r6}      ; fd, offset=0
   0x0000d05d adds r3, #0x23          ; MAP_PRIVATE|MAP_ANONYMOUS
   0x0000d05f rsb.w r5, r0, #0        ; r5 = -4096 = 0xFFFFF000
   0x0000d063 mov r8, r0
   0x0000d065 and r5, r5, #0x20000000 (2.00)   →   #0x40000000 (2.03)   <<<< 唯一立即数语义
   0x0000d069 mov r0, r6 (0)  / 0x0000d06b mov r1, r5
   0x0000d06d blx [PLT mmap @0xaf44] ; 0x0000d075 str r5,[r4,#4] ; 0x0000d07b blx [PLT memset @0xad20]
   ```
   语义：`-pagesize & mask` 用来定匿名映射长度 ⇒ **更新缓冲（ring buffer 的 mmap 窗口）从 512 MiB(0x20000000) 扩到 1 GiB(0x40000000)**。
2. **`.text`，函数 `Updater::SDFileManager::getFirmwarePath()` @0xda58，T32 `sub.w sp, sp, #imm` @0xDA59**：
   `#0x830 → #0xc30`（0xDA5E）—— 栈帧大 1 KiB（路径/目录名缓冲扩大）；同一函数内 0xDA9E 处 0x00→0x40 是
   紧随其后的 `ldr r3,[pc,#0x38]` 字面量池位移（上一行栈帧变化把字面量池整体挪了 0x40），**不是语义变化**。
3. **`.ARM.extab` @0x1243E**：`03 → 05`，上面被改函数（BufferManager::Initialize）的 LSDA/调用站表连带变化。
⇒ **2.00 的 sdfileinput 库和 2.03 一样带完整 RSA 验签代码**，差别只是缓冲大小，跟验签无关。

## C. 2.03 的 IAMSIGN 机制（2.00 完全没有这套）

* 旗标文件：**`/root/IAMSIGNENABLED`（0 B，sha256 `e3b0c442…`）只存在于 2.03 的 a1**（`work/v203/a1_initrd_manifest.tsv:475`）；
  2.00 的 `/root` 只有 `IAMUPDATER`+`chassis`；2.00 全固件 `IAMSIGN|VERIFY_SIGN` **0 命中**。
* **唯一读点 = `/usr/lib/libupdater0604.so`（2.03 版 22,536 B；2.00 版 21,552 B 里 0 命中）**，字串：
  `udtr_adjcmd_get_verifysign`、`[UDTR0604] UD_GET_VERIFY_SIGN can not mount %s: (ret = %d)`、
  `can not mount cramfs`、`can not stat sign marker file`、`/tmp_updater/root/IAMSIGNENABLED`、`/tmp_updater/root/IAMSIGNDISABLED`
  ⇒ 它是一个 **adjcmd（PC/工厂「查询」命令）**：把 a1 的 cramfs 挂到 `/tmp_updater`，再 `stat` 两个旗标，回答"这台机的更新器验不验签"。
* **谁写：没有人写。** 旗标是 Sony 构建 a1 CRAMFS 时烧进去的（只读镜像里的 0 B 空文件），
  2.03 = `IAMSIGNENABLED` 存在 ⇒ **默认开**；2.00 = 概念不存在。`mf`/`sauu`/所有 .sh 里 `IAMSIGN` **0 命中 ⇒ 它不是运行时开关，只是能力位查询**。
* **2.03 的真验签发生在 `mf`（= PROD/`execute_prod.sh` 里那个进程）**：
  2.03 `mf` NEEDED `libcrypto.so.1.1`+`libssl.so.1.1`，导入 `RSA_verify@stub 0xb20c`、`PEM_read_RSA_PUBKEY@0xb694`、`SHA256@0xb4b0`、`RSA_free@0xb618`；
  实体 `VerifySignature ≈ fcn.0xc178`（196 B）：`fopen("/etc/VerificationKey.pem","rb")` → `PEM_read_RSA_PUBKEY@0xc1d4`
  → `SHA256@0xc1ec` → `RSA_verify(NID_sha256=0x2a0, len=0x20, …)@0xc200`，`cmp r0,#1` 不等就 printf `"signature"`
  + `ApiException 0x30002 @ SignatureVerification.cpp:0x41(65)`；pem 打不开 `0x30005(:0x2e)`、pem 读失败 `0x30002(:0x33)`。
  **唯一调用点 @0xbd1c**（在 `SenserInputUpdaterManager` 那段：组 `verify_info_t{ siglen=0x100, data=buf+r5, key="/etc/VerificationKey.pem" }`），
  失败 → `"Signature Verification Error"` + `ApiException 0x30002 @ SenserInputUpdaterManager.cpp:0xa2(162)`。
  **2.00 的 `mf`：不链 libcrypto/libssl、0 个 RSA/PEM 导入、`Signature|VerificationKey` 字串 0 命中 = 根本没有验签码。**
  `sauu` 两版都 import RSA_verify/PEM_read/RSA_free/SHA256（stub 0xb60c/0xbb84/0xbae4/0xb940）但 **.text 里 0 个调用点**（2.00 与 2.03 都是死代码）—— 注意连 2.03 的 USER 路径也不验。
* 错误码对照（`a1 /usr/bin/common.src:16-24` + `UdtrMain.sh:5`，两版 a1 与两版 body 全同）：
  `ERROR_INVALID_FIRMWARE=41  ERROR_MPR_ERASE=45  ERROR_POWER_IC_TYPE=47  ERROR_FSYS_FORMAT=48
   ERROR_UINCOMP=54  ERROR_CA_COMMAND=67  ERROR_NAND_MOUNT=72  ERROR_NAND_UNMOUNT=73  ERROR_SYSTEM=87`；
  body `bin/us_mkfs.sh:3-6`：`ERROR_FIRMWARE=0x41(65)  ERROR_PARTITION=0x61(97)  ERROR_LOGICAL_FORMAT=0x62(98)  ERROR_WBI_DROP=0x68(104)`。
  ⇒ **验签失败不走这些 shell 码**：它是 C++ `ApiException 0x30002`（一代 crypter 里 0x30002 另有通用解密含义，别混），
  进程 non-zero 退出 → 脚本 `|| { echo "[Error] : error sdfileinput"; exit 1; }` → 机身侧只剩 LED/`us_error.sh` 表现。

## D. 结论表（A7C **2.00**）+ L0' 判定

| 路径（a1 编号） | 2.00 实际进程 | 撞 RSA 验签？ | 依据 |
|---|---|---|---|
| USER（裸 `mode`，**官方 PC .dat 的 modeType 'U'**） | `execute_ufp.sh` → `sauu` | **不会** | `sauu` 不 NEEDED `libsdfileinputupdaterapi.so`（自带静态 `SignatureVerification` 副本），`.text` 对 `RSA_verify@plt 0xb60c`/`PEM_read@plt 0xbb84`/`RSA_free@plt 0xbae4`/`SHA256@plt 0xb940` **各 0 个调用点**（2.00 与 2.03 皆如此） |
| PROD(mode1 / `/root/IAMLDUDWRT`) | `execute_prod.sh` → `mf &` + `sen.elf &` | **不会**（2.03 才会） | 2.00 `mf` 不链 libcrypto/libssl、无 RSA/PEM 导入、无 Signature 字串；2.03 `mf` 有活验签（`0xbd1c→0xc178`，`0x30002`） |
| MINOR(mode3 → `sauu -m`) | `sauu -m` | **不会** | 同一个 `sauu`，验签代码死 |
| VERSKIP(mode6 → `sauu -s`) | `sauu -s` | **不会** | 同上 |
| SERVICE(mode2 → `sauu`) | `sauu` | **不会** | 同上 |
| MSCRYPT(mode5) | `sdfileinput.elf` | **会**（但 PC 通道进不来） | `sdfileinput.elf` 唯一 NEEDED → `SDDecryptorModule::execWriteFirm@0xcba4` 在 **0xcc32 无条件** `blx VerifySignature(stub 0xab7c)` → `RSA_verify@0xde0c`，key `/etc/VerificationKey.pem`、siglen 0x100；失败 `ApiException 0x30002`；`mode5` 只由 `up.sh ms` 写（需要机身 shell） |
| （`UFPDecryptorModule::exec_write_firm@0xc600`） | — | **不会**（死代码） | 其 stub 0xaac0 全库 0 callers，全固件 0 个 import |

**L0' 探针（官方 2.03 包，FDAT 尾 272 B 翻 1 bit + 重算 `DEND` CRC32）在 2.00 上会不会被拦：不会被 RSA 拦。**
官方 PC 通道 = `modeType 'U'` → USER → `sauu`（2.00 与 2.03 都不验尾），2.03 新增的验签只挂在 **PROD/`mf`（工厂 "SenserInput" 路径）** 上，
而 2.00 的 `mf` 连 libcrypto 都不链 ⇒ 只要 CRC 重算对，尾签名翻 bit 在 2.00 上无人校验。
**DEND CRC32 确实被相机校验（必须重算）**：4 份 `crypter.elf`（a15-2.00 / a1-2.00 / a1-2.03 / a15-2.03）都有
`CrcChecker.cpp` 例程 @0xb408（CRC32 poly `0xEDB88320`，按 0x1000 分块）→ @0xb466-0xb480 `memset(12)+Seek+Read(12)`
→ `memcmp(buf+8,"DEND",4)` → @0xb4a2-0xb4b2 把 `buf+0xc..0xf` 拼成 u32 与 calc 比较 → 不等则
`printf "UdrAPI,%d,%s:%d,\"calc_crc:0x%lx, getHd_crc:0x%lx\"\n"`（`CrcChecker.cpp:0x59`=89）并返回 0。

还缺 / 仍要盯的环：
1. **PC 端**：已验（`notes/updater_flow.md:558`）Mac `SystemSoftwareUpdater.app` 与 52,992 B 的 `Contents/Resources/SystemSoftwareUpdaterTool` 里 `rsa|signatur|verif|pem|dend|UDTRFIRM|FDAT` **0 命中** ⇒ PC 不验、只搬运（本轮 `/Volumes` 只有 `Macintosh HD`，2.03 DMG 未挂载，沿用已验结论；若要再确认可 `hdiutil attach -readonly ~/Downloads/Update_ILCE7CV203.dmg`）。
2. **帧内 u16 校验和**（`crypter.elf@0xe0ec`）与 **FDAT 头 CRC**（`crc32(明文[12:512])`）：翻尾 256 B 不碰它们，但若顺手动过版本号/IV 就要一并重算。
3. 门禁三件套 + modeType：model→`0x140`、region→`0x141`、版本必须严格大于→`0x142`（`libupdaterufp.so@0x127a-0x1336`）、modeType 只收 `'U'/'O'`。
4. 没跑过真机：结论是「代码上不可达」，不是「实测通过」；且 **2.00 机身的 a1 是自家 dump（`work/l1-camera/a1_initrd`），2.03 包里的 a1 是跨机型共享镜像**（同 sha256），两者不能互换理解。
5. 若有人（工厂/服务菜单）走 SD/MS 卡 MSCRYPT，则 **2.00 也会撞 `0x30002`** —— 这条是唯一"2.00 已带活验签"的路径，别把探针和它混在同一次实验里。
