# 复核：A7C **2.00** 机身 `sauu` 自身的 RSA 验签（重新定性 2.00 更新器的验签）

日期 2025-10-24（离线纯静态；不碰相机 / 不碰远端 / 不碰 `work/qemu-a7c/**`）。
**全部结论 = E0（静态）**：没有任何实机刷写证据。

分析对象与地址口径
* 2.00 机身 a1：`work/l1-camera/a1_initrd/usr/bin/sauu`（84,428 B，sha256 `5e345c86…`）
* 2.03 包 a1 ：`work/v203/a1_initrd/usr/bin/sauu`（84,428 B，sha256 `d79af0e6…`）
* `sauu` 是 **ET_EXEC，ARM32（e_flags 0x5000002），vaddr = file_off + 0x8000**（ELF paddr==vaddr，
  LOAD0 off0/vaddr 0x8000 filesz 0x13ea4；LOAD1 off 0x14000/vaddr 0x24000）。
  `.text 0xbb90-0x15710`、`.rodata 0x15718-0x195e4`、`.plt 0xb450-0xbb90`（**ARM 长 PLT**，
  与 `libsdfileinputupdaterapi.so` 同形式）。
  ⚠ 旧文档 `work/sauu/pltmap.py` 只能处理 vaddr==file-off 的 PIE 库：对 ET_EXEC 的 `sauu` 它把 vaddr 当文件偏移用，
  解出 **0 条** PLT 条目（差点据此误判 `sauu` 没有 import）。它还有 `if not (w3>>21)&1: off = -off` 的取负分支，
  对 `sauu` 的 `ldr pc,[ip,#imm12]!`（实测 0xe5bcfd30 这类，bit21 布局不同）会取错号。
  本次的解析器 = `work/sauu/elfplt.py`（vaddr↔off 感知，PLT imm12 按不旋转的 12 位正偏移解），
  对 `libsdfileinputupdaterapi.so` 复算结果与旧文档一致（`RSA_verify`=0xad2c、`PEM_read_RSA_PUBKEY`=0xb6fc、
  `SHA256`=0xb380、`RSA_free`=0xb65c、`VerifySignature`=0xab7c）⇒ 旧文档的库侧映射可信；
  `sauu` 侧解出 151 条 stub。
  用 r2 `-e bin.baddr=0x8000` 得到的地址与上表 vaddr 一致，可直接混用。

---

## 1. `RSA_verify` 在 `sauu` 里 **确实有调用点**（旧文档漏了）

`sauu`（2.00 与 2.03 完全一样）只有 **1 个** `RSA_verify` 调用点：

| import | PLT stub | 调用点 | 所在函数 |
|---|---|---|---|
| `RSA_verify` | 0xb60c | **0x10568** | `fcn.000104e0` = `Updater::SignatureVerification::VerifySignature`（`SignatureVerification.cpp`，RTTI `N7Updater21SignatureVerificationE` @0x17f94） |
| `PEM_read_RSA_PUBKEY` | 0xbb84 | 0x1053c | 同上 |
| `SHA256` | 0xb940 | 0x10554 | 同上 |
| `RSA_free` | 0xbae4 | 0x1058a | 同上 |
| `SHA1_Init/Update/Final` | 0xb814/0xbb54/0xb584 | 0x103de / 0x103e8 / 0x103f2 | `fcn.00010368` = "verifyKey"（密钥文件 SHA1 ↔ 安全服务比对） |

（`work/sauu/elfplt.py` 的 per-function BL 扫描在 exidx 上失准 ⇒ 用 r2 `axt` 复核，两法对 RSA/SHA 系列都只给出上面这些点；
PLT stub 本身也没有被 `adr/ldr` 取址、没有重定位项指向它、不在任何函数指针表里 ⇒ **不是死代码**。）

调用链（vaddr，2.00 机身 a1 的 `sauu`）：

