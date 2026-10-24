# A7C 一代（ILCE-7C v2.00, CXD90045）updater 侧"验签"复核

方法：纯离线静态（rabin2 / r2 / capstone(tools/ufpdis.py) / strings / 自写字节扫描）。全程未碰相机。
标注：**【已验(指令级)】** = 本文给出地址+指令，可复现；**【推断】** = 由已验事实推出；**【未定】** = 缺工件。
所有地址都是**文件 vaddr**：`libupdaterufp.so`/`libupdaterbody.so` 等 PIE 库 vaddr==paddr；`crypter.elf` 是 ET_EXEC、base=0x8000（文件偏移 = vaddr − 0x8000）。

一句话结论：**在我们手里的 A7C 一代工件里，没有任何一处对更新数据做数字签名校验**（无 RSA/ECDSA/EVP 符号、无公钥、
`crypter.elf`/`libupdater*` 全都不链接 libcrypto）。代二报告里的 `VerifySignature`/`0x30002=RSA 失败` 在一代**不成立**：
一代的 `0x3000x` 是一整套 ApiException 通用错误码，`0x30002` 出现在 `DecryptorModule.cpp:81`（AES 分组未对齐）等处，与签名无关。
**但**：一代包内**没有 nflasha1（Updater 分区/更新器 ramdisk）的镜像**，所以"256 B 尾部 blob 到底谁验、验不验"在一代仍是【未定】。

---

## 1. 文件定位【已验】

```
find . -name 'libupdaterufp*' -o -name 'libupdaterapi*' -o -name 'sauu*' -o -name 'libupdatertalk*'
  ./firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdaterufp.so      (12,936 B, ARM32 Thumb, stripped)
  ./firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdatertalk.so      (3,404 B)
  ./firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdatertalk.so 同目录还有
      libupdatercommon.so libupdatermedia.so libupdaterufunc.so
```
- **不存在** `sauu`、`libupdaterapi*`（A7C II 报告的两个证据锚点在一代包里根本不存在）【已验：全树 find/grep】
  grep 全树 `VerifySignature|UFPDecryptor|sauu|libupdaterapi` 只命中
  `nflasha15_unpacked/bin/bsa_server` → 实为蓝牙栈 `BTM_BleVerifySignature`【已验：strings】。
- **`updater.img_unpacked/`（=FDAT 里的 updater bodyfs，47 个文件）里没有 `libupdaterufp.so`**：
  只含 `bodylib/libupdaterbody.so`、`usr/lib/libupdatercommon.so`、`bin/*.sh`、`bin/*.elf`【已验】。
  `updater.img` ≡ `nflasha15_unpacked/bin/udtrbody.bin`（逐字节相同，见 UPDATER_ANALYSIS §1）。
- 真正做"解密+写更新器 body"的是 **`nflasha15_unpacked/bin/crypter.elf`（39,036 B, ET_EXEC base 0x8000, stripped）**，
  它在 **usr 分区**里，不在 FDAT 的 updater body 里【已验】。

## 2. 有没有验签符号 / 字符串

`rabin2 -i/-E`（= .dynsym 导入/导出）：

| 模块 | 与密码学相关的**全部**符号 | 结论 |
|---|---|---|
| `libupdaterufp.so` | 导入只有 `Dec_ScrambleInit @0xf90`、`Dec_Scramble @0x1074` | 【已验】无 RSA/EVP/verify |
| `libupdatertalk.so` | 导出 `KeyArray(32B)@0x8830`、`decx@0x8854`、`Dec_ScrambleInit@0x620`、`Dec_Scramble@0x648`；`Dec_ScrambleInit` = `b.w sym.imp.AES_set_decrypt_key(key=KeyArray, 0x80)`；`Dec_Scramble` = `AES_decrypt` 16B + 拷回 → **AES-128-ECB** | 【已验】唯一的原语 |
| `crypter.elf` | 导入只有 `Dec_Scramble @0xaaa8` / `Dec_ScrambleInit @0xa98c` | 【已验】无验签 |
| `libupdaterbody.so` / `libupdatercommon.so` | strings `rsa|evp|sign|verif|sha|md5|aes|crypt` **0 命中** | 【已验】 |
| nflasha3 initrd `sbin/init`（含 debug_info）/ `kmod/*` | 无 sign/verify 相关 | 【已验】 |

