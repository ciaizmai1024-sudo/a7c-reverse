# A7C（ILCE-7C，v2.00）改固件 + 写回相机的可行方法

配套阅读：`UPDATER_ANALYSIS.md`（更新器内部机制：config.xml → 脚本 → ELF → 分区）、
`notes/zve10-qemu.md`（同 SoC 的 ZV-E10 逆向/QEMU/反砖工作全记录）。
本文所有数值都是**我在本机对 `FirmwareData_ILCE7CV200.dat` 实测**得到的；标注方式：
**【实测】= 有可复现命令与数值**，**【他证】= 来自 refs/ 里别人的实机或反汇编结论**，**【未验】= 待做**。

参考仓库（已 clone 到 `refs/`）：
`QAQLeonard/a7c2-fl23-research`（A7C **II** 已商用的改功能工具）、`cokeenet/zve10-qemu`（同 CXD90045 的 QEMU/救援）、
`Lost-week-1025/CXD90045-FPSU`（DAT/FDAT 格式与三层校验）、`ma1co/Sony-PMCA-RE` + `ma1co/fwtool.py`（容器格式、**公开密钥表**、updatershell）。

---

## 0. 结论先说：四条写回路线，建议按 D→B→C→A 的顺序推进

| 路线 | 做什么 | 需要的前提 | 破坏性 | 当前判断 |
|---|---|---|---|---|
| **A 改包重刷**（自制 .dat 走官方更新通道） | 换 `firmware.tar` 里的分区镜像（nflasha3/5/7/15） | 需要 **FDAT 尾 256B 签名**的解法（见 §1.4） | 中（走官方流程，会重建分区/格式化） | **默认不可行**：CXD90045 世代 FDAT 带 RSA-2048 签名【他证】；A7C 上验签在哪还没定位【未验】 |
| **B 服务通道写 `libJit.so` → worker 里 `dd`/整盘写回** | 主路：**`SET_FILE2(0x4010)` 直写 `/tmp/jiritsu/libJit.so`**（同芯片实测：只有 `write(16)` 会触发 dlopen）；`set_firm(0x4006)` 刷 tar 降为备选（同芯片实测 0x4006/0x4003 会卡死服务） | 服务模式 + 写一个 ARM32/Thumb `libJit.so`（**干活放在 `.init` ctor**，dlopen 即执行；ScriptI 四入口作为次要） | 中：nflasha6 不是启动分区；dlopen 崩 → `im.elf` 死但**相机会自己重启（30–40 s）**；`jinit` 会熔断不再加载（需手动刷回原厂 libJit.so） | **首选**：加载器已逐指令确认（§3.1.1）；同芯片 ZV-E10 已把这条路完整跑通并开源工具（`notes/camtool.md`）；**一代本体也已打通**：ILCE-7C **2.03** 上 Senser 认证 + `054c:0336` 服务会话 + Jiritsu `dlopen("/tmp/jiritsu/libJit.so")` **root 已实测可用**（`QAQLeonard/a7c2-fl23-research` issue #23，hnws，2026-10-22；载荷必须 **ARM32 EABI**）【他证】。一代是 **32 位 ARM/Thumb**，二代 AArch64 worker 不能直接用 |
| **C 服务模式 + 官方包** | 只改"版本/机型/区域"门禁，刷**原厂**包（降级、重复刷、跨区） | 需要 shell（同 B 的前半）跑 `up.sh`，或直接服务模式 | 低（不改内容） | **已在他机型实机验证**（`dat4=00 00` 兜底）【他证】，A7C 侧 `dat4` 格式待验【未验】 |
| **D BootROM 串行启动** | 反砖：SRAM 里跑裸机 payload，直接操作 eMMC 扇区 | 硬件桥（USB-C D+/D− + 470Ω + RP2040） | 低（只改一个扇区） | **最后兜底**；A7C 上已有人发出过 5,149 B payload【他证】，ZV-E10 上数据阶段读还没通 |

> 一句话：**先别想着"重打包 .dat"**（缺签名），把力气放在 **B（服务通道刷 nflasha6 → 自家 `libJit.so` → 写分区）** 和 **D（反砖兜底）**，
> 用 **C（版本杠杆）** 保证"原厂包永远能刷回去"。

---

## 1. 包格式：已经能完全解开，且密钥是公开的【实测】

### 1.1 外层容器（UFU）
```
89 55 46 55 0D 0A 1A 0A                     ; magic "\x89UFU\r\n\x1a\n"
[u32be size][4B ASCII type][data] ×N         ; DATV(4) @0x10, PROV(4) @0x1c, UDID(172) @0x28, FDAT @0xdc
[u32be 4]["DEND"][u32be CRC32]               ; 覆盖 [0, filesize-12)
```
- A7C 实测：file=346,206,712 B；FDAT data @0xdc；`DEND` CRC 存 `0xaaaa81b8`，
  `zlib.crc32(file[0:-12]) = 0xaaaa81b8` **相符** → 这层只是完整性校验，可重算。
- `UDID` 记录（172 B）= 允许的 USB 描述符（VID/PID）白名单，和 `config.yaml` 里 `normalUsbDescriptors` 一致。
  **本轮把它解开了**（`tools/ufu_scan.py`）：头 `u32be 条数=21`，后面 21 条 ×8 B = `<flag u32le><PID u16be><0x054C u16be>`：
  ```
  flag=1: 054c:0448 047d 05fe 05ff 0501 0502 05a7 05a8 05ee 05ef 05c9 05ca 0513 0514 050d 050e 0511 0512 0528 0529
  flag=2: 054c:05e2
  ```
  ⇒ **A7C 自己的两个 PID（0E8A 存储 / 0336 服务模式）都不在这张表里**，而表里是 `05xx` 系（多半是更早机型/
  更新模式下的描述符）⇒ 这张表不能拿来反推“A7C 刷机会枚举成哪个 PID”，只能当旁证【已验：字节解码；含义未定】。
- 本轮另两点已工具化：`tools/ufu_scan.py`（列 chunk + 自动校 `DEND` 的 crc32 + 解 UDID），`tools/fdat_layout.py`
  （解主头字段/对象表 + 校头 CRC + **把包里已有的 `updater.img`/`firmware.tar` 与解密区全量逐字节比对**，实测两个都✓）。

### 1.2 FDAT：帧流 + 两段加密（用公开密钥全部解出）
```
FDAT data = N 个 1024B 加密块  +  272 B 尾部
  明文块 = [u16le 校验和][u16le (长度 | bit15=末块)][负载 ≤1020][0xFF 填充]
  校验和 = Σ 块内偏移 2..1023 的 511 个 u16le，& 0xFFFF
加密分段（= ma1co fwtool `AesCbcCrypter`，CXD90045）：
  块0 前 512B：AES-128-ECB，key_aes（平台公开 key）
  块0 后 512B 及其余全部块：AES-256-CBC，key_cxd90045，IV = FDAT 尾部前 16 字节（= 文件末尾 -0x110）
```
**实测结果**（`python3 tools/fdat_aescbc.py <dat> /tmp/fdat_dec.bin`）：
```
FDAT 数据 346206480 B = 338092 块 + 272 B 尾部   IV=13efb6a39e3f0cf8345933679c7ed222
块头校验: 通过 338092 / 失败 0            ← 密钥正确性的强证明
明文流 344853504 B；开头: b'UDTRFIRM\xd7<\xf8\xcd0100'
```

密钥来源（两处独立印证）：
- `key_aes = E3B0C442 98FC1C14 9AFBF4C8 996FB924` = **SHA-256("") 前 16 字节**；
  它就是相机 `libupdatertalk.so` 里 `KeyArray`(32B) 的前 16 字节（`.data` 0x830），
  **编译期硬编码**：全库无任何重定位/写指令触碰 0x8830–0x884f【实测】。
- `key_cxd90045` 出自 ma1co `fwtool/sony/constants.py`（公开）；`devices.yml` 里 `ILCE-7C: arch CXD90045 / model 0x91030019`，与我们解出的头字段完全一致【实测】。

### 1.3 FDAT 明文内部（改动就落在这里）【实测】
```
偏移      内容
0x000     UDTRFIRM 头（512 B 区，只有这一段用 key_aes/ECB）
          +0 magic 'UDTRFIRM' | +8 checksum(u32le) | +12 '0100'
          +16 modeType 'U'（fwtool 常量：U=user / O=verskip / M=minor / P=prod）
          +20 luwFlag 'N'
          +32 versionMinor=0, versionMajor=2      → 2.00
          +36 model=0x91030019   +40 region=0
          +48 firmwareOffset=143872  +52 firmwareSize=344709632  +56 numFileSystems=2
          +64 fs[0]: 'U' offset=512 size=143360   ; fs[1]: 'P' offset=512 size=0
0x200     更新器 bodyfs（CRAMFS 143,360 B）＝我们的 updater.img，逐字节相同
0x23200   firmware.tar（344,709,632 B）＝我们的 firmware.tar
```
- 头校验规则【实测】：`checksum = zlib.crc32(明文[12:512])`（存 LE，**存于明文头 +8 处**，即 payload[8:12]；+12 是 ASCII `'0100'`）。注意范围是 **到 512**，不是到 400。
- 帧头本身（`[cs][len]` 4 字节）**也在密文里**【实测】：对密文流前 512B 做 ECB 解密后，头 4 字节才是 `0x0596 0x03fc`，且 `0x0596` 等于解密后重算的校验和 —— 这同时是密钥/分段正确的自证。
- 512 + 143,360 + 344,709,632 = 344,853,504 = 明文总长，**严丝合缝**：我们的两个工件就是包里的原文。
- 相机侧同样只解这 512 B 头：`libupdaterufp.so` 调 `Dec_Scramble` 解 `packet+0x28` 起 512 B（32×16B ECB）与文件头 0x204 B【实测反汇编】；`crypter.elf` 的 ECB 循环也是 16 B/步、无 IV。