```
main @0xe078  (UpdaterModeMain.cpp；挂载 /dev/nflasha2→/setting、dlopen libUsbBusPower.so、
               构造 ModeFlagFile/Mode3/Mode5/Mode6/CompleteFlagFile 等旗标对象 @0xe184-0xe1ac)
  → UpdaterManager / 命令处理（ChkGuardCommand.virtual_36、WriteFirmCommand.virtual_36 @0xf070、
    QueryVersionCommand.virtual_36；vtable+0x3c 派发到 0xefe0 / 0xf0a0 / 0x12080 / 0x138a6）
  → method.Updater::UFPDecryptorModule.virtual_12 = fcn.0001383a
        0x138a6: ldr r3,[r3,0x3c] ; 0x138a8: blx r3          ← 无条件
  → th 0x10d00: b.w 0x10a88  =  method.Updater::UFPDecryptorModule.virtual_60  (vtable slot @0x18104)
        0x10a9e printf "…… Waiting for Firmware Copy Completion ……" (UFPDecryptorModule.cpp:0x4e)
        0x10aa8 ldr r3,[r3,0x50]; blx r3                     (数据模块 virtual_80)
        0x10ab4 printf "…… Firmware Copy Completed ……"       (:0x50)
        0x10ac8/0x10ad2 取缓冲基址与 total_data_size → 0x10ae0 printf "total_data_size = %d" (:0x56)
        0x10ae4 fcn.00010358 (init verify_info)
        0x10aec-0x10b0c 组 verify_info（见 §3）
        0x10b0e: bl fcn.000104e0   ← ★ 验签点，**无旗标 gate**
  → fcn.000104e0 (VerifySignature)
        0x104f4 bl fcn.00010368      "verifyKey"（见 §4）
        0x1050a fopen(keyfile,"rb")  失败 → printf "file open" + ApiException **0x30005** (line 0x2e)
        0x1053c PEM_read_RSA_PUBKEY  NULL → printf "pem" + ApiException **0x30002** (line 0x33)
        0x10554 SHA256(data, len, md@sp+8)
        0x10568 RSA_verify(type=0x2a0(=672=NID_sha1), md, md_len=0x20, siglen=[r7,0x48], sig, rsa)
        0x1056c cmp r0,1 / 0x1056e beq → 只有返回 1 才算过；否则 printf "signature" + ApiException **0x30002** (line 0x41)
        0x10588 RSA_free; fclose; return 0(=成功)
```

`sauu` 的 ctor 无条件把对象 vtable 设成 **UFPDecryptorModule**（`fcn.00010948` @0x10952：
`ldr r3,[0x180c8]=vtable UFPDecryptorModule; str r3,[r4]`）⇒ **`sauu`（= USER(0)/SERVICE(2) 裸跑那条路）本身就带 UFP 验签模块**。

⚠ 与旧文档 `SIG_VERIFY_200.md` 的关系：旧文档只处理了 `libsdfileinputupdaterapi.so`（MSCRYPT/mode5 侧）
并断言"只有 mode5 一条路验签"。它没扫 `sauu` 自己的 `RSA_verify` 导入（名字集合不同：`sauu` 里没有
`sdfileinput`/`execWriteFirm`/`SignatureVerification::VerifySignature` 这些**导出名**，只有 `.so` 里 C++ mangled 名）。
两边结论要合并：**PC/USB（UFP）通道在 2.00 也验签，验签体在 `sauu` 里，而不是（只）在 mode5 的 sd 库里。**

---

## 2. 2.00 vs 2.03 `sauu` 差分要点（详见 `sauu_200_vs_203.diff.md`）

* 同大小 84,428 B、同节表、**同 PLT 映射（151 条 stub→import 逐条相同）**、**dynsym 名字集合完全相同（无新增/删除导入）**。
* 5,924 字节不同；按节：`.text 4583`、`.dynstr 610`（同一批名字换顺序）、`.rodata 256`、
  `.ARM.exidx 285`、`.ARM.extab 150`、`.dynsym 39`、`.dynamic 1`。
* **验签相关代码逐字节相同**（2.00/2.03 都：`fcn.00010368` 0x10368-0x104b0 相同、
  `fcn.000104e0` 0x104e0-0x105a4 相同、`UFPDecryptorModule.virtual_60` 0x10a88-0x10c40 相同、
  ctor 0x10948-0x10990 相同、`0xbb90-0xc000` 相同）。调用点地址在两版里一模一样
  （0x10568 / 0x1053c / 0x10554 / 0x1058a / 0x103de / 0x103e8 / 0x103f2 / 0x10b0e / 0x138a6）。
  ⇒ **2.03 没有新增验签、也没有给验签加旗标 gate**（就 `sauu` 而言）。