DT_NEEDED（`rabin2 -l`）里**都没有 libcrypto/libssl**：
```
crypter.elf      : libupdatercommon libupdatertalk libSysDef libMWF libInfraFsys libInfraMediaCommon libbackup libosal_uipc libosal_utm ...
libupdaterufp.so : libupdatertalk libupdatermedia ...
libupdaterbody.so: libInfraFsys libupdatercommon libul_xml libbackup ...
```
→ **crypter.elf 结构上不可能做 RSA/ECDSA 验签**【已验(ELF 级)】。

`0x30002` 在一代确实存在，但**是通用错误码**：`crypter.elf` 里出现的 0x3000x 家族共 13 个不同值
（0x30000,1,2,7,f,10,11,12,15,17,1a,25…）。`0x30002` 的抛出点（每处都有 `printf("UdrAPI,%d,%s:%d,...")` + `__cxa_allocate_exception(0xc)` + `__cxa_throw`）：
```
DecryptorModule.cpp:0x51(81) @0xe044   ; 前置条件：ldr.w r3,[r5,0x458]; ands r4,r3,0xf; beq ok  → 长度不是 16B 整数倍
DecryptorModule.cpp:0x2d/0x3b/0x69/0x70 @0x…
BaseBodyLoaderModule.cpp:0xee(238)/0x130(304)/0x18a(394)/0x18d(397) @0xc0c0/0xc0f0/0xc52a …
CryptFileInputUpdaterManager.cpp:0xa5(165)
```
【已验】→ **一代没有把 0x30002 用作"签名失败"**；它 = "解密/取体失败"。

## 3. 写入路径与"校验覆盖哪些字节"（指令级）

### 3.1 `libupdaterufp.so` 的 UFP 路径（PC→相机，USB）

`udtr_ufp_init @0x20e8`（门禁数据装载，**先于一切写入**）【已验】：
```
0x20f4 blx Dec_ScrambleInit            ; 装载 KeyArray(AES-128)
0x2150/0x215a/0x2166/0x2168 mount("/dev/nflasha1","/mnt","vfat","posix_attr",0xc0ed0001)
0x217a open("/mnt/dat2") → read 4B → 0x2196 ldr r3,[r5,#set_model]; 0x2198 str r2,[r3]     ; 本机 model
0x21a2 open("/mnt/dat3") → read 4B → 0x21da str r2,[set_region]                            ; 本机 region
0x21e8 ldr r0,[set_version]; bl 0x1500   ; 0x150c open("/setting/updater/dat4") → read 2B → 0x1530 strh [r5]=set_version
```
→ `set_model/set_region/set_version` = **本机身份**；`firm_model/firm_region/firm_version` = **包里的值**（下面从包头解出）。

收块处理函数 `0x1a24`（UFP chunk 回调，注册在 `osal_reg_sync_msg_queue_cb`，见 0x2011/0x1599/0x1a25）【已验】：
```
0x1b5a add.w r6, r4, #0x28            ; r4=packet(.bss @0xad98, 65568B)
0x1b62 blx Dec_Scramble               ; 循环: sb+=0x10, cmp.w sb,#0x200 → 恰好 512 B，16B/块 ECB
0x1b76 ldr r0,[r6,#0x28] → 0x1b7c str → firm_model      ; = 包(header)+0x24
0x1b78 ldr r2,[r6,#0x2c] → 0x1b82 str → firm_region     ; = header+0x28
0x1b86 ldrh r2,[r6,#0x24]→ 0x1b8a str → firm_version    ; = header+0x20
0x1b8c ldrb r3,[r6,#0x14]; cmp #0x4f 'O'; cmp #0x55 'U' ; header+0x10 = modeType，只允许 'U'/'O'，否则错误 0x1031
0x1c00 cmp r3,#0x4f / 0x1c08 str #1 → verskip = 1        ; modeType=='O' ⇒ verskip 置位
0x1c1e bl 0x1684 (→ 门禁 0x127c)      ; 失败即 0x101 应答并退出，**不再往下写**
```
⇒ **ECB 解的就是 FDAT 明文的最前 512 B（UDTRFIRM 头）**；被读的字段只有 4 个：`modeType(+0x10)`、`version(+0x20,u16)`、`model(+0x24,u32)`、`region(+0x28,u32)`。与 `FIRMWARE_MOD §1.3` 的离线布局完全对齐【已验】。