### 1.4 还剩一个真正的安全边界：尾部 272 B【他证 + 实测尺寸】
272 B = **16 B IV + 256 B**。256 B 恰好是 RSA-2048 的签名长度；ZV-E10（同 SoC）那边给出四条证据：
`fwtool` 的 `AesCbcCrypter.encrypt()` 明确 `raise Exception('Encryption not supported')`、
272B 结构、公开 `VerificationKey.pem`、相机侧 `checkGuard` 报 **Invalid version**，
结论是"该 SoC 的 FDAT 有 RSA-2048 签名，**自制 updater body 结构性不可行**"。
旁证：ma1co 的 `updatershell`（往 FDAT 里塞自定义 `libupdaterbody.so`，见 `refs/Sony-PMCA-RE/updatershell/pack.py`）
只覆盖到 `CXD4105/CXD4115/CXD4120/CXD4132/CXD90014`，**没有 CXD90045** —— 正是这一代加了签名。
A7C 上验签具体发生在哪（`nflasha1` 里的 `mf`/UdtrMain.sh？还是 `crypter.elf`？我们没有 A7C 的 nflasha1）→ **【未验，关键缺口】。**

★ **一代包内复核（`notes/updater_verify.md`，指令级）——上面那段对一代不成立，要降维**：
- A7C II 的两个证据锚点（`sauu`、`libupdaterapi.so`）**在一代包里根本不存在**；A7C II 的 `exec_write_firm@0x12f50`+`RSA_verify`+`0x30002` 结论**不能直接搬到一代**。
- 一代手里所有更新器工件（`libupdaterufp.so`@nflasha15/lib、`libupdatertalk`、`crypter.elf`@nflasha15/bin、`libupdaterbody.so`、`libupdatercommon.so`）的 `.dynsym`/strings 里 **没有任何 RSA/EVP/DigestVerify/公钥**，而且这些模块 **DT_NEEDED 不链 libcrypto** → `crypter.elf` 结构上不可能验签【已验】。全树 `VerifySignature` 只命中蓝牙 `BTM_BleVerifySignature`；`key_cxd90045` 0 命中。
- **`crypter.elf` 从不读那 272 B**：`0x110` 出现 0 次，帧循环靠帧头 bit15 结束 → 尾部不解析。它只校三样（全部可重算）：DEND CRC32 覆盖 `[0, size−12)`（`0xae60`）、每帧 `2..1023` 的 u16 校验和（`0xe0ec`）、头 CRC32 覆盖 `hdr[12,512)` 存于 `hdr+8`（`0xbf1c`）；另外 chassis 字符串比较（`/bodyfs/config/chassis` vs `/root/chassis`，`0xbde4`，失败 `0x30007`）。
- CBC（`key_cxd90045` + IV）在文件系统里看不到实现，最可能由 **硬件 DMA 解密器**消费（initrd 里的 `kmod/ldec.ko`：`boss_hw_ldec_set/process`）【推断】→ 尾部 256 B 可能是**硬件认证/密钥包装**而不是 RSA 签名。`0x30002` 在一代是 `ApiException` 通用码家族（`0x30000…0x30025`）里的一个，抛出点在 `DecryptorModule.cpp:81`（长度不 16 字节对齐），**不是 RSA 失败**。
⇒ **修正后的结论**：①一代的“签名边界”仍未找到，但它不在我们已有的软件里；②“改包能不能刷”这件事的**正确探针不是改身份字段**（见下：门禁先报错，测不到签名），而是 **只翻 CBC 区 1 个字节（尾部 272 B 原样）看报哪种错**：报 `calc_crc/getHd_crc` 类 ⇒ 检查在 crypter.elf 手里（可软件绕过）；报其它硬失败 ⇒ 前面还有一道（nflasha1 的 updater 或 `ldec` 硬件）。
⇒ **可行的绕过目标已经在可写分区里**：`/usr/bin/crypter.elf`（nflasha15）里的 DEND CRC `0xae60`、头 CRC `0xbf1c`、chassis `0xbde4` 都能就地 patch（先有路线 B 的代码执行，不动 .dat、不碰 nflasha1）【推断，已定位】。

★**本轮新增：更轻的靶子 = `/usr/lib/libupdaterufp.so`**（同在 nflasha15，只有 12 KB，`.text` 5.8 KB）：
它是 `libIMDB.so` 按名字 dlopen 的插件（表里就是 `("libupdaterufp.so","udtr_ufp_init","udtr_ufp_exit")`），
并且**全部身份门禁就写在这几 KB 里**（model/region/version 比较 `0x127c`、modeType 只允 'U'/'O' `0x1b8c`、verskip `0x1c00`）。
⇒ 一次“整分区 dump→本地改→整分区写回”就能把门禁彻底拆掉（同代 `appFw.so` 战术），写坏只会 `im.elf` 起不来，
而 a15 本来就在“更新器可重建”名单里【已验：分区归属+dlopen 方式；效果未验】。详见 `notes/updater_flow.md` §9。

推论：
- 改 `firmware.tar` 内容 → 必须重算 DEND CRC + 帧校验 + 头 CRC32（都简单，已给规则），
  但 **256 B 签名重不出来** → 路线 A 在拿到 Sony 私钥或 patch 掉验签之前不成立。
#### 1.5 ★最小改包实验（已离线做完，产物已生成）
> ★**2025-10-24 更正（E1）**：这类"只改 512 B 头区"的改包**并不能绕过签名**。实测（`tools/sig_probe_fdat.py`，官方 `.dat` × 相机 a1 自带公钥）：签名 = `FDAT` 记录 payload 尾 256 B，消息 = `FDAT payload[0:size−0x100]`（**整块密文体，含那 512 B 头**）；未改 payload **Verified OK★**（2.00/2.03 同一把 key），密文体中段**翻 1 位即 FAIL**。
> ⇒ 改包路线（路线 A）在相机侧**过不了验签**，除非换掉验签器（**Route A′**：改 a1 里 `sauu` 的调用/判定）。签名**外面**只有容器 magic 与 `DATV/PROV/UDID` 记录（可改 + 重算外层 CRC；`UDID` 是 PC 侧用的 USB VID:PID 白名单）。详见 `notes/updater_verify.md` 末节"★★签名门最终判定"。

工具 `tools/fdat_hdr_edit.py`（只动 ECB 那 512B 里的身份字段，不碰 CBC 区）：
```
# 往返证明（原文件）
文件 346206712 B；FDAT data @220 size 346206480；帧数 338092
帧0 checksum: 存 0x0596 算 0x0596 OK
头 checksum: 存 0xcdf83cd7 算 crc32(payload[12:512])=0xcdf83cd7 OK
身份字段: modeType=U luw=N ver=2.00 model=0x91030019 region=0
往返 512B(ECB): 一致；往返 512B(CBC 首段): 一致

# 挨刀试验：modeType U -> O（fwtool 常量里 'O' = updateModeVerskip）
帧0 checksum: 0x0596 -> 0x6be5 ；DEND CRC: 0xaaaa81b8 -> 0x280e32f4
产物 /tmp/ILCE7CV200.modeO.dat（346,206,712 B，与原包同尺寸）
自检：对新包再跑 --prove → modeType=O、帧0/头 checksum 全 OK；DEND CRC 自洽；
     cmp 全文件只 differing 36 字节：密文区 0xdc..0xfb（32B，帧0 ECB 雪崩） + DEND CRC 4B；
     FDAT 尾 272B 与原包 SHA-256 完全相同（签名原样保留）。
```
第二个实验包（只改区域，**上机代价最小**）：`/tmp/ILCE7CV200.region1.dat`（`--set-region 1`，帧0 checksum `0x0596→0x6384`，DEND CRC `0xab023d47`）。
差异同样是 36 字节，且**位置正好对上字段布局**：`0xdc..0xeb`（帧0 第一个 AES 块 = 帧头 + 头 CRC 存位 payload[8:12]）与 `0xfc..0x10b`
（第二个 AES 块，包含 region 字段 payload[40:44] → 密文偏移 0x108）+ 末尾 4B DEND CRC → 这是字段偏移的又一重独立自证。
预期行为：更新在门禁处安全中止（机型/区域不匹配 0x141）→ 能报 0x141 就说明**签名不覆盖（或不校验）身份字段**；报其它更新器级错误则说明覆盖到了。
而 `modeType='O'` 那个包会走 VERSKIP 分支（`edisx.elf` 重写分区表 + `uc_mkfs -m full` 全盘重建），只适合在确定要降级时用。

三个包（均 346,206,712 B，sha256 前 12 位）：`34aeaf5ecad2` `/tmp/ILCE7CV200.dat`（源副本）、`46fc176d6139` `…modeO.dat`、`2f58ebea6f14` `…region1.dat`；尾部 272B（签名）三个包完全相同。
⇒ **身份字段（modeType/model/region/version）+ 三处 CRC 全可离线改写并自洽**；唯一变量就是那 256B 验签。
若上机后官方更新器报错误，则说明签名覆盖到身份字段（错误本身就是信息）；若顺利进 verskip，则降级/刷同版这条路不需任何相机侧补丁。

---

## 2. 相机侧门禁：机型/区域/版本比较在哪【实测反汇编】