* 差异集中在 `0xe64e … 0x14ca1`（569 个小块；此后函数整体平移 +0x120），最大语义变化是
  `BufferManager.virtual_8`（mmap 尺寸掩码）：
  `0xe64c: and r5,r5,0x20000000` (2.00) → `and r5,r5,0x40000000` (2.03)，
  与旧文档在 `libsdfileinputupdaterapi.so` 里发现的 `sysconf(_SC_PAGESIZE)`/mmap 类改动同一族 ⇒ 缓冲区/映射尺寸调整 + 重编译抖动。
* `IAMSIGNENABLED` **不在 `sauu` 里**（两版 `sauu` 都 0 命中；`sauu` 的 rodata 里也没有）。它只出现在
  `work/v203/nflasha1_203.bin`（CRAMFS inode）、`work/v203/n15/a1_boot/boot/initrd.img`、
  `work/v203/full_dec.bin`、`firmware_203.tar`，以及代码文件 **`work/v203/a1_initrd/usr/lib/libupdater0604.so`**（2.03）。
  2.00 机身的 `libupdater0604.so` **完全没有** `IAMSIGN*` 字符串（两版该库仅差少量字节，2.03 版多出整段函数）。
  * 2.03 `a1_initrd_manifest.tsv` 里有一条 **`/root/IAMSIGNENABLED  size=0  sha256=e3b0c442…`**（空旗标文件，真实存在于 2.03 的 a1 initrd 根目录）；
    2.00 机身 a1 manifest 只有 `/root/IAMUPDATER`，**没有** `/root/IAMSIGNENABLED`。
  * 2.03 里引用它的代码：`sym.udtr_adjcmd_get_verifysign`（`libupdater0604.so`，xref 0x2d54/0x2d60），
    字串 `/tmp_updater/root/IAMSIGNENABLED` / `/tmp_updater/root/IAMSIGNDISABLED`
    + `"[UDTR0604] UD_GET_VERIFY_SIGN can not mount %s"` / `"… can not mount cramfs"` / `"… can not stat sign marker file"`
    ⇒ 这是一个 **服务/工厂 adjcmd 查询命令**：把 body 侧 cramfs（`/mnt/boot/initrd.img`）挂到 `/tmp_updater`，
    再 `stat` 里面的 `IAMSIGNENABLED` / `IAMSIGNDISABLED` 标志文件，回一个"这台机器的 body 是否开启签名检查"的读数。
    谁调用 `UD_GET_VERIFY_SIGN`（PC 工具？工厂菜单？）在离线数据里查不到 ⇒ 该点 E0 强度只到"存在该命令"。

---

## 3. 验签覆盖哪些字节

`UFPDecryptorModule::virtual_60` @0x10ae4-0x10b0c 组装（`r8 = total_data_size`，`r2 = [r7,0x44] = 缓冲基址`）：

```
verify_info @sp+0x40:  [0x00] = 数据基址            (str r2,[r7])
                       [0x04] = total_data_size-0x100   (str r3,[r7,4])   ← 被哈希的长度
                       [0x08] = 基址 + (total_data_size-0x100)  (str r3,[r7,8]) ← 签名起点
                       [0x0c] = 0x100                    (str r3,[r7,0xc]) ← 签名长度 = 256 B
入参： r1,r2,r3 = ldm.w r7,{r1,r2,r3}（基址/长度/签名指针），[sp]=0x100，[sp,4]="/etc/VerificationKey.pem"
```

即：**签名 = 传输/落盘缓冲的最后 0x100 字节（RSA-2048），被哈希（SHA-256）的范围 = `[基址, 长度-0x100)`，也就是整块 body 影像（含 fdat 头、所有 nflashaX 数据、CRC/DEND/尾区），再减去尾部签名本身**。
0x10b48 处另有一次 `memcpy(obj+0x4a8, 基址+total-0x110, 0x10)` —— 把签名块**之前**的 16 字节（`total-0x110`）另存并在 0x10b62-0x10b78 用 `"%02x"` 逐字节打印（一个 16 字节的尾随 ID/摘要），它同样落在被签名覆盖的范围内。

改哪里会让 `RSA_verify` 失败（E0 推断，前提是 `sauu` 那条路真的执行到 0x10b0e）：
* 改 **payload 本体的任何一字节**（nflasha5 体、nflasha6/7、header 里任意字段、DEND/CRC 字段、尾 16 字节 ID）→ 都在 `[0, total-0x100)` 内 ⇒ SHA256 变 ⇒ `RSA_verify` 返回 ≠1 ⇒ **失败**。
* 改 **尾 0x100 签名本身** → 不改变被哈希范围，但 RSA 数学校验失败 ⇒ **失败**。
* 只改 header 里的 CRC（`tools/fdat_tail.py` 那套 CRC/DEND）→ 不会让 `RSA_verify` 失败（它不看 CRC），但会先/后撞 CRC 检查（不同检查点，见 `notes/updater_verify.md`）。
* 只有把 body 影像重新切一刀、使 `total_data_size` 变化、同时补上合法的 256 B 尾签，才可能同时满足两者。