**门禁函数 `0x127c`**（被 0x168c / 0x1968 / 0x1e66 调用）【已验】：
```
0x128c ldr r3,[acsy_flag]; cmp #1          ; acsy_flag==1 → 先用 IPC(0x11f0/0x1340) 重新取本机 model/region/version
0x12a2/0x12a4/0x12aa 清零 set_* ；0x12ac bl 0x11f0 ；失败 → 返回 0x2000
0x12bc/0x12be/0x12c0 str ← 从 IPC 应答 +4/+8/+0 填 set_version(u16)/set_model(u32)/set_region(u32)
0x12c6 ldr r2,[firm_model]; 0x12c8 ldr r3,[set_model]; 0x12ca cmp; bne → 0x1306 mov.w r0,#0x140   ; 机型不符
0x12d2/0x12d4/0x12d8/0x12da cmp firm_region vs set_region; bne → 0x130c movw r0,#0x141           ; 区域不符
0x12e2 ldr r0,[verskip]; cmp #1; beq → 0x1310 movs r0,#1                                          ; verskip=1 ⇒ 跳过版本比较
0x12ee ldr r0,[firm_version]; 0x12f2 ldrh r3,[set_version]; 0x12f4 cmp; ite ls → 0x142 / 1        ; 包版本<=本机 ⇒ 0x142
```
`udtr_conv_stat2err @0x274c`（状态→对外错误码）【已验】：`1→0, 0x40→4, 0x100→8, 0x101→9, 0x140→7, 0x141→6, 0x142→5, 其它→2`。
⇒ **"机型不符"=内部 0x140；"区域不符"=0x141；"版本不许降/相同"=0x142；`verskip`(mode6/'O') 只放宽版本，机型+region 永远要过**【已验】。

写与执行（门禁之后才发生）【已验】：
```
0x1896..0x18b2 snprintf("%s/%s", mediaPath, "LENSDATA.DAT"|"BODYDATA.DAT") ; 0x18b8 bl udtr_write_firm_from_media
0x2668 udtr_write_firm_from_media: mount tmpfs "size=5M" @0x26dc → open("/tmp_updater/Firm.dat",O_CREAT 0x26ea) → write(fd,chunk,len) 0x2706
0x18d4/0x1dd8 argv 表 @0xaaac / 0xaab8 = {"/usr/bin/crypter.elf", "/tmp_updater/Firm.dat", NULL} → stm_system(argv,3,...) 0x18e2/0x1dd8
0x1fca/0x1fd6/0x2098/0x20a6 argv 表 @0xaa94/0xaaa0 = {"/usr/bin/up.sh","user"}, @0xaac4/0xaadc = {"up.sh","ver"}, @0xaad0 = {"up.sh","ms"}
   ; verskip==1 → 走 "ver"（0x1fc0 cmp verskip,1 → 0x1fc8 选 "ver"），否则 "user"
0x1ed0 "ufp_reboot" + osal_create_waitable_thread（重启进更新器）
0x1e3c bl udtr_copy2dmm（mmap /dev/mem，@0x2358 udtr_copy2dmm）  ; ACCYFIRM.BIN 等大负载走 DMM/DMA 通道
```
另有 `udtr_get_firm_info_inmedia @0x25dc`：在介质里以 8B 步进搜索 4 字节 magic `"FDAT"`（0x25aa `strncmp(...,"FDAT",4)`）并返回偏移【已验】——SD/介质侧入口。

### 3.2 `crypter.elf`（= 一代的 "exec_write_firm" 对应物）里的全部校验，按代码顺序【已验】