`libupdaterufp.so`（usr 分区，被 `libIMDB.so` 以名字 dlopen：字符串表里就有 `libupdaterufp.so` + `udtr_ufp_init/exit`）：

```
udtr_ufp_init(0x20e8)
  ├─ Dec_ScrambleInit @0xf94  ← 装 AES key（KeyArray 前 16B）
  ├─ mount("/dev/nflasha1", "/mnt", "vfat", MS_MGC_VAL, "posix_attr")   @0x2198 附近
  ├─ 读 /mnt/dat2 → set_model, /mnt/dat3 → set_region, /setting/updater/dat4 → set_version
  └─ 注册 osal 消息回调（ExtCmdSvc，USB 报文）
fcn.0000127c  ← 门禁
  firm_model(0xad8c) != set_model(0xad68)            → 返回 0x140
  firm_region(0xad64) != set_region(0xad88)          → 返回 0x141
  verskip(0xad4c)==1 → 跳过版本比较
  firm_version(0xad90) <= set_version(0xad94)        → 返回 0x142
```
`firm_*` 来自包内头（§1.3），`set_*` 来自机身 nflasha1 的 `dat2/dat3` 与 `/setting/updater/dat4`。
`verskip` 也能由报文 `+0x3c == 'O'/'U'` 置位【实测】；头 `modeType` 也有 `'O'`=verskip 的常量【fwtool】→ 值得在 A7C 上试【未验】。

★ **门禁的执行位置与后果（`notes/updater_verify.md`）【已验】**：这段代码在 **`/usr/lib/libupdaterufp.so`（可写分区）里、运行在正常模式的 `im.elf` 进程内**（被 `libIMDB.so` 按名字 dlopen）；`modeType` 只允许 `'U'`/`'O'`。失败时**直接应答退出，不写任何东西**；通过后才 `mount tmpfs` 写 `/tmp_updater/Firm.dat`（`0x26dc-0x2706`）→ `stm_system("/usr/bin/crypter.elf", "/tmp_updater/Firm.dat")`（argv 表 `0xaaac`/`0xaab8`）→ `up.sh user|ver|ms`（`0xaa94`/`0xaac4`/`0xaad0`）。
⇒ **`model/region` 永远要过（`verskip` 只跳过版本比较）**：所以只改 model/region 的测试包**测不到签名**（它在验签之前就 0x140/0x141 停了）；
⇒ **同版本重刷会撞 `0x142`**（`firm_version <= set_version`）。本轮新发现：跳版本并不只有 `'O'`/VERSKIP 一条，
`/usr/bin/up.sh modver <4位>` 可以直接把机身“当前版本”（`/setting/updater/dat4`，由 `ud_datcnv.elf -e` 编码）改小
【已验脚本内容，效果未验】——这比 verskip 的 `edisx + -m full` 温顺得多。见 `notes/updater_flow.md` §3。