`/etc/VerificationKey.pem`（451 B，RSA-2048 PUBLIC KEY）本身也被校验：
`fcn.00010368` 打开 PEM → `lseek(END)` → `mmap` 整个文件 → `SHA1_Init/Update/Final` 全文 →
经 `osal_valloc_msg_wait/osal_snd_sync_msg`（MWF IPC，消息对象 0x25906be）把 20 字节 SHA1 送进一个**内部安全服务**，
回收 20 字节（memcpy @0x1043a）后 `strncmp(...,0x14)`（0x10474）比对；不等 → printf `"signature"` + ApiException **0x30002**（`SignatureVerification.cpp:0x75`）。
⇒ 换 PEM（例如换成自己的公钥）**也会被这条 SHA1↔服务 检查挡住**；这条链在更新器 initrd 里能否真的收到服务应答，E0 无法判定。

---

## 4. 致命性 / 旗标 / 参数（-m / -s）

* 调用点 `0x10b0e` **之前没有任何旗标或 mode 判断**（0x10a88-0x10b0e 一路是 printf + 取缓冲 + 组结构）。
  `0x138a6` 处 `blx r3`（调 virtual_60）也是无条件的。
* 返回值检查：`0x10b12 mov r5,r0; 0x10b14 cbz r0,0x10b3a` ⇒ **0 = 成功**；非 0 ⇒
  `printf "UdrAPI,%d,%s:%d,"Signature Verification Error"\n"`（rodata 0x182e2）→
  `__cxa_allocate_exception(12)` → `ApiException(**0x30002**)`（`UFPDecryptorModule.cpp:0x61`=97）→ `__cxa_throw`（0x10b36）。
  即 **抛异常**，不是"只记录"。异常最终由 `ChkGuardCommand/WriteFirmCommand.virtual_36` 一带的 catch 处理
  （sauu 里有多处 `__cxa_begin_catch`，其中 0xf0a4 的调用点后有 `cbz r0` 检查返回值；
  `main` 里唯一 `exit` 在 0xf03c，是 `Backup_read` 失败路径 `exit(-1)`）。
  ⇒ 静态上"验签失败会中止该 write-firm 命令"，但**中止到哪种用户可见状态（是否 `ERROR_NAND_MOUNT=72`、是否回 USB 错误码）E0 未定**。
* 内部错误码（同一 verify 例程内）：`0x30005` 打开文件失败（PEM 缺失/不可读），`0x30014` lseek 失败，
  `0x30025` IPC 失败，`0x30002` pem 解析失败 / SHA1 比对失败 / RSA 校验失败。
* 旗标：`sauu` 自身 rodata 有 `/ramdsk/dev/mode`、`/setting/updater/mode`、`/setting/updater/mode1`、`/ramdsk/mode5`、
  `/root/IAMUPDATER`、`/root/IAMLDUDWRT` 与 `ModeFlagFile/Mode3FlagFile/Mode5FlagFile/Mode6FlagFile/CompleteFlagFile`
  类（main @0xe184-0xe1ac 构造、0xe1d0-0xe26a `fcn.0000c138` 反复查询）——这些决定**选哪个 mode state / 哪个模块**；
  但**没有 `IAMSIGNENABLED`**（2.00/2.03 `sauu` 都没有），也就是 `sauu` 内部**没有**"签名开关"可读。
* 参数 `-m`（MINOR）/ `-s`（VERSKIP）：`main` 里对 `argc` 只有一处 `cmp r5,1`（0xe152）后构造若干对象，
  没有 `strcmp("-m")` 之类的字符串比较（`sauu` 里根本没有 `-m`/`-s` 字串）⇒ 参数处理在
  `fcn.0000dc70` / `fcn.0000c03c` 一类的构造/选择函数里（未逐条读完，**不确定**）。
  可确定的是：**验签只在 `UFPDecryptorModule`（UFP 传输）路径上**；`sauu -m` / `sauu -s` 是否走同一模块 = 未证。