| # | 地址 | 校验内容 | 覆盖字节 | 失败码 |
|---|---|---|---|---|
|1|0xb340–0xb384|UFU 记录走链：BE u32 size 在 `+0`，`memcmp(+4,"FDAT",4)`，游标 `r5 += 8 + size`|容器记录头|0x30012 (CryptFileInputUpdaterManager.cpp:0xab)|
|2|0xae60 `CrcChecker`|取流末端 12B：`memcmp(sp+8,"DEND",4)`；`sp+0xc..0xf` 拼 BE u32 与自算 CRC 比较；打印 `"calc_crc:0x%lx, getHd_crc:0x%lx"`(CrcChecker.cpp:0x59)|**整个容器 [0, X)**，X=`0xb00a/0xb00c` 处算出的 `字段+8+r5`（= DEND 记录位置，即 filesize−12）→ 含 FDAT 记录及其尾 272B|—|
|3|0xae00/0xadb0|CRC-32 实现：`eors r3,r5` + `ldrne r5,[0xadf8]=0xedb88320`，0x1000B 分块读流，末尾 `mvns`|同上|—|
|4|0xe0ec–0xe104|帧校验：从 `this+0x5a` 起累加 511 个 LE u16（`movw r1,0x3fe`）`uxth` 后比对；0xe106–0xe110 `ldrh [r0,0x5a]; lsrs #0xf` = **末块位(bit15)**|每个 1024B 帧的 2..1023|—|
|5|0xe06a–0xe090|`memcpy(16) → Dec_Scramble → memcpy 回`，长度 `ldr.w r3,[r5,0x458]`；长度&0xf≠0 → **0x30002**|帧流（ECB, key=KeyArray 前 16B）|0x30002|
|6|0xbf1c–0xbf76|头解析：`memcmp(hdr,"UDTRFIRM",8)`；`memcmp(hdr+0xc,"0100",4)`；**CRC32(poly 0xEDB88320) 覆盖 hdr[12..0x200)**（`movs r3,0xc … cmp r3,0x200`，逐字节 8 轮），`mvns` 后与 `hdr+8` 处存值（`add r0,r4,8; bl 0xbd8c`）比较；`mov.w r0,0x200`@0xbf12 = 头长 512|**头 [12,512)**，存值在 +8|—|
|7|0xbde4–0xbeb2|机型/ chassis：`FileHandler::Open("/tmp_updater/updater/bodyfs/config/chassis")` 与 `Open("/root/chassis")`（缺文件→0x30007, BaseBodyLoaderModule.cpp:0x1c3），`ReadAll` 各 16B，长度相等再 `memcmp`（0x10）|两个 ASCII 串（本包都是 `CXD90045`）|0x30007|
|8|0xc06a / 0xc1e0 / 0xc4c2–0xc4ee|取体：写 `/tmp_updater/updater/bodyimg`；比 `/usr/bin/udtrbody.bin`(0xc4c8)；`mov.w r2,0x401` 比较|body 文件|0x30010 / 0x30002|
|9|0xd6d4–0xdd46|`CurrentFirmware`：挂 `/dev/nflasha1`(0xd750)/`/dev/nflasha2`(0xd6dc) 到 `/tmp_updater/updater/current`，`Mode6FlagFile/Mode3FlagFile/ModeFlagFile` 构造(0xdd06/0xdd00/0xdd04) + `IsValid/Delete`；0xdee0 ModelFile/RegionFile `GetValue` 取本机 model/region|旗标文件 mode/mode3/mode6|0x3000f|
|10|0xc556–0xc56a|`/dev/loop0`+`cramfs`(0xf765/0xf783) 环挂，`dlopen bodylib/libupdaterbody.so` → `GetBody`/`ReleaseBody`|—|—|

→ 表里 **1..10 没有任何一步是签名校验**；覆盖到的字节只有：容器 CRC（可重算）、帧 u16 校验和（可重算）、头 CRC32 [12,512)（可重算）、chassis 字符串（可改）。

### 3.3 门禁与"验签/校验"的先后顺序【已验 + 推断】

```
(A) udtr_ufp_init: Dec_ScrambleInit + 读 dat2/dat3/dat4 → set_*        @0x20e8   [装载本机身份]
(B) 收首块 → ECB 解 512B 头 → 取 mode/version/model/region + modeType'U'/'O' @0x1b5a-0x1b96
(C) 门禁 model/region(/version)                                        @0x127c   ← 报错 0x140/0x141/0x142
      └ 失败即 0x101 应答、b 0x1e92，不写任何东西                      @0x1c22-0x1c50
(D) 挂 tmpfs → 写 /tmp_updater/Firm.dat                                @0x26dc-0x2706
(E) crypter.elf：DEND CRC → 帧校验 → ECB → 头 CRC32 → chassis → 取体   @0xb340…0xc56a
(F) libupdaterbody.so::Execute → 解 tar → 写分区 → endupdate.sh（.sum CRC 在写之后再算一遍）
```
即 **机型/区域/版本门禁在写分区之前**；(E) 的 CRC 类校验也在写分区之前；(F) 里 `us_crc32sum.sh` 是"写后回读校验"（序号 0700 写 → 0701 校，见 UPDATER_ANALYSIS §3.2）。