### 2.1 A7C 原生 `us_mkfs.sh` 给出的权威模式表【实测】
```sh
PRODUCT=1  LOADER_UPDATER=2  USER=3  SERVICE=4  MINOR=5  MSCRYPT=6  VERSKIP=7   # UPDATER_ACTION_MODE
SERVICE|USER|MINOR|MSCRYPT → 不跑 edisx.elf（不重分区表）; fmode="app"; 提前 exit 0（不跑 dosfsck/smode）
PRODUCT|LOADER_UPDATER     → 跑 edisx.elf + uc_mkfs.elf -m full（除非 /tmp_updater/not_write_file/nwl 存在 → app）
VERSKIP                    → 跑 edisx.elf + uc_mkfs.elf -m full，然后提前 exit 0
两者都会：ud_keep_backup.elf -s（还原 Backup.bin）→ ud_wbi_drop.elf partinf.conf（重建 WBI）
```
→ **普通用户更新（USER=3）不重写分区表、只做 app 级格式化**；降级/VERSKIP 反而更重（会 edisx + full）。
另外 A7C 的更新器 body 只有 **35 个 bin 文件**，但脚本/config.xml 里引用了 `updater_log.sh`、`updater_storage_backup.sh`、
`updater_storage_restore.sh`、`uc_pclear`、`us_darwin_firm.sh`、`ud_frfup2.elf`、`ud_datcnv.elf` 等 **本 body 里没有的名字**
→ 它们很可能由 **nflasha1 ramdisk 的 bin/**（`body_common.sh` 把 `$EXTRACT_ROOT/bin` 加进 PATH）提供，**必须先 dump nflasha1 才确认**。



---

## 3. 可操作的写回手段

### 3.1 代码执行（路线 B 的入口）【他证 + A7C 侧组件已确认】
A7C 一代 `/usr/lib/libJiritsu.so` 里有【实测】：
```
IM_JIRITSU::CImJiritsu（jiritsu_init/exit/sus/res/act/inact/jit_thread）
导出 cmd_high_capacity_get_file
字符串: /tmp/jiritsu  /tmp/jiritsu/ver.txt  /tmp/jiritsu/tmmc.jit  /tmp/jiritsu/DIAC.csv
        /tmp/jiritsu/libJit.so   /bin/sh   /bin/tar xpf %s ./ -C %s   /dev/nflasha6
DT_NEEDED: libSTMcmdexecute.so（我们的包里缺，需从相机 dump）【未验】
```
A7C II 已商用的工具（`refs/a7c2-fl23-research/src/camera_runtime/transport.py`）给出了同一通道的用法【他证】：
```python
def jiritsu(self, cmd, data=b'', missing=False): ...      # USB 端点上的命令通道
# 15=select(path) 16=write 17=read 18=remove，path 必须 startswith('/tmp/jiritsu/')，≤510 字符
def read(self, path, missing=False): self.select(path); return self.jiritsu(17, b'\0\xff\0')
...
session.read('/tmp/jiritsu/../../etc/ld.so.preload')      # ← 用 .. 越界读写任意路径
```
服务模式 USB 身份（A7C II 实机）：常规 `054C:0E8A`（海量存储）↔ 服务 `054C:0336`；
进入服务身份要认证（用机身序列号的 legacy hex-text digest）并绑定属性 `00e70003`（序列号）；
相机卡在 `0336` 时要取电池 ≥1 分钟【他证 README/changelog】。协议细节（帧格式/握手/写限制）见 `notes/a7c2-tools.md`：
Senser 12B 头 `{size,pFunc,sequence,version,miconType,offsetType,response}`、1MB 分块、文件通道 = `pFunc 0x40` + `CommandHeader(0x1001, cmd)`，
写只限 `/tmp/jiritsu/*`（单文件 ≤64KB），读靠 `..` 逃逸读任意路径，状态码 `0x10000006`=文件不存在。

**A7C 一代的 Jiritsu 能力清单（本机直接证明【实测】）**：`libJiritsu.so` 的 `.dynsym` 里有定义（shndx=10=.text）的处理函数：
```
jiritsu_init 0x3be5  exit 0x3ce9  sus 0x3d39  res 0x3d7d  inact 0x3e19  act 0x3e1f  thread 0x3e25
adj_cmd_get_version 0x5029   adj_cmd_set_file_path 0x52a9   get_jiritsu_area_filename 0x53f9
adj_cmd_get_file 0x5469   adj_cmd_set_file 0x56c1   cmd_file_delete 0x58f9   adj_cmd_set_file2 0x5b01
cmd_file_delete2 0x5f19   adj_cmd_get_file2 0x5fe9   adj_cmd_compare_media 0x625d
adj_cmd_get_file_list 0x641d   ★adj_cmd_set_firm 0x67ed   cmd_high_capacity_send_file 0x6b21
adj_cmd_get_file_hash 0x6c55   cmd_high_capacity_get_file 0x6f15
```
`JIRITSU_*` 日志名按序列在 .rodata 0xa0d1：`MODE, MOUNT, FORMAT, START, DEBUG, FIRMUP, SET_FILE, GET_FILE, FILE_DELETE, GET_FILELIST, GET_FILE_HASH, COMPARE_MEDIA, GET_VERSION, FACTORY, SET_FILE_PATH, SET_FILE2, GET_FILE2, FILE_DELETE2, TEST_UI_VIEW`。
→ **一代不仅有一代二同样的文件通道（SET_FILE2/GET_FILE2/DELETE2/GET_FILELIST/GET_FILE_HASH），还多了 `FIRMUP`（`adj_cmd_set_firm`）与 `MOUNT/FORMAT/FACTORY`**（§3.1.1 已逐指令确认）。
#### 3.1.1 ★ `adj_cmd_set_firm` = 官方自带的"刷 Jiritsu 分区"通道【实测逐指令】
⚠ **同芯片（ZV-E10）实测：`FIRMUP(0x4006)` 与 `FORMAT(0x4003)` 会卡死服务模式，“不要发”**（`Sony-ZVE-10-Camtool/README.md:358`）【同芯片实测】→ 本节作为“已逆向清楚但默认不用”的备选通道；部署 worker 走 §3.1.4。

★**载荷 tar 的两条硬要求（用相机自带的 busybox 1.29.3 在 arm32 容器里实测，方法见 `notes/toolchain.md`）**：
  ① 归档**必须含一个 `./` 目录项**——相机解包命令固定是 `tar xpf <载荷> ./ -C /tmp/jiritsu`，没有 `./` 成员时 busybox 会把文件**解出来但返回 rc=1**（`tar: .: not found in archive`），`set_firm` 有可能把它当解包失败（`0x10000010`）⇒ 已修 `tools/jiritsu_pack.py`（现在相机自家 busybox 解我们载荷 **rc=0**，文件与 mode 都对）。
  ② busybox 会**剔掉成员名里的 `../`**（`removing leading './../../' from member names`）⇒ **tar 成员无法越出解包目录**，“靠成员名 `../..` 越界写”的猜想不成立【实测】。
`libJiritsu.so`（全量反汇编 `work/text.asm`，笔记 `notes/jiritsu.md`）：
```asm
0x681a '/tmp/jbusy' -> sys_file_chk_exist      ; 存在则 'jiritsu running' 直接退出
0x6834 r5='/tmp/jiritsu'  0x6836 r0='/dev/nflasha6'  0x683a blx sys_mount
       ; <-- /tmp/jiritsu 就是 nflasha6（16MB vfat）的挂载点
0x6844 失败 -> 'Jiritsu partition mount error.'
0x6870 '/tmp/jiritsu.bak.tar' -> sys_tar_compress   ; 先备份现有内容
0x68a6 '/tmp/jiritsu.bak.hash'
0x692e r0='/tmp/jiritsu/ramdsk' r1='size=5M' -> ramdisk_mount
0x6942 movw r1,#0x241 (O_WRONLY|O_CREAT|O_TRUNC)  movw r2,#0x1ed (0755)
0x694a '/tmp/jiritsu/ramdsk/jiritsu.dat' -> open   ; PC 发来的载荷
0x69d2 blx sys_tar_extract                        ; 'Tar file extract error.'
```
libJit 加载器（代码执行入口）：
```asm
0x7680 '/tmp/jiritsu/ramdsk_libJit/libJit.so'  ; 'libJit.so copy error.'  先复制到 ramdisk
0x769c blx dlopen ; 0x76c8/0x7706 blx dlsym 'CreateScriptI' 'LoadScriptI' 'RunScriptI' 'DestroyScriptI'
0x75b2 '/tmp/jiritsu/jinit' -> 'libJit.so crashed.' -> 0x75ec 'Recovery mode execute.'
```
要点：
- 服务通道能把 tar 载荷刷进 **nflasha6**（开机不挂载的 Jiritsu 工作区，`mount.conf` 里 `none vfat 16777216`），且**自带备份 tar/hash 与崩溃保护（jinit + Recovery）** → 比裸 `dd` 安全得多（但备份寿命有限，见下）。
- 往 nflasha6 放自家 `libJit.so`（一代还会读 `tmmc.jit` / `DIAC.csv` / `ver.txt`）→ Jiritsu `dlopen` → **im.elf 进程内 ARM32 代码执行**，之后再去 `dd /dev/nflasha*`。
- worker 必须是 **ARM32/Thumb**，导出 `CreateScriptI/LoadScriptI/RunScriptI/DestroyScriptI`；二代那套 AArch64 worker 不适用。
- `/tmp/jiritsu ≡ nflasha6`：文件通道写的东西**落在 flash 上**（不是 tmpfs），配额 ~5 MiB；备份 tar 写到 `/tmp`(=nflasha10, 12 MB)，刷前先看剩余空间。
- 分发/报文（子代理反汇编【他证】，我未逐行复核）：`jiritsu_init` 注册 osal 回调 → 一级 TBB `ldrh [msg+0x1a]` 取命令号(1..19)；小头 `msg+0x1c`、数据 `msg+0x1f`、长度 `msg[0x14]`、状态码 `msg+0x10`；路径 ≤512、只拦换行/逗号、**无 `..` 检查**（逃逸成立）。

#### 3.1.2 命令号寻址（两处独立源互证）+ worker ABI
wire 帧 = PMCA AdjustControl：`PFUNC=0x40` + `{u16 block=0x1001; u16 code}` + payload【他证：ZV-E10 在 `libsencore.so` 命令名表 `{u16 f1; u16 osal_id; u16 block; u16 code; char name[]}` 里找到，并用 `adjstctl.elf` 的 `{0x01d7,0x0003,0x0404,0x00fe,"RAM_READ"}` 校验了字段顺序】：
```
0x4001 MODE   0x4002 MOUNT✅实测成功   0x4003 FORMAT⚠勿碰   0x4004 START
0x4005 DEBUG(=二代 root 代码执行入口)  0x4006 FIRMUP      0x4007 SET_FILE  0x4008 GET_FILE
0x4009 FILE_DELETE  0x400a GET_FILELIST  0x400b GET_FILE_HASH  0x400c COMPARE_MEDIA
0x400d GET_VERSION  0x400e FACTORY  0x400f SET_FILE_PATH✅实测成功（含 /tmp/jiritsu/../.. 穿越）
0x4010 SET_FILE2    0x4011 GET_FILE2    0x4012 FILE_DELETE2    0x0013 TEST_UI_VIEW
```
代码低字节 = 一级 TBB 下标（就是我看到的 `JIRITSU_*` 名字表顺序）→ **与 A7C II 工具用的 15/16/17/18 完全一致**。
`libJit.so` 必须导出（dlsym 名 + 调用点）：
```
CreateScriptI(void) -> obj*                    @0x76ec   0 = 'create fail'
LoadScriptI(obj, "/tmp/jiritsu/tmmc.jit")      @0x77ba   非 0 = 成功
RunScriptI(obj, paramStruct*, char* name)      @0x7a60   调用前 open('/tmp/jbusy',O_CREAT|0755)，调用后 unlink
DestroyScriptI(obj)                            @0x7462
```
`dlopen` 的 flag 是指令级确定的：**`0x769a movs r1,#1` → `RTLD_LAZY`**（不是 RTLD_NOW）；目标文件是 ramdisk 副本
`/tmp/jiritsu/ramdsk_libJit/libJit.so`（`0x7680`），先 `sys_file_copy`（`0x7684`，失败报 `'libJit.so copy error.'`），再 `dlopen` + `dlerror`（`0x76a2`）。
⇒ 未定义符号不会在 `dlopen` 时硬失败（只有真调用到时才报）→ 我们依赖进程 glibc 提供 `system/fopen/memset` 是安全的。
★ **对象布局约束【实测反汇编，重要】**：加载器虽然把 `CreateScriptI` 的返回值当不透明指针存在 `this+0x14`，
但会**直接解引用 `obj+0x1c` 当 `char*`**：
```
0x77c0  ldr r3,[r4,#0x14] ; 0x77c2 ldr r6,[r3,#0x1c] ; 0x77c6 bl strlen   ← LoadScriptI 返回 0 的失败路径，无 NULL 保护
0x77e8  ldr r2,[r3,#0x1c] … 0x77e4 bl fopen                              ← fopen(obj+0x1c, "a") 写日志
0x791c  ldr r3,[r4,#0x14] ; 0x791e ldr r6,[r3,#0x1c] ; cbnz …; 为 0 则用 'unknown'
```
⇒ worker 的 `CreateScriptI` **不能返回 `0x19700101` 这种假指针**（失败路径上 `strlen` 会在相机进程里 SIGSEGV），
必须给一个真的、≥ 0x20 字节的对象，且 `+0x1c`（= `slots[7]`）放一个合法字符串（我们的 worker 现在放 `/tmp/jiritsu/worker.log`）。
Sony 原版 `libJit.so` 的对象在此处应当就是它的日志路径（`/tmp/jiritsu/jit.log`）——这一点待 dump 原库后比对验证【未验】。
另：`RunScriptI` 的第二个参数是相机内部填的结构（观测到 +0x18 处有 magic `0x20170213`、+0x28 处是 `'/tmp/jiritsu/jit.log'`），我们的 worker 不解析它【已验：传 NULL 不崩】。
注：`/tmp/jbusy` 是"脚本正在跑"标记（所以 `set_firm` 见到它就退出）。
**崩溃/回滚机制【逐指令确认，之前的描述不准、已修正】**：
- `chk_exist` 在本库里是 **0 = 存在/成功**（`LoadScriptI` 则是非 0 = 成功，约定不统一）。
- `0x75b2 sys_file_chk_exist('/tmp/jiritsu/jinit')`：**存在**（r0=0）→ 记 `'libJit.so crashed.'` → 直接退出，**不加载 worker**（不是自动回滚）。
- `0x75ce/0x75dc`：只有 **`bak.tar` 与 `bak.hash` 同时存在** 才打 `'Recovery mode execute.'` 并 `sys_tar_extract('/tmp/jiritsu.bak.tar' → '/tmp/jiritsu')`（0x7604），随后删除两者；只有 `bak.tar` 没有 `bak.hash` → 直接删掉（不一致状态清理）。
- 而 `set_firm` 的**成功路径末尾**（`0x6a2e ldr r3,[r7]`，该局部就是 `0x6862 ands r3, sb, #2` 即 `mode&2`）会 `remove(bak.tar)`+`remove(bak.hash)`（0x6a36/0x6a40）；各种错误分支（`0x10000010` 解包错、`0x10000005` ramdisk、`0x10000009`）跳过删除 → 备份保留。
⇒ **备份素材只意味着“上一次 set_firm 没走到终点”**：中途失败 → 下次开机自愈；**刷成功之后没有可回滚的备份**（刷了行为错误的 worker 不会自动恢复）；而 worker 里 `dd` 写坏分区完全不在备份范围内。
已做的工具（均已自检）：`tools/jiritsu_pack.py`（打包 tar 载荷 + 校 e_machine==40/4 个导出/条目必须 `./` 开头/≤5MiB）、
`tools/jit_worker/libJit.c`+`Makefile`+`selftest.c`（worker 源码 + 自测）。
**链接已实测可行**：本机 Apple ld 不认 GNU 选项（只能编），用 OrbStack/Docker 的 `--platform linux/arm/v7 alpine:3.19` 容器链→
产物是 `ELF 32-bit LSB shared object, ARM, EABI5`，`--check-so` 返回 0，未定义符号只有 `fopen/fclose/fputs/fgetc/fwrite/snprintf/strcmp/system`（皆 glibc 可见）。
命令：`make docker`（链）与 `make test`（在 arm32 容器里 dlopen 并按 jit_thread 的调用顺序跑一遇 Create/Load/Run/Destroy，验证 `cmd.txt` 真的被执行）。
载荷格式：相机 `/bin/tar` 是 busybox applet → 用 ustar、条目均 `./` 开头；解包是**覆盖**而非清空；
副作用：写 `jiritsu.hash`（载荷 MD5）、删 `jcount`、若有 `DIAC.csv` 会调 `sens_list_update()`。
载荷里**不要放**：`DIAC.csv`（会被 `sens_list_update()` 重写，放错内容直接弄坏校准表）、`jiritsu.hash`（set_firm 自己写）；
`ver.txt`（只被 `cmd_get_version` 读，缺文件只记日志）、`jcount`（缺文件时 glob 无匹配返回 0）**不必须也不有害**。
首个实测载荷（已打包）：`work/payload/{libJit.so, tmmc.jit(0B), WORKER.VER}` → 明文 6,047 B（配额 5 MiB 的 0.1%），tar 10,240 B，条目均 `./` 开头（纯 ustar、无额外帧），MD5 `a5d193a9…`。

#### 3.1.3 ★刷之前就能拿到的原厂能力（实现已定位，详见 `notes/senser_shell.md`、`notes/injection.md`）
- **一代没有 Jiritsu 调试执行**：`cmd_debug @0x4da8`（42 字节）里没有 `system/popen/execve`，唯一引用点 `0x711e`（PLT stub `0x35c8`）→ 命令 5（0x4005）**不给代码执行**（二代才有）【已验（指令级）】。
  **但它不是“无害空桩”**：`0x4dc2` 调 `sys_set_timeofday @0x4694`（旧笔记写的 0x3a34 是错的），串 `0x9503 = /bin/date -s %02d%02d%02d%02d%04d.%02d`，参数全是立即数 ⇒ **发 0x4005 会把时钟设成 2017-07-04 21:42:26**（副作用，会污染 EXIF/日志时间）【已验】。
- **`/bin/sh -c` 通道存在，但一代注不进去（此路已死）**【已验（指令级），`notes/injection.md`】：`CShellExecute::ExecShellNew @0x3b78` → `{"/bin/sh","-c",cmd,NULL}` → **`libSTMcmdexecute.so @0x828`：`fork` + `execve`(0x876) + `waitpid`(0x88a)**（无白名单/无转义/chroot/超时；envp 是 .data@0x8cd4 固定 7 串；校验器 0x7b8 只查 path≠NULL、`strlen≤0x1000`、`path[0]=='/'`、argv 数≤≤20）。**但两个调用点的命令行全是 `.rodata` 常量**：`sys_tar_process @0x45e0` 只有 3 个调用点（`0x6874` 备份 `cf /tmp/jiritsu.bak.tar ./ -C /tmp/jiritsu`、`0x69d2` 解包 `xpf /tmp/jiritsu/ramdsk/jiritsu.dat ./ -C /tmp/jiritsu`、`0x7604` 还原），参数来自 `add rX,pc` 的常量串（0x953e/0x9e0d/0x9efd）⇒ **报文里的路径从不进命令行**；`date` 那条根本没有 `%s`。libsencore 的两处 exec（`0x1634a`/`0x16378`）是 `execve("/usr/bin/ulogio.elf", …)` **不经 shell**（只有 1 个字符可控）。⇒ 过滤器不构成防线（空格 `; | & $( ` " ' ( ) * > <` 与 `..` 全部通过；`adj_cmd_set_file_path @0x52a8` 的 0x5318-0x534a 只做 `0x5c→0x2f`、拒 `0x0a/0x0d/0x2c`），但**没有 sink 可用**。
- ★**不需要代码执行就能用的“写 + 删”原语（取代注入的新发现）**【已验（指令级）】：
  - `SET_FILE_PATH(0x400f)` 的 mode 字节（`msg+0x1c`）取 **0**，再 `SET_FILE2(0x4010)`（小头 `mode=0,id=0,flag=0` + 内容）可写任意路径；**不需要先发 `MOUNT(0x4002)`**（SET_FILE2 mode0 自己挂 nflasha6 @`0x5b48`）、不需要清 `/tmp/jbusy`、不需要 `/tmp/jmode=Manual`；路径 ≤512 B、禁 `\n \r ,`、**允许 `..`**（可越界写 `../../etc/…`；但**越界写不在 `.bak.tar` 回滚范围内**，配额也只统计 `/tmp/jiritsu/*`，写满 nflasha10=12MB 会让所有写都报 `0x10000009`）。
  - `FILE_DELETE2(0x4012)`（`cmd_file_delete2 @0x5f18`）：mode 字节 ∈/∉ {0,1} 决定基目录；mode 不是 0/1 ⇒ 基目录=空串（0x997d）⇒ 路径按 `g_customPath` 原样用；末尾带 `/` ⇒ `sys_rm_tree` **递归删**；否则 `sys_file_remove2 @0x43e0` = **`glob(path)` + unlink ⇒ `*`/`?`/`[…]` 会展开**（通配符删除能力，不是 shell）⇒ **别乱发**（一次可以删掉整个目录，含越界到 `/etc`=nflasha10）。
  - 读回用 `GET_FILE2(0x4011, mode0/id0xff/flag0)`；写入用 `0x4010`——这就是“写一个文件、再读回验证”的最小可观测副作用，可当首次上机的零风险探针（tmpfs 版重启自清；flash 版持久）。
- 另：`libSTMcmdexecute.so` 在 **nflasha7**（rootfs）里；旧笔记里的 `prctl(PR_SET_PTRACER)` 不存在（导入表无 prctl）；`/bin/sh`、`/bin/tar` 确为 busybox 软链（解包时丢了 symlink；nflasha7 里是一串 mode `0xa1ff`、target `"busybox"` 的 fast-symlink），相机 busybox = **v1.29.3 (2021-02-04)**。
- **PMCA-RE 那套服务命令在一代全部实现**（在 `libsencore.so`，版本串 `6.02 15-May-2020`）：ProductInfo `0x13834`（含子命令 `0xf1`）、AdjustControl `0x14bed`（比较 `0x601/0x603/0x6b3`）、FileControl `0x14d54`（写走 `WriteDeviceData(path,0x1241,0x8000)`）、MemoryDump `0x14af8`（`mmap /proc`）。
  ⇒ **读备份不需要代码执行**：`CUsbSvc::ReadDataFromBackup @libInfraUsbCmn 0xd0f0` → `Backup_read/nread/get_datasize` → 安全阶梯里"只读拉 `/setting` 校准 `Backup.bin`"可用现成 `pmca-console serviceshell`【已验实现存在；0x603↔1,235,836 B 的对应未验】。
- **但"终端"不是 shell**：`(0x601,0x1f) @0x162bc → 0x16306` 执行 **`/usr/bin/ulogio.elf it|ot`** ⇒ 那是 ulogio 日志控制台，不是 `/bin/sh`（PMCA `serviceshell` 的 `interactiveShell` 在这一代拿到的是它）【已验（指令级）】。

#### 3.1.4 ★同芯片（ZV-E10 = CXD90045）已跑通的部署规则（详见 `notes/camtool.md`）
来头：`github.com/nolan2628/Sony-ZVE-10-Camtool`（10★，2026-10-18）——与 A7C **同 SoC、同内核**，它的红线与错误码对我们是硬约束【同芯片实测】：
- **写 `libJit.so` 必走 `write(16)`=`SET_FILE2(0x4010)`**；用 `FileControl(0xff01)` 写同一路径**不会触发 dlopen**（`cam.py:434-436`）。
- **执行触发点 = 载荷的构造函数**（`DT_INIT`，入口带 Thumb 位）：dlopen 即跑，不必实现 ScriptI 四入口（他们的 `jit_exec_v1*.s` 就没实现）；`cam.py deploy_payload(pad=…)` 用**改文件大小**躲开 dlopen 按名缓存（崩过一次后同会话不再跑 ctor）。
- 错误码：`write(16)→0x10000000` = 空/非法 ELF（干净失败）；抛 USB 异常 = dlopen 阶段崩、**`im.elf` 死后相机 30–40 s 自动重启**（不必拔电池）；`/tmp/jiritsu` 读返回 130 = **nflasha6 被卸载**（删 libJit.so 会触发）→ `0x4002` 重挂。
- `e_flags = 0x05000200`（`EF_ARM_EABI_VER5 | soft-float`）**就是他们实测可用的值**（与我们 `make docker` 产物一致）→ issue #23 “要改 0x5000002”的说法与此矛盾【他证】。手工搭 ELF 时 **`.dynamic` 必须在可写段**（glibc 会写 `l_info`），否则 dlopen 直接 SIGSEGV；我们 gcc 产物天然满足。
- **备份/写回不需要代码执行**：`FileControl(0xff01)` 可直接整段读/写**块设备**（`dump_flash.py`/`restore_flash.py`）。
- **改 `/usr`、`/` 的正确粒度是“整盘 dump → 本地改 → 整盘写回”**，禁止运行中局部写（页缓存不一致 → ext2 错误）；`nflasha15=/usr` 是 **ext2 ro**。
- ZV-E10 有 **`nflasha16` 140 MB 全零空白（天然试验田/暂存）**、`nflasha17` 100 MB 空 FAT16、`nflasha13` 更新历史、`nflasha12` /cert、`nflasha23` 67 MB 未挂载；**A7C 对应分区存在与否要在 L1 用 `partinf.conf` + `ls /dev/nflasha*` 核对**。
- 认证直接复用 PMCA-RE 的 `SonySenserAuthDevice/SonySenserDevice/GenericUsbDriver`；破坏性命使命令 `retries=0`。

调参文件表：`.data.rel.ro`@vaddr 0x3200c 是 34 项 `{u32 id, char* 路径}`（id=0x10..0x1f、0x20、0x30..0x3d），路径全在
`/tmp/jiritsu/Cam_AdjustGuide_Files/{Req_Files,Res_Files}/REQ_*|RES_*.bin`（AWB 等调整文件）→ 一代也有“调整文件”机制。

**A7C II 已商用工具真正改的是什么**（重要参照）【实测读源】：`PROGRAMS = ['appFw.so', 'cpapp-b.bin']`，
经 `/tmp/jiritsu/../..` + 绝对路径读写机身文件：`/usr/lib/appFw.so`（chip0）与 `/cp/cpapp-b.bin`（chip1），
用 `before/after` 字节跳 + `file_offset` 的前置条件做**就地字节补丁**（`core.py:58-67`），新程序要**取电池重开才加载**。
→ 注意 A7C **一代** v2.00 的 /usr 里**没有** `appFw.so`/`cpapp-b.bin`（nflasha15 全量解包 941 个文件里只有 `bin/im.elf` + `lib/libObj.so` 这类），
也**没有** `/cp` 挂载点 → 一代的"程序载体"不同，需自己定位（并考虑 cpapp 可能在 nflasha1/其他分区）【实测】。

拿到代码执行后，`/etc`（= nflasha10，12 MB vfat，挂 /tmp）根目录写 `ld.so.preload` →
下次开机 `im.elf` 里插进自家 `.so` → 有 busybox（ash + dd）→ 直接写分区。
ZV-E10 上这条路已把内核→init→33 模块→`im.elf` 在 QEMU 里整套跑起来【他证】。

### 3.2 直写分区的落点（A7C `0100_config/mount.conf` 实测）
```
/dev/nflasha1  none    vfat   8 MB      更新器 ramdisk（不在 part_image 里！要自己 dump）
/dev/nflasha2  /setting vfat  20 MB     Backup.bin、updater/mode*、dat4、sen/smode
/dev/nflasha3  /system  vfat  48 MB
/dev/nflasha5  /wbi     wbi    60 MB    eMMC/WBI 信息（ud_wbi_drop 会动它）
/dev/nflasha7  /rootfs  raw    8 MB
/dev/nflasha10 /tmp     vfat   12 MB    ← ZV-E10 实测 /etc 的实体就在这（A7C 同结构）
/dev/nflasha11 /log     vfat   500 MB   ← 安全的暂存区（放我们的 payload/备份）
/dev/nflasha15 /usr     raw    300 MB   ← 要改的就是它（里面有 56 MB 空闲）
/dev/nflasha23 /PMBP    prfile  2 MB
```
两条纪律（ZV-E10 实机教训）【他证】：
- **不要原地改 /usr**：改动放 `/log` 再用 `mount --bind`，并配"开机 N 秒没看到 UI 进程就自动回滚"。
- **`/tmp /etc /var` 同一块 12 MB**：写满之后**连自救写入都会失败**（错误 0x10000009）→ 救援必须只有 1–2 字节。
- 分区镜像偏移口径：`镜像文件内偏移 = partinf 表内偏移 + 0x400000`（boot0/boot1 各 2 MB），
  而真机用户区偏移就是表内偏移本身（例：nflasha10 → 0x0AC00000，块号 0x56000）。

### 3.3 版本/机型杠杆（路线 C）
- 机身侧：`/usr/bin/up.sh`【实测存在】`user / serv(user+mode3) / ver(mode+mode6=VERSKIP) / ms(mode+mode5) / modmod / modreg / modver`，
  改的就是 `/setting/updater/mode*` 与 `dat2/dat3/dat4`（`ud_datcnv.elf -e/-d` 走 `libosal_uipc` IPC 服务）。
- 旗标语义（`nflasha15/bin/up.sh`【实测】）：`mode`=UFP（用户更新）；`mode`+`mode6`=Version Skip；`mode`+`mode5`=MS Crypt；`mode`+`mode3`=Service mode；`func_usermode` 会 `rm -f /setting/updater/mode*`。
  后果差异（`us_mkfs.sh`【实测】）：`mode6`(VERSKIP) **会跑 `edisx.elf` 重写分区表 + `uc_mkfs.elf -m full` 全盘重建**（连 /setting、/log 这类 vfat 也重建，事后只 `ud_keep_backup.elf -s` 还原 `Backup.bin`）；
  普通 `mode`(USER=3) **不跑 edisx、只 `-m app`**。→ 降级/刷同版比正常升级更激进：提前把 /setting 与 /log 里自己放的东西（payload、备份）取到 PC/SD。
- 包侧：FDAT 头 `+16 modeType`（'U'/'O'/'M'/'P'）在**平台公开 key** 保护的 512 B 里 → 自制头即可切模式（A7C 上是否被接受【未验】）。
- ZV-E10 实机验证过的兜底：把 `dat4`（2 B BCD）写成 `00 00` → 相机报 0.00 → 任何官方包都能灌【他证，另一机型】。
  **★本轮已离线讁实：A7C 的 `dat4` 就是两字节小端 BCD**——在 arm/v7 容器里跑相机自己的
  `/usr/bin/ud_datcnv.elf`（它虽然报 `open /dev/uipc error` 但本地编码/解码照样成）：
  `ud_datcnv.elf -e -a` 对输入做“**两两十六进制数字 → 一个字节，低位先写（LE BCD）**”：
  `0200`→`00 02`、`0100`→`00 01`、`0000`→`00 00`、`9103`→`03 91`、`0191`→`91 01`、`000000910319`→`19 03 91 00 00 00`；
  `-d -a` 能完整解回 ASCII（带换行）。⇒ **`dat4` = 版本文本的 2 字节 LE BCD**（版本 2.00 存的是字串 **`"0200"` → `00 02`**，不是 `"2.00"`；
  `"2.00"` 会被编成 `00 2e`，因为 `.` 按低半字节变成 0xE），
  **`dat2` = 机型码 8 位 hex → 4 字节 LE BCD**（与 FDAT 头 model=`0x91030019` 的小端字节序 `19 00 03 91` 一致），
  **`dat3` = 区域码（region 0 ⇒ 4×`00`）**。不加密、无校验 ⇒ **ZV-E10 的“dat4 裸写 `00 00`”对 A7C 成立**【已验（跑的是相机自家二进制）】。
  不带 `-a` 的是另一种“半字节交换 +0x30”写法（`0200`→`00 30 30 32`），**不是** `up.sh` 用的那个，别混。
  坑：输入 **>8 字节或 >16 字符时 rc=0 但输出 0 字节（静默写空）**；无 magic/无校验，手写字节与工具产物完全相同（详见 `work/DATCNV_RESULTS.md`）。
  ⇒ 不需要代码执行也能改身份/版本：把 `nflasha2`（/setting）整段 dump → 改 `updater/dat4` 两字节 → 整段写回（风脸：a2 里还有校准 `Backup.bin`）。
  有代码执行时首选自带工具：`up.sh modver <4位>`（`func_modver` 要求长度正好 4，先 `-d -a` 读旧值再 `-e -a` 写回，不会打坏格式）。
- ★**身份写错不是不可逆**：`us_crc32sum_appli.sh`（`appli` 段后处理）会 `if [ -e /ramdsk/dat4 ]` 则
  **`cp /ramdsk/dat2 /mnt/`（=nflasha1）、`cp /ramdsk/dat3 /mnt/`、`cp /ramdsk/dat4 /setting/updater/`**
  ⇒ **更新器 ramdisk 里存着 dat2/dat3/dat4 的原始副本**，官方更新能自己把机型/区域/版本恢复回去【已验脚本内容】。
  代价：同一个脚本紧接着 `touch /setting/updater/mode mode6` ⇒ 跑过 `appli` 段后会**以 Version Skip 再进一次更新模式**。
- 不依赖代码执行的另一种改身份方法：把 `nflasha2`（/setting, vfat 20 MB）整段 dump → PC 上改 `updater/dat4` → 整段写回
  （同芯片 camtool 的“整盘 dump/restore”规则）；风脸在于 a2 里还有校准 `Backup.bin` ⇒ 必须先确认两次读一致再写【推断，未验】。

### 3.4 BootROM 串行启动（路线 D，反砖兜底）【他证】
`refs/zve10-qemu/zve10-uart-boot`：BOOT_SERIAL_IN ← USB-C **D−**(A7) 经 470Ω；XRESET_REQ ← **D+**(A6) 经 470Ω；
CC1/CC2 各 5.1 kΩ 下拉；BootROM 记录流 **48000 baud 8O1**，慢块 250 µs、组内静默 <293.6 µs、整组 <1.45 s；
之后 UART0(`0xF2000000`) 115200 控制台；可执行任意 ARM32（`0xFE020000`）。
纠偏：三代机（CXD90045）组首/组末必须同为 **SET_UNLOCK**（不能用 A7M4 的 `END_MARKER 0x0123`，否则 `0x2004`）；
解锁 token 由**本机 boot0@0x200 的 8 字节**决定（不是公开常量）；eMMC PEF1G4 按**非高容量**访问（CMD17/24/25 ARG = 字节地址）；`wdt.timeout=500` ⇒ 单块写。
"1 字节修复法"定稿：把 nflasha10 FAT 根目录项的 **size 字段（+28..31）清 0**（只写 1 个 512B 扇区，幂等、写后读回）→ glibc 读到空 preload 列表。
仓库多处记"**A7C 实测可发 5,149 B payload**"（接线点需向作者确认）。

### 3.5 QEMU 离线验证（同 SoC，强烈建议先做）【他证】
ZV-E10 已跑到：内核 → init → 33 模块 → `im.elf` 常驻、`libObj.so` 加载、280 线程、零崩溃；
显示"通道"已通（`/dev/mem` mmap 物理 `0x20312000` → QMP screendump 可见，**不需要 GPU 模型/ramfb**）。
跑法：`scripts/run_qemu_zve10.sh`（`-M cxd90045`、`-drive if=mtd,file=全盘 eMMC 镜像`、`-device loader,file=BACKUP.BIN.fixed,addr=0x02E80000`）；
需要 4 件：全盘镜像、真机 cmdline（`/setting/kemco.txt`）、`BACKUP.BIN.fixed`、打补丁的内核（`adrs_conv`/`CONFIG_PCI`/tty-visible）+ QEMU 补丁（DDR/WBI/ATAGS、sd-cid）。
**他们已在 QEMU 里跑通更新器链**（`UdtrMain.sh → 强制 Prod MODE=1 → ud_im.elf → execute_prod.sh → mf → sen.elf`）→ 这就是"改包能不能过关"的正确离线实验台。
注意固件会**主动检测 QEMU**（`init` 里有 `check_qemu()`，`im.elf` 里有 `qemu` 字符串）。
A7C 侧缺口：包里**没有 0400_updater**（`mf/UdtrMain.sh/dat2-3/p1chksum` 都在相机 nflasha1 上，必须先 dump）【实测：本包 part_image 只有 3/5/7/15】。

已核对本机可行性（见 `notes/toolchain.md`）：他们的 QEMU 形态是**补丁集**（`patches/qemu/{bionz,sd-cid,qemu-cxd90045-vip-display}.patch`），
而基座是 **`qemu-sony`：它就是公开的 `github.com/ma1co/qemu`（fork，20★，`VERSION 5.1.0`，最后推送 2021-06-19）**，
`hw/arm/bionz.c` 里有 `DEFINE_MACHINE("cxd90045", cxd90045_machine_init)`（`cortex-a5`、`CXD90045_DDR0_SIZE 0x40000000`、`SRAM_BASE 0xfe000000`、`SDHCI_BASE 0xf0304000`）⇒ **QEMU 路线不再被“源码拿不到”卡住**：
取该树 + 叠我们已有的 `patches/qemu/{bionz,sd-cid,vip-display}.patch` 即可（公开快照的 `boot_size=0x40000`、DDR 与真机不符，止于补丁要改的 4 处）。
仍缺：打过补丁的 A7C 内核源码（包里只有不可补的 `vmlinux.bin`）。另一条公开新路线：`chocotan/a7c2-qemu`（QEMU 11.1.2 + `qemu-sony-native/usb.patch`，但 `-machine virt -cpu cortex-a35` 是 arm64，需改成 armv7）。
另注意同芯片工具链红线：ZV-E10（=CXD90045）实测 **`FIRMUP(0x4006)` / `FORMAT(0x4003)` 会挂死服务模式**，且官方载荷写 `libJit.so` 用的是 `write(16)`（=SET_FILE2）而不是 FIRMUP（见 `notes/camtool.md`）。
本机无 qemu；最短路径 = OrbStack 里 linux/arm64 容器编 QEMU 5.1（`--target-list=arm-softmmu`）。
**包里其实能提供的 QEMU 输入**（之前我判断过于悲观）：`0800_appli/setting/kemco.txt`（真机 cmdline，`mem=1G@0`/`mem=256M@0x80000000@1` 与他们 bionz 补丁的对齐值一致）、
`nflasha3/initrd.img`（他们说的“真机导出 initrd”其实就是来于包）、`partinf.conf` + nflasha{3,5,7,15} ⇒ 可合成近似整盘。
**仍需真机 dump**：`/setting` 里的 `Backup.bin`（1,235,836 B，逐机校准；包内 `0110_backup/SYSASTRA-DSLR/NB*/CH886xx_*.bin` 是 1,210,408 B 的语言/地区固件，**不是** BACKUP.BIN）、
nflasha12 /cert，以及 nflasha1 / boot0 / boot1 / nflasha2/6/10/11（更新器 ramdisk 与 loader）。

---

## 4. 落地顺序（建议）

> 本轮（读完包内更新体脚本后）的**最新落地顺序与风险分级以 `TEST_LADDER.md` + `notes/updater_flow.md` 为准**；
> 下面这一段是早期写法（其中“写 `tools/fdat_repack.py`”已降级为 `tools/fdat_hdr_edit.py`，因为路线 A 被签名边界卡住）。
> 新发现改变了两个前提：①同版本重刷可以用 `up.sh modver`/旗标模式而不必上 VERSKIP；②门禁库 `libupdaterufp.so` 自身就在可重建的 a15 上，可作为直接靶子。

1. **离线**（零风险）：
   - `python3 tools/fdat_aescbc.py <dat> /tmp/fdat_dec.bin` → 复现 §1（帧校验 338092/0）。
   - 用 `tools/verify_sums.py` 复现 `.sum` 只有 CRC32+size（124 条记录、123 文件全对）。
   - 写 `tools/fdat_repack.py`：按 §1.2 规则**重加密 + 重帧 + 头 CRC32 + DEND CRC**，做往返 `cmp`（证明"除了签名，我们造得出来"）。
   - 在 A7C 的 `nflasha15_unpacked` 里把 §1.3 的头字段/fs 表与 `partinf.conf`/`mount.conf` 对齐成一张表（含空闲 56 MB）。
2. **确认签名归属**（关键）：A7C 包里 **没有 nflasha1**
   （实测 `0700_part_image/dev/` 只有 `nflasha3 / nflasha5 / nflasha7 / nflasha15`，且 `part_image.sum` 也只列这 4 个）
   → 必须从相机 dump 它，才能读 `mf/UdtrMain.sh/dat2/dat3/p1chksum` 并定位 RSA 验签；可先拿 ZV-E10/A7 IV 等 CXD90045 机型的 updater 分区代研。
   **工具已就位**（无需代码执行）：`.venv-jir/bin/python tools/jiritsu_send.py dump nflasha1`（FileControl 整读块设备，完事就地扫 vfat 目录项）。
3. **路线 B 上真机**（**分级执行与砖风险评级见 `TEST_LADDER.md`**）：服务模式 → 先用 `FileControl(0xff01)` 整段 dump `nflasha15/3/7/6/2` 到 PC（不需代码执行）→ **`SET_FILE2(0x4010)` 写自家 `libJit.so`**（同芯片实测：这是触发 dlopen 的唯一通道；载荷大小略变以躲缓存；干活放 `.init` ctor）→ 拿到代码执行后再对 `nflasha15` 做“整盘写回”式改动；`set_firm(0x4006)` 与 `FORMAT(0x4003)` 默认不发（同芯片实测卡死服务）；`ld.so.preload`（`/etc`≡nflasha10）只做兜底（busybox 动态链接，preload 写错直接全灭）。
   已经做掉的前置：PC 侧发送工具 `tools/jiritsu_send.py`（鉴权/Jiritsu 全部命令/FileControl 块设备流式读写/状态码翻译/默认护栏/mock 演练），arm32 链接与自测 `tools/jit_worker`（ctor 触发已验），载荷格式用相机自家 busybox 验过 rc=0。
   原路径：Jiritsu（`/tmp/jiritsu/…` + `..` 越界）→ 写 `/etc(=nflasha10)/ld.so.preload` → preload `.so` → busybox shell
   → 先 `dd` 备份 nflasha1/2/3/7/10/15 + SHA-256，再演练"改 nflasha15 里一个不关键的文件"。
4. **兜底准备**：先把 BootROM 桥焊好、跑通发 payload + 单块写 eMMC（先在 QEMU 演练救援 payload）。

---

## 5. 必须备份的东西（改之前）

| 目标 | 为什么 |
|---|---|
| `/setting/Backup.bin`（nflasha2） | 唯一承载校准数据；`ud_keep_backup.elf -s` 会还原它；`keep_big_backup.sh` 只保 `/setting/psd.bin` |
| `/dev/nflasha1`（更新器 ramdisk） | **包里没有它**；`mf/UdtrMain.sh/dat2/dat3/p1chksum` 都在里面，缺它就无法研究验签与更新入口 |
| `/dev/nflasha10`（=/tmp、/etc） | `ld.so.preload` 的家；"1 字节修复"的作用对象；**`/tmp/jiritsu.bak.tar` 也落在这（12 MB，刷前看剩余空间）** |
| `/tmp/jiritsu/` 原有内容（`libJit.so`、`tmmc.jit`、`DIAC.csv`、`ver.txt`） | **更新包里没得 nflasha6 镜像**（part_image 只有 a3/a5/a7/a15）→ 本地无原厂副本；刷前必须先经 `GET_FILE2(0x4011)` 逐个拉回 PC，否则原厂 worker 永久丢失 |
| `/dev/nflasha6`（Jiritsu 区 16 MB） | 就是 `/tmp/jiritsu` 的挂载点，路线 B 的落点；刷前 dump 原内容与 `libJit.so/tmmc.jit/DIAC.csv/ver.txt` |
| `/dev/nflasha15` 全镜像（300 MB） | 改动目标；同时留 `ext2` 镜像与逐块 SHA-256 |
| `/setting/updater/dat4` + nflasha1 的 `dat2/dat3` | 机型/区域/版本身份；`us_crc32sum_appli.sh` 会先把它们从 `/ramdsk` 写回 |
| `/dev/nflasha5`(WBI) / `/dev/nflasha4`(MPR) | `ud_wbi_drop.elf`、`endupdate.sh: ud_lerase.elf /dev/nflasha 4` 会擦它们 |

破坏性清单（更新器实做，务必绕开）：`edisx.elf /dev/nflasha partinf.conf`（重写分区表）、`uc_mkfs.elf -m full`、
`ud_wbi_drop.elf`、`dosfsck -Y /dev/nflasha2`、`ud_lerase.elf /dev/nflasha 4`、`pformat.elf /dev/nflashaB0`（刷 loader，最危险）。

---

## 6. 未验清单（按价值排序）

1. **A7C 的 256 B 签名由谁验**（`mf`? `crypter.elf`? PC 端 app?）——决定路线 A 死活。
   注意一个逻辑死锁：若验签在 nflasha1 的 `mf` 里，而包又不刷 nflasha1 → 想绕过就得先能写 nflasha1（即路线 B），
   所以路线 A 只在"已经拿到代码执行"之后才有意义。
2. **Jiritsu 命令号→函数映射**：【他证，两处独立反汇编相互印证】`jiritsu_init` 注册 osal 回调后由一级 TBB 表（`ldrh [msg+0x1a]`，命令号 1..19）分发；**15/16/17/18 = set_file_path / set_file2 / get_file2 / delete2，与 A7C II 工具的用法完全一致**【已定】wire 寻址：`PFUNC=0x40` + `block=0x1001`, `code=0x4001..0x4013`（FIRMUP=0x4006、SET_FILE2=0x4010、MOUNT=0x4002、DEBUG=0x4005）；MOUNT 与 SET_FILE_PATH 已在同平台他机实测返回 0（`notes/a7c2-tools.md` + ZV-E10 `docs/JIRITSU_CHANNEL.md`）。仍缺：`libSTMcmdexecute.so`（包里没有，需从相机 dump）、Senser payload→请求体字段偏移（他机上 GET_FILE 还没打通；但二代工具的 payload 布局已可用）。
3. 头 `modeType='O'` 是否等价 verskip、**验签是否覆盖身份字段**：两个测试包都做好了 —— 先用 `/tmp/ILCE7CV200.region1.dat`（只改 region，预期在门禁处安全中止，不碰分区），再用 `/tmp/ILCE7CV200.modeO.dat`（会走 VERSKIP → edisx + full 重建，先备 /setting 与 /log）。
   **【本轮已答】`dat4` 不是“裸写 00 00”而是编码文件**：`up.sh modver/modmod/modreg` 用 `ud_datcnv.elf -d/-e`（逆序逐字节、半字节 +0x30，无密码学）读写
   `/setting/updater/dat4`（版本）与 `nflasha1:/dat2`、`/dat3`（机型/区域）—— 所以身份可以用相机自带的 `up.sh` 直接改，不需刷写【代码证实，见 `notes/updater_flow.md` §3】。
   `modeType` 在 USB(UFP) 路径上只接受 `'U'/'O'`【已验】，但模式还可以由 `/setting/updater/{mode,mode3,mode5,mode6}` 旗标选择（`us_mkfs.sh` 对这四种都不跑 edisx）。
4. `p1chksum` 是否会卡住我们自写 nflasha1/nflasha3 —— 仍未定（nflasha1 未 dump）；不过包内 `config.xml` 里确实有 `loader_sum/loader.sum → loader_writer.sh → pformat.elf /dev/nflashaB0` 这条官方 loader 写入通道（本包**没有** loader 段 ⇒ 这次更新不动 loader）。
5. A7C 包内**没有** `0400_updater`（不刷更新器分区）——已证实；但 `config.xml` 保留了 loader/front/furud/accsy 等段落占位，说明升级更新器/loader 的官方通道在那（只是这个包不用）。
6. **A7C 一代的"可挨打的程序载体"到底是什么**：二代用 `/usr/lib/appFw.so` + `/cp/cpapp-b.bin`，一代 nflasha15 里两者均不存在；候选是 `bin/im.elf`/`lib/libObj.so`/`codec`/`kmod`，以及未在包内的 cpapp 镜像（可能在 nflasha1 或单独分区）。
7. `config/uconfig.xml`、包内 `program/` 目录（PATH 注入）是否真被 A7C 更新器读取（§`UPDATER_ANALYSIS.md` 的 `us_darwin_firm.sh` 缺失之谜；同类：`updater_log.sh`、`updater_storage_backup.sh`、`ud_frfup2.elf`）。
   **【本轮补充】`updater.img_unpacked/config/config.xml` 已逐行读完（见 `notes/updater_flow.md` §2）：作业表就是 `*_sum/<name>.sum → 脚本` 的映射；
   `us_darwin_firm.sh`/`us_ca_firm.sh` 在 `udtrbody.bin` 解包体里没有，但 `config.xml` 引用了它们 ⇒ 这些脚本在 nflasha1 的 ramdisk（`/ramdsk/updater/bodyfs/bin`）里，同一个 `body_common.sh` 就在 `updater.img/bin/`。仍缺：`updater_log.sh`、`updater_storage_{mount,backup,restore}.sh`。
8. **（新）官方更新会不会“校机身现有文件”？** `us_crc32sum_appli.sh` 把机身 `/setting` 挂到解包目录里再跑 `uc_crc32sum.elf -c appli.sum`，
   而 `appli.sum` 里有 14 条指向 `setting/`(4) 与 `tmp/`(10) 的条目 ⇒ 如果它校的是**机身现文件**，那我们改了 `/setting/kemco.txt` 之类后官方更新可能 CRC 不过（LED `0x82`）；
   如果只校包内，则改 /setting 不影响下次刷。读 `uc_crc32sum.elf`（已在手，在更新体里）就能定【待做】。
9. **（新）CBC 的 key/IV 不在包里任何镜像里**（nflasha15/3/5/7 + updater.img 全量字节搜索 0 命中）⇒ CBC 层在芯片里的 LDEC 硬件（`initrd/kmod/ldec.ko`，导出面只有 DMA 描述符字段，无 key）；
   而 ECB 层的 key 就在软件里（`/usr/lib/libupdatertalk.so` 偏移 `0x830`）。⇒ 推论：拿到代码执行后可以用 `/dev/ldec*` 让硬件用片内 key 加/解数据（路线 A 最现实的执行手段）【推断】。

---

## 附录：本次新增/实测命令

```bash
# FDAT 解帧 + 两段解密（公开 key）→ 帧校验 338092 全过
python3 tools/fdat_aescbc.py \
  ~/Downloads/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV200.dat /tmp/fdat_dec.bin