---

## 5. 六种模式判定表（E0 静态；`execute_ufp.sh`/`execute_prod.sh` 的分支已确证）

| MODE | 更新器实际执行 | 验签：有/无 | 无条件 or 旗标控制 | 失败是否中止 |
|---|---|---|---|---|
| USER(0) | 裸 `sauu`（UFPDecryptorModule） | **有**（0x10568，唯一调用点） | **无条件**（`sauu` 内无旗标 gate；`IAMSIGN*` 不在 `sauu`） | 静态看是：`ApiException 0x30002` 抛出 → write-firm 命令失败（用户可见码未定） |
| PROD(1) | `mf &` + `sen.elf &`（不进 `sauu`） | `sauu` 不跑；`mf`/`sen.elf` 侧未见 RSA/SHA 导入（本次未逐一扫，弱） | — | 未证 |
| SERVICE(2) | 裸 `sauu` | **有**，同 USER(0) | 无条件 | 同上 |
| MINOR(3) | `LD_PRELOAD=libSysDef.so sauu -m` | `sauu` 带验签代码；`-m` 是否走 UFP write-firm 路径 **未证** | 未见旗标 gate（就 `sauu` 可见部分） | 未证 |
| MSCRYPT(5) | `insmod mcmn/mmc(_drv)[2.03 +ms_drv]` + `sdfileinput.elf` → `libsdfileinputupdaterapi.so` | **有**（旧文档已证：`SDDecryptorModule::execWriteFirm@0xcba4` → `VerifySignature@0xdd6c` → `RSA_verify@0xde0c`） | 旧文档：该调用无条件；运行时进 mode5 需要 `up.sh ms`（机身 shell） | 旧文档：`ApiException 0x30002` |
| VERSKIP(6) | `copyCurrentFirmwareInfo` + `sauu -s` | 同 MINOR：**未证** | 未见旗标 gate | 未证 |
| （新增）2.03 body 侧 | 2.03 a1 里存在空旗标 **`/root/IAMSIGNENABLED`**，2.00 a1 没有 | — | `libupdater0604.so` 的 `udtr_adjcmd_get_verifysign` 会 mount body cramfs 并 stat `/tmp_updater/root/IAMSIGNENABLED` / `IAMSIGNDISABLED` | 该命令的**调用者未知**（PC 工具/工厂菜单）；不能据此断言运行时开关 |

**关键修正**：2.00 的官方 PC/USB 通道（USER=0 ⇒ 裸 `sauu`）**不是"不验签"**，而是"`sauu` 自己验，
条件是整块 body 影像尾部 256 B RSA 签名对得上"。2.03 相对 2.00 的差别不在 `sauu` 的验签（逐字节相同），
而在 **2.03 的 a1 里多了一个 `/root/IAMSIGNENABLED` 空旗标 + `libupdater0604.so` 多出 `get_verifysign` 查询函数**。

---

## 6. 实践结论：没有 Sony 私钥能不能刷改过的 payload？

**E0 判定：按静态结构 —— 不能（就 USER/SERVICE 的 `sauu` 路径而言）。**
被哈希的是"整块 body 传输缓冲去掉尾 0x100"，签名必须是 Sony 私钥对这整段签出来的 256 B；
改 1 字节 payload 就得改签名，改签名又没有私钥 ⇒ 死循环。另外 PEM 本身还有一条 SHA1↔内部服务 的绑定检查。

可执行绕法（按风险从低到高）：

1. **改 a1（我们已有完整 2.00 dump，nflasha1）让验签短路** —— 最推荐。
   最小 patch：`sauu` @0x10b14（vaddr）`cbz r0,0x10b3a`（2 字节 T32 `20b1`）之前的调用点
   `0x10b0e: bl fcn.000104e0` 换成 `nop`(0xbf00)+`movs r0,0`（或直接 `0x10b12` 处强制 r0=0），
   即在 **调用点** 而非被调函数里短路，长度中性（32bit `bl` → `nop`+2 条 16bit，需就地摆放）。
   * 更省事的等价做法：改 `RSA_verify` 判定点 `0x1056c-0x1056e`（`cmp r0,1` → 让分支总走成功块）。
   * 可逆性 **R1**：a1 是 CRAMFS 只读镜像，我们有 2.00 机身 `work/l1-camera/nflasha1.bin` 与解包 initrd；
     只要保留原始 `nflasha1.bin` 并整分区回写即可完全还原（前提：刷 a1 的通道本身可用）。
   * 风险：改 a1 后 **boot 链自己可能校验 a1**（a1 是否被签名/度量，本次未查）；若 boot/XLOADER 校验 a1，
     改错的 a1 会变砖风险 = 未知（这次必须靠别的子系统的结论）。⇒ 先做"改名/删 PEM"这种更小动作。