### 3.4 有没有"模式相关分支跳过验签"【已验】
一代没有验签可跳过；能跳过的只有 **版本比较**：
- `verskip==1` ⇔ 包头 `modeType=='O'`（0x1b8c/0x1c00）或 IPC 应答==1（0x1bf4）；`0x12e4 beq` 直接返回 1。
- 之后 `up.sh` 的参数也因此不同：`verskip=1 → "ver"`（0x1fc0→0x1fc8），否则 `"user"`；`"ms"`（@0xaad0）用于 MSCRYPT 出错收尾。
- `acsy_flag==1`（0x128c）不是跳过门禁，而是**改从 IPC 现取本机 model/region/version**。
- 脚本侧模式常量 `config/common.src:29-33`：`MODE_USER=0 / PROD=1 / SERVICE=2 / MINOR=3 / VERSKIP=6`；`us_mkfs.sh/endupdate.sh` 按模式决定是否重建分区（`$USER|$SERVICE|$MINOR|$MSCRYPT` 分支，`endupdate.sh:59`）。**没有哪个模式能跳过 model/region 比较。**

## 4. 能不能 patch（"改 updater body 里的验签指令"）

1. **FDAT 里 updater body 的位置**【已验，FIRMWARE_MOD §1.3】：明文 512B 头 +0x200 起，CRAMFS 143,360 B（fs[0] `'U'` offset 512 size 143360）。
2. **一代 body 被什么覆盖**：body 在 CBC 帧区里（块0 前 512B ECB，其余含 body 全部 AES-256-CBC(key_cxd90045, IV=尾 16B)）→ 改 body 必然改变密文；若尾 256 B 真是签名，**签名覆盖它（自指）** ⇒ **改 body 破签名**【推断，基于 body 位于 CBC 区这一实测事实】。
3. **验签代码本身不在签名覆盖范围内吗？** —— 一代的"验签位置"根本不存在：(E) 那串 CRC 全在 `crypter.elf`（usr 分区 `/usr/bin/crypter.elf`），**不在 FDAT 的 body 里**，也**不在 FDAT 之外**——它在 `firmware.tar` 的 `0700_part_image/dev/nflasha15` 镜像里，即**在签名区之内**【已验(路径+FDAT 布局)】。所以：
   - 在**包内** patch `crypter.elf`：改动落在 CBC 区 → 若签名存在则同样破坏签名【推断】。
   - 在**相机上就地** patch `/usr/bin/crypter.elf`（服务通道/Jiritsu 写文件，见 FIRMWARE_MOD 路线 B）：**不动 .dat**，可以把 DEND CRC / 头 CRC / chassis 三道检查一并废掉【推断，指令级可定位：0xae60、0xbf1c、0xbde4】。
4. **body 里的 `nwu/uincomp` 之类旗标**（`/tmp_updater/not_write_file/nwu` 等，UPDATER_ANALYSIS §6）是运行时开关，不是校验，仍可用【已验(字符串+调用点)】。

**关键分歧点（与 A7C II 报告）**：A7C II 说"验签在 `libupdaterufp.so::UFPDecryptorModule::exec_write_firm@0x12f50`，验完再写"。
一代同名库里对应的写入函数是 `udtr_write_firm_from_media@0x2668` + `stm_system("/usr/bin/crypter.elf","/tmp_updater/Firm.dat")`，
里面**没有任何验签**，且 `0x12f50` 附近在一代只有一般代码（一代 `libupdaterufp.so` 全文只有 0xe8c–0x27ac）【已验】。

## 5. FDAT 尾 272 B（16 B IV + 256 B）在代码里怎么被读【已验(否定)】