# 只验外层容器 CRC
python3 - <<'PY'
import zlib
b=open('/Users/wubin/Downloads/SystemSoftwareUpdater.app/Contents/Resources/FirmwareData_ILCE7CV200.dat','rb').read()
print(hex(zlib.crc32(b[:-12])&0xffffffff), b[-4:].hex())   # 0xaaaa81b8
PY

# .sum 只有 CRC32+size（124 条 / 123 文件全对）
python3 tools/verify_sums.py

# 最小改包：往返证明 + 改 modeType（只动公开 key 的 512B 区，重算三处 CRC）
python3 tools/fdat_hdr_edit.py <DAT> --prove
python3 tools/fdat_hdr_edit.py <DAT> --set-mode O --out /tmp/ILCE7CV200.modeO.dat

# Jiritsu 通道载荷打包 + worker（路线 B）
python3 tools/jiritsu_pack.py <staging_dir> -o jiritsu.dat
python3 tools/jiritsu_pack.py --check-so tools/jit_worker/libJit.o   # 校 e_machine==40 + 4 个 Script 导出
make -C tools/jit_worker                                            # 链接需要 GNU ld/lld 或交叉 gcc（或 arm32v7 容器）

# 用相机自己的 busybox/glibc 离线跑（验证 tar、跑它自己的 ELF）
bash tools/camuser.sh                       # 自检：打印相机 busybox 版本
bash tools/camuser.sh work/t_tarcheck.sh    # 脚本里 . /t/camprefix.sh 后用 BB/CAM

# PC 侧发送工具（服务模式；先 --mock 离线演练）
python3 tools/jiritsu_send.py frames 'sel=/tmp/jiritsu/libJit.so' 'w16=/tmp/jiritsu/libJit.so:tools/jit_worker/libJit_padded.so'
python3 tools/jiritsu_send.py --mock l1 --dir work/l1_mock --dump nflasha7,nflasha3
.venv-jir/bin/python tools/jiritsu_send.py scan
.venv-jir/bin/python tools/jiritsu_send.py l1 --dir work/l1 --dump nflasha1,nflasha6,nflasha7
.venv-jir/bin/python tools/jiritsu_send.py put /tmp/jiritsu/libJit.so tools/jit_worker/libJit_padded.so

# 反汇编（不带 r2 的自研注释器，见 tools/ufpdis.py、tools/talkdis.py）
python3 tools/ufpdis.py firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdaterufp.so
```