2. **删/改名 `/etc/VerificationKey.pem`（在 a1 initrd 里）** —— 让验签在 `fopen` 处失败。
   但注意：失败路径是 **抛 ApiException 0x30005**，不是跳过 ⇒ 单靠删 PEM **不能**让刷写继续；
   它反而保证"必定失败"。⇒ 只有配合 1) 的短路 patch 才有意义（把"验签不可用"变"验签被跳过"）。可逆性 R1，风险低于 1)。
3. **换 PEM 为自签公钥 + 用自己私钥重签 payload**：需要同时过 `fcn.00010368` 的
   SHA1(PEM)↔内部安全服务 比对（0x10474）；静态看这条必失败（服务里存的期望摘要不是我们的）⇒ **不可行**，除非那个服务的期望值也来自 a1（未证）。
4. **绕开 `sauu` 路径**：走 PROD(1)（`execute_prod.sh`：`mf` + `sen.elf`）或 MINOR/VERSKIP（`sauu -m` / `sauu -s`）
   —— 若这些路径确实不经过 `UFPDecryptorModule::virtual_60`，就没有本次讨论的验签（但会有别的门：CRC/DEND/版本）。**未证**，属"低成本先试"类。
5. **机身 shell + mode5（MSCRYPT）**：`up.sh ms` 造 mode5 旗标 + 卡上更新文件，走 `sdfileinput.elf`
   那条路（旧文档已证它同样 `RSA_verify`）—— 需要机身 shell，风险中等，收益是拿到另一条写入通道。
6. 只改 CRC/header 字段、不动 payload 体：若 `sauu` 的验签真的在跑，**改任何字段都失败**；
   若跑的是 PROD/MINOR 路径，则只受 CRC/DEND 约束（`notes/updater_verify.md`）。

最推荐顺序：**4)（先试不需要改 a1 的模式）→ 2)（删/改名 PEM，R1）→ 1)（`sauu` 原地 patch，R1）**；
任何改 a1 的动作都要留 `nflasha1.bin` 原件 + 事先确认 a1 是否被上级签名/boot 校验（本次未查，见 §7）。

---

## 7. 证据等级与仍不确定之处

* **E0（静态，强）**：`sauu` 里 `RSA_verify` 恰好 1 个调用点 0x10568；`VerifySignature`/`verifyKey`/`virtual_60`
  的指令级流程、错误码（0x30002/0x30005/0x30014/0x30025）、`verify_info` 的字段与 0x100/0x110 偏移、
  两版 `sauu` 验签区逐字节相同、PLT 映射相同、无新增导入、`IAMSIGNENABLED` 不在 `sauu` 而在 2.03 的
  `libupdater0604.so` + 2.03 a1 manifest 的空旗标文件。
* **E0（弱，仅靠字符串/符号）**：2.03 的 `UD_GET_VERIFY_SIGN` 语义（谁调用、返回什么、是否影响刷写门）；
  PROD(1) 下 `mf`/`sen.elf` 是否另有验签。
* **未定（需要实机或 QEMU 证据）**：
  1. `sauu -m` / `sauu -s` 是否真的走 UFP write-firm ⇒ 是否验签（三种 `sauu` 模式差异未证完）；
  2. 验签失败后用户可见结果（错误码 / 是否重启 / 是否已经写了一部分 nflashaX）——异常抛出后的 catch→状态机细节未跟完；
  3. 被哈希缓冲到底是"传输原样流"还是"解扰（`Dec_Scramble`）后的流"（`sauu` 导入了 `Dec_Scramble/Dec_ScrambleInit`，构造点 0x10982）；
  4. `fcn.00010368` 依赖的 MWF IPC 安全服务在更新器 initrd 环境里是否存在/应答；
  5. a1（nflasha1）自身是否被 boot/XLOADER 签名校验 ⇒ 改 a1 的 R1 可逆性是否成立；
  6. `UD_GET_VERIFY_SIGN` 的调用者。
* 本次没碰 `work/qemu-a7c/**`（另一子代理占用），也没做任何实机验证。