- **没有任何一代工件读这 272 B**：`crypter.elf` 反汇编里 `0x110` 出现 **0 次**、`0x100` 仅 1 次（`0xade2 cmp.w r2,0x100` = CRC 循环计数）；`libupdaterufp.so` 里的 `#0x110` 只是栈帧偏移（`0x191a add.w r2,r7,#0x110` / `0x193a ldr.w r1,[r7,#0x110]`），与尾区无关【已验】。
- 唯一被"从文件尾取数"的地方是 **`CrcChecker` 取末尾 12 B**（DEND 记录，见 §3.2 #2）——**只覆盖 UFU 外层容器的 DEND CRC，不是那 256 B**。
- FDAT 帧循环靠 **bit15 末块位**结束（0xe106 `ldrh [r0,0x5a]; lsrs #0xf`）→ **帧流之后的 272 B 从不被解析**【已验】。
- IV 用在哪：userspace 里**没有 CBC 实现**（`Dec_Scramble` 只有 ECB，key=`KeyArray@0x8830` = `e3b0c442 98fc1c14 9afbf4c8 996fb924 | 27ae41e4…b855` = SHA-256("") 前 16B【已验】）。
  全树字节扫描（含 240MB 的 `nflasha15` 原始镜像、`nflasha3/5/7`、initrd、av-cam.bin 等）结果：
  `key_cxd90045`(C1AA8F7C…D303E06B) **0 命中**；`SHA256("")` 前 16B 只在 `libupdatertalk.so` 命中；`-----BEGIN`/DER RSA-2048 前缀 (`30 82 01 22 00 30 0d 06 09 2a86 4886f70d01 01`) **只命中网络栈**（libcrypto/libcurl/`share/network/cert/certification.pem`）；`RSA`/`ECDSA` 字符串只在 libcrypto/libssl/openssl/wpa/ipsec【已验】。
  → **AES-256-CBC 的 key/IV 不在文件系统里**；最可能是硬件 DMA 解密：initrd 里带 **`kmod/ldec.ko`**（导出 `boss_hw_ldec_set/process/wait`，参数 `srclen/dst_phys/ch`，`ldec_ioctl`+`dmac` 通道）与 `lld.ko/dmac.ko`【已验符号级存在】，**推断**它承担 body 的 CBC 解密（key 来自 OTP/MPR=nflasha4，`endupdate.sh:94` 还会擦 nflasha4）。
  → 256 B 若是签名，**它更像被硬件/loader（ldr_drv.bin / WBI=nflasha5 / BootROM）侧消费**，而不是被 userspace 验【推断】。256B 与 RSA-2048 相符（ECDSA P-256 只 64B）【已验：长度算术】。

## 6. 还缺什么证据（一代要钉死的三件事）

1. **nflasha1（Updater 分区）的镜像**：本包只刷 nflasha3/5/7/15（`part_image.sum`），**不含 nflasha1**，
   而 crypter.elf 的 `CurrentFirmware` 明确读写 nflasha1（0xd750）。要判"256 B 到底验不验"，必须从**在用相机**dd 出 nflasha1（7.94MB，partinf.conf 第 1 条 `0x10000,0x7F0000`）与 loader 区（nflashaB0）。【未定 —— 最大缺口】
2. **`ldec.ko`/`lld.ko` 的 ioctl 参数结构**（`udif_ldec`）→ 谁能指定 key/IV；若 key/IV 由 userspace 传入，则 key 必然在某处（我们扫不到 ⇒ 只能来自 IPC/OTP），从而确认硬件解密路线。【未定】
3. **实机一次"失败实验"的返回值**（最便宜的判据）：改包只动 CBC 区里 1 个字节（例如 body 里 1 字节，保持 272 B 原样）→ 若相机在 (E) 之前/之中报 `calc_crc/getHd_crc` 不符或 0x3000x ⇒ 校验只有 CRC（可重算 ⇒ 自制包可行）；若报**别的/无日志的硬失败** ⇒ 有 CRC 之外的签名层。已有的两个试验包（`FIRMWARE_MOD §1.5`，只改 ECB 头区，差 36 B）能顺带回答"门禁 vs 签名谁先报错"。

---
### 复现命令
```bash
cd firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked
rabin2 -i lib/libupdaterufp.so; rabin2 -E lib/libupdaterufp.so          # 无 RSA/verify
python3 ../../../../../../tools/ufpdis.py lib/libupdaterufp.so 0xe8c 0x27ac --mode thumb   # 门禁/收块/写盘全序列
r2 -q -a arm -b 4 -e scr.color=0 -c 'aaa; pd 0x1e54 @ 0xab40' bin/crypter.elf > /tmp/crypter_pd.txt
# 关键锚点：0xae60(DEND CRC) 0xbf1c(头 CRC32 poly 0xedb88320, hdr[12,0x200)) 0xbde4(chassis)
#           0xe0ec(帧 u16 校验和) 0xe106(bit15 末块) 0xe06a–0xe090(ECB 16B/块) 0xc556(loop mount+dlopen)
python3 - <<'EOF'   # 全树密钥/公钥扫描（key_cxd90045 = 0 命中；RSA/ECDSA 只在网络栈）
... pats = {'key_cxd90045': bytes.fromhex('C1AA8F7C46341FFED15589FC8170A6BB5925E85F6282D7F95BA3FDF5D303E06B'),
             'sha256empty': bytes.fromhex('e3b0c44298fc1c149afbf4c8996fb924'),
             'DER2048': bytes.fromhex('3082012200300d06092a864886f70d0101'), 'BEGIN': b'-----BEGIN'}
EOF
```

---
## ★更正（2025-10-24，来自本机 a1 提取件的重扫）：2.00 的 USER 路径**确实**引用 RSA 验签
之前"`sauu` 是死代码 / `sauu` 里 0 次 `RSA_verify@plt` / 2.00 没有 libcrypto"的结论**不可靠**，原因是解析器把 ELF32 正常的
`e_shentsize = 40 (0x28)` 当成"怪异补齐"，于是根本没解析到 `.dynsym`/`.dynamic`（工具 bug，不是样本的特殊性）。
用 `tools/elfdyn.py`（按 10 字段的 ELF32 section header 解析）重扫 `work/l1-camera/a1_initrd/`：

| 模块 | 引用的加密 API | NEEDED libcrypto |
|---|---|---|
| `usr/bin/sauu` | `RSA_verify`, `PEM_read_RSA_PUBKEY`, `SHA1_Init/Update/Final`, `SHA256` | **`libcrypto.so.1.1`** |
| `usr/lib/libsdfileinputupdaterapi.so` | 同上 + `Updater::SignatureVerification::{VerifySignature,verifyKey}` | **`libcrypto.so.1.1`** |
| `usr/lib/libInfraSKD.so` | `EVP_aes_256_cbc`/`EVP_Cipher*`（对称，对应 mode5 解密） | YES |
| `usr/lib/libsencore.so` | `SHA256` | YES |
| `lib/libcrypto.so.1.1` | （导出 1200 个符号，含全部 RSA/PEM） | — |

- **updater initrd（真机 a1 里的）自带 `lib/libcrypto.so.1.1`(1,459,464 B) 与 `lib/libssl.so.1.1`(344,512 B)**（还有 `libcrypto.so`/`.so.1` 符号链接）。⇒ 2.00 的 updater 阶段有完整 OpenSSL 1.1。
- `etc/VerificationKey.pem`（451 B，`BEGIN PUBLIC KEY`，RSA-2048）被 **`sauu` 与 `libsdfileinputupdaterapi.so` 两者**引用。
- 而 `execute_ufp.sh`（见 notes/qemu.md §15）在 **USER / MINOR(`sauu -m`) / VERSKIP(`sauu -s`) / SERVICE** 分支里跑的就是 `LD_PRELOAD=/usr/lib/libSysDef.so sauu`；只有 **MODE_MSCRYPT(5)** 走 `sdfileinput.elf`（并 `insmod mcmn_drv.ko mmc_drv.ko` = 插存储卡）后 `touch /setting/updater/MediaUpdateCompleteFlag`。
⇒ 结论方向变化：**验签在 2.00 的 USER 路径上是"存在"的**；能不能绕过取决于**控制流**（是否无条件、结果是否致命、签名覆盖哪些字节）——见 `work/sauu/SIG_RECHECK_200.md`（待做）。
⇒ 但有一个此前没注意的事实对我们有利：**验签者本身（`/etc/VerificationKey.pem`、`/usr/bin/sauu`）都在 a1 的 initrd 里**，而 a1 是我们已有完整 dump、且技术上可重写的分区。
