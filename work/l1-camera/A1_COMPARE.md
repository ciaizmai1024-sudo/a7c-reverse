# 机身 a1（2.00 时代）vs 出厂 2.03 包内 a1 —— 完整离线比对

输入（只读，未碰 USB/相机）：
- 机身：`work/l1-camera/nflasha1.bin` 8,323,072 B，sha256 `82e1b199a8e8…9b79a1a`，md5 `25fa4d8da17893d002a5b5d2f46dd9c8`
  （与 `SHA256SUMS` 里 `nflasha1.bin` / `nflasha1.bin.r1` 两条一致；两次拉回相同）
- 参照：`work/v203/nflasha1_203.bin` 8,323,072 B，sha256 `c9040270ad88…21c093`，md5 `6dca7ec458fad4a2903eb4ff6aebc3ef`
工具（本次新写，零依赖 python3，纯离线）：`work/l1-camera/fat12.py`（FAT12 手写解析/BPB/目录/簇链/提取）、
`work/l1-camera/tscan.py`、`work/l1-camera/armdis.py`（capstone Thumb2 + objdump `@plt` 标签关联）。
CRAMFS 用已有 `work/v203/dump_body.py`（vendored `refs/fwtool.py`）—— 与 2.03 manifest 同一把尺子。
本机没有 mtools / fsck.vfat / unsquashfs / extract-cram（只有 bsdtar，但本次未用）。

---

## 1) BPB / FAT 类型（手写 FAT12 解析，两镜像逐字段相同）

| 字段 | 机身 a1 | 2.03 a1 |
|---|---|---|
| jump / OEM | `eb 3c 90` / `mkfs.fat` | 同 |
| bytes/sector | 512 | 512 |
| sectors/cluster | **32**（=1 簇 1024 B） | 32 |
| reserved sectors | 1 | 1 |
| FAT copies | 2 | 2 |
| root dir entries | 512（16,384 B） | 512 |
| sectors/FAT | 32 | 32 |
| sectors/track / heads | 32 / 64 | 32 / 64 |
| media | 0xf8 | 0xf8 |
| hidden sectors | 0 | 0 |
| total sectors (16bit @0x13) | **16256** | 16256 |
| 数据区总簇数 | **505**（(16256−1−64−32)/32） | 505 |
| FAT 类型判定 | 505 < 4085 ⇒ **FAT12** | FAT12 |
| 布局 | FAT@0x200/0x4200，根目录@0x8200，数据@0xc200 | 同 |
| `0x1fe` | `55 aa`（无 MBR，整卷就是一个 FAT 卷） | 同 |
| boot sector 差异 | **只有 4 字节**：`0x27-0x2a` 卷标序列号 `79 54 21 38`(body) vs `a1 7a 48 87`(203) | — |

★ **两份 FAT 副本逐字节相同**（body 内 0x200-0x41FF vs 0x4200-0x81FF 差异 0 字节；203 同）⇒ 之前笔记说的
"0x4200-0x45ff FAT 链只差 4 个 EOF 簇位"其实是**两个镜像之间**的 FAT 差，不是机身卷内部不一致。机身 a1 卷是干净的。
FAT1↔FAT2 之间差异的字节（机身 vs 203）：`FAT+0x1bd,0x1be`（簇 297：机身 `0xfff` EOF / 203 `0x12a`）、
`0x1c9,0x1ca`（簇 301 同类）、`0x259…0x26b`（= **dat2/dat3/p1chksum 的簇 404/405/406 与 203 的 410-412 链**）。

时间戳（ Sony 驱动/mkfs 用**原始 hex 当 BCD** 的非标准写法，`0x50ae` = 时 0x14=20、分 0x0a=10、秒 0x0e→10+10=20s… 见下）：
- 机身：`boot/`、`p1chksum` 及 boot/ 里 4 个文件 = 日期 `0x83c5` → **2020-05-14**，时间 `0x50ae` → **16:30:10**（照抄 mkfs 默认）
  与 boot sector 序列号 `0x4e382154`（=2020-05-14 16:30:10 epoch）一致 ⇒ **出厂 mkfs 时刻**。
- 203：日期 `0x840a` → **2025-12-25**，时间 `0x599b` → **01:16:27**，序列号 `0x4e87487a`（=2025-12-25 01:16:42）⇒ 打包时刻（2.03 包重打）。
- `dat2`/`dat3`：日期 `0x81a8` → **2011-01-01**，时间 `0x013e` → 00:09:12，序列号字段 `0x3e21213e`（=2003-01-01）⇒ 运行期由相机驱动写，日期是它的默认起点。

## 2) 目录条目（原始字节已核，见上表偏移）

根目录（0x8200，机身）：
| 名字 | 起始簇 | 簇链长 | 大小 | 属性 | 条目偏移 |
|---|---|---|---|---|---|
| `boot`(LFN `boot`) | 3 | 1 | 0(dir) | 0x10 | 0x8240 |
| `p1chksum`(LFN) | 404 | 1 | **105** | 0x20 | 0x8260 |
| `dat2`（**无 LFN**） | 405 | 1 | **4** | 0x01 | 0x82a0 |
| `dat3`（**无 LFN**） | 406 | 1 | **4** | 0x00 | 0x82e0 |

根目录（0x8200，203）：只有 `boot`(cl3) 与 `p1chksum`(**cl412**,105 B) ⇒ dat2/dat3 是机身运行期新增。

`boot/` 子目录（簇 3，偏移 0x10200，两边各 4 个文件；名字都是 1 条 LFN + 1 条 SFN）：
| 文件 | 机身 簇/链长/大小 | 203 簇/链长/大小 |
|---|---|---|
| `initrd.img` | 4 / **294** / **4,812,800** | 4 / **302** / **4,943,872** |
| `vmlinux.bin` | 298 / 104 / **1,697,076** | 306 / 104 / **1,701,156** |
| `kemco.txt` | 402 / 1 / 1,062 | 410 / 1 / 1,062 |
| `loadaddr.txt` | 403 / 1 / 33 | 411 / 1 / 33 |

FN 侧怪癖（记档）：LFN 条目布局是**标准**的（[1:11]=前 5 字符、[14:26]、[28:32]），但 `[12]`(ord) 不是 0x01/0x41（boot/ 里是 0x00，boot/ 里那 4 个是 0x0F），`[13]`(checksum) 也不是微软校验和（例：`INITRD  IMG` 的 MS 校验和 0xc8，条目里写 0x18）。名字仍可从 LFN 完整重建（`initrd.img`/`vmlinux.bin`/`kemco.txt`/`loadaddr.txt`）。`dat2/dat3` 完全没有 LFN。

## 3) 提取产物（`work/l1-camera/a1_extracted/`，按 FAT 簇链重建，截到目录项 size）

| 文件 | 长度 | sha256 | md5 |
|---|---|---|---|
| `boot/vmlinux.bin` | 1,697,076 | `07cb36c89c68f999ce51b5b4be97aa9670f334416353102309ec8e019107f2b3` | **`a6d9d7695e66a1301ca8f2a29eb42aea`** |
| `boot/initrd.img` | 4,812,800 | `5a7a90a3aed3fa9328cf5579f46cc01809f019225d64c3a64a7d0b21432e7200` | **`0f00bf40c7d13f84cf9abf8c068c5f7a`** |
| `boot/kemco.txt` | 1,062 | `5bdcc4d98b9216a9128f62fa9b845e1e04c8c9d931fd6d9c4ddcab8d57995f42` | `1c5c0bab64c41162fe3af306815a0867` |
| `boot/loadaddr.txt` | 33 | `a55bb7c1ef670cad21301679f75412bf2f81bfe713c3a83acd4b2b457523200d` | `7911fe23c7d2327231d399f4ab98ea17` |
| `p1chksum` | 105 | `86ba9d3282e2d85d262797aa61cc7b4fab711085207c24d2448696e98e89543d` | `668cd114cd3fbffddaf6919da56a70e4` |
| `dat2` | 4 | `a97d57cedf3e2b64224f09e9c5ef858c2ccf8af43a4a3ed916386d15bff6b0c8` | `a3cb895ccadeb0454cc28d968dd0a4e5` |
| `dat3` | 4 | `df3f619804a92fdb4057192dc43dd748ea778adc52bc498ce80524c014b81119` | `f1d3ff8443297732862df21dc4e57262` |

2.03 参照（`a1_extracted_203/`）：vmlinux `49a2c6f8…` md5 **`0dcd3b9177c38b610dcd0afdfba57def`**；initrd `040a7d76…` md5 **`bb50bfb5261f161a9f49bd351e5fddfb`**；kemco `79d71ee7…`；loadaddr 与机身**逐字节相同**；p1chksum sha256 `4feddcce…`。

## 4) `p1chksum` 验证 ★ 机身 boot 未被改过

机身 a1 的 `p1chksum`（105 B，簇 404 @0x654200）**原样**：
```
a6d9d7695e66a1301ca8f2a29eb42aea  ./boot/vmlinux.bin
0f00bf40c7d13f84cf9abf8c068c5f7a  ./boot/initrd.img
```
实算：vmlinux.bin md5 = `a6d9d769…aea` ✓；initrd.img md5 = `0f00bf40…f7a` ✓ ⇒ **两条完全吻合**。
⇒ 机身 a1 的 `boot/vmlinux.bin` + `boot/initrd.img` 与刷入时（出厂）**一致，没有被事后改过**（也没有部分写坏）。
格式与 2.03 的 p1chksum **完全一致**（同为 105 B、同 `<32hex><空格><空格>./boot/…\n` 两行、md5sum 兼容；只是数值不同：
203 的是 `0dcd3b91…` / `bb50bfb5…`）。⇒ p1chksum 是**可直接照抄格式重写**的文件，不含机型专有内容。
另外：机身 a1 initrd 全树（621 条目）**0 处引用 `p1chksum`**（与 §21.3 结论一致）⇒ 读它的是更早的阶段（loader/EXBL）。

## 5) `dat2` / `dat3` 解值

| 文件 | 原始 4 字节 | 小端 LE | 大端 BE | 判读 |
|---|---|---|---|---|
| `dat2` | `19 00 03 91` | **`0x91030019`** = 2,432,892,953 | `0x19000391` = 419,431,313 | LE 与已知 **model id `0x91030019`**（A7C，`ud_datcnv.elf`/笔记 §21.1）吻合 ⇒ **小端** |
| `dat3` | `00 00 00 00` | `0x00000000` | `0x00000000` | 两种读法都是 0 ⇒ 机身这台 region=0（无区码/未写区码）。之前笔记说"dat2/3 sha 相同"是**错的**（dat3 sha256 `df3f6198…` = 四个零字节） |

## 6) CRAMFS（`boot/initrd.img`）解开 + 与 2.03 逐文件比

机身 initrd.img = CRAMFS：超级块 `45 3d cd 28`，size 字段 `0x00497000`=4,812,800，`Compressed ROMFS`，edition `0x09eb`，blocks `0x026d`。
解开到 `work/l1-camera/a1_initrd/`，manifest `work/l1-camera/a1_initrd_manifest.tsv`（**621 条目 / 217 个非空文件**，与 2.03 manifest 同一格式）。

与 `work/v203/a1_initrd_manifest.tsv`（625 条目）对比：
- 两边都有：**608**；其中**字节完全相同**：**157 个文件** + 404 个目录/占位条目
- **不同**：**47 个文件**（清单在 `work/l1-camera/a1_initrd_diff.txt`）：`/version.txt`、`/usr/bin/{sauu,mf,crypter.elf,UdtrMain.sh,common.src,execute_ufp.sh,ulogio.elf}`、`/usr/kmod/*.ko`（34 个里的多数）、`/usr/lib/{libInfraFsys,libInfraMediaCommon,libMWF,libSysDef,libosal_ulogio,libsdfileinputupdaterapi,sencore,testcmd,ul_xml,updater0604}.so`
- 只在 2.00：13 条 = `/lib/{libcrypto*,libssl*,libstdc++*,libssp*,libgcc_s.so.1}`；只在 2.03：17 条 = 同一批库挪到 `/usr/lib/` + 新增 `/lib/libuuid*`、`/usr/lib/libuuid*`、`/usr/lib/libgcc_s.so.1`、**`/root/IAMSIGNENABLED`（0 B）**
  ⇒ 13/13 里除 `libgcc_s.so.1`（2.00 35,324 B `3078081f` vs 2.03 252,717 B `71738aa5`）外**内容逐字节相同**，只是 `/lib` → `/usr/lib` 挪位置。

关键文件（机身 2.00 vs 2.03）：
| 路径 | 2.00（机身） | 2.03 | 结论 |
|---|---|---|---|
| `/usr/bin/sauu` | 84,428 `5e345c865f96` | 84,428 `d79af0e6958e` | **DIFF**（但见 §7：节级比对） |
| `/usr/bin/mf` | 36,604 `6fc47717ea74` | 39,960 `8d99f909b091` | **DIFF**（3.3 KB 差 = 验签代码） |
| `/usr/bin/crypter.elf` | 43,280 `5ebb6d9cb2cb` | 43,280 `28c56467ee40` | **DIFF**（但**全部 section 逐字节相同**，只有 ELF 头/`e_shoff` 类元数据不同） |
| `/usr/bin/up.sh` | 5,008 `03a70fd0d0ef` | 同 | **SAME** |
| `/usr/bin/UdtrMain.sh` | 2,041 `6e78519b09c0` | 2,174 `001220e5fa3b` | **DIFF**（见下） |
| `/usr/bin/execute_ufp.sh` | 1,943 `202e3bd599f9` | 2,030 `274112942c49` | **DIFF**（只差 1 行：2.03 多 `insmod ms_drv.ko`） |
| `/usr/bin/sen.elf` | 22,604 `c257e5fc9a7f` | 同 | **SAME** |
| `/usr/bin/is_valid_boot.sh` | 483 `51a9aec51413` | 同 | **SAME** |
| `/usr/bin/sdfileinput.elf` | 49,536 `3bb68f04e7eb` | 同 | **SAME** |
| `/usr/bin/ud_datcnv.elf` | 5,892 `2b3b085e4c36` | 同 | **SAME** |
| `/etc/VerificationKey.pem` | 451 `79be4fb50a65` | 同 | **SAME**（RSA-2048 `BEGIN PUBLIC KEY`，`openssl rsa -pubin` 可解） |
| `/usr/lib/libsdfileinputupdaterapi.so` | 82,788 `c34404ca1b8a` | 82,788 `373f3a119047` | **DIFF（仅 4 字节！见 §7）** |
| `/usr/lib/libupdater0604.so` | 21,552 `178525afe0ca` | 22,536 `0e2cec62ca3f` | **DIFF（语义差，见 §7）** |
| `/usr/lib/libupdatercommon.so` / `libupdatertalk.so` / `libupdaterufunc.so` | `a6b6bf200dad` / `5a22e281c8ae` / `61a01288a888` | 同 | **SAME** |
| `/version.txt` | `100.101.014` | `100.110.035` | 机身=2.00 版链，203=2.03 版链（与 `cfg__version.txt`=`39119_05.2021111501` 的 2.00 侧自洽） |

`UdtrMain.sh` 实质差（2.00 机身 → 2.03）：
```
13a14,16 >  #Forced Production?  test -f /setting/updater/mode || { echo "[W] Forced Prod Mode."; touch /ramdsk/mode1; return $MODE_PROD; }
50c53      < test $MODE_PROD -eq $cur_mode && ud_cons.elf on      (机身 2.00：PROD 模式**总是**开串口控制台)
           > test -f /root/IAMLDUDWRT     && ud_cons.elf on      (2.03：只有 LDUDWRT 才开)
```
⇒ **机身 2.00 的 a1 在 PROD（官方 .dat 刷入）模式下会自动 `ud_cons.elf on`**，这比 2.03 更好（做 L0' 探针时不用额外放 `/setting/updater/debug` 就有更新模式串口）。

## 7) ★★ 验签者版本判定（机身 2.00 版 a1 里到底谁验 RSA）

字串级（`grep -a` 偏移，2.00 = 机身）：
| 对象 | 2.00（机身） | 2.03 |
|---|---|---|
| `/usr/bin/sauu` 84,428 B | `RSA_verify`@11183、`PEM_read_RSA_PUBKEY`@11194（dynsym）、`SignatureVerification`@65439/65501、`/etc/VerificationKey.pem`@66249、`Signature Verification Error`@66291、`verifyKey`@65627；`nm -D` 有 `U RSA_verify@OPENSSL_1_1_0`/`U PEM_read_RSA_PUBKEY@OPENSSL_1_1_0`/`U RSA_free`；DT_NEEDED 含 `libcrypto.so.1.1` | **完全同样的偏移与 dynsym** |
| `/usr/bin/mf` | **0 命中**：无 libcrypto/libssl（DT_NEEDED 里也没有）、dynsym 无 RSA/PEM、无 `SignatureVerification`/`VerificationKey.pem` 字串 | 有：`RSA_verify`@9354、`PEM_read_RSA_PUBKEY`@9365、`/etc/VerificationKey.pem`@30150、`Signature Verification Error`@30192，DT_NEEDED 含 `libcrypto.so.1.1`/`libssl.so.1.1`/`libInfraSKD.so` |
| `/usr/bin/crypter.elf` | 0 命中；不链 libcrypto；dlopen `/tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so` | 同（0 命中） |
| `/usr/lib/libsdfileinputupdaterapi.so` | **有完整验签实现**：导出 `_ZN7Updater21SignatureVerification9verifyKeyEPKc`(0xdbcc)、`…15VerifySignatureENS_13verify_info_tEPKc`(0xdd6c)、`_ZN7Updater15DecryptorModule9verifySumEv`(0x10228)；`.rodata` 里 `SignatureVerification.cpp`@0x11587、`Signature Verification Error`@0x110f0、`"signature"`@0x115c1（该库 .rodata 的 vaddr==file offset，上面即 vaddr） | **`.rodata`/`.plt` 逐字节相同**；见下 |
| `/usr/lib/libupdater0604.so` | **0 命中**（无 `SIGN`/`IAMSIGN`/`VERIFY_SIGN` 任何字串） | 有 `UD_GET_VERIFY_SIGN`、`/tmp_updater/root/IAMSIGNENABLED`、`/tmp_updater/root/IAMSIGNDISABLED`@0x4d2b（挂载 a1/cramfs 后 stat 标志文件） |

指令级（capstone Thumb2 + objdump `@plt` 标签，脚本 `work/l1-camera/tscan.py`、`armdis.py`）：
- `libsdfileinputupdaterapi.so`：`VerifySignature(0xdd6c)` 里 **实打实** `bl PEM_read_RSA_PUBKEY@plt`(0xdddc)、`bl SHA256@plt`(0xddf8)、**`bl RSA_verify@plt`(0xde0c)**、`bl RSA_free@plt`(0xde32)；调用者只有两个：
  `0xcc32 ← _ZN7Updater17SDDecryptorModule13execWriteFirmEv`（SD 卡媒体更新，`sdfileinput.elf` 走这条）
  `0xc69a ← _ZN7Updater18UFPDecryptorModule15execWriteFirmEv`（USB/UFP 侧的 decryptor 模块）。
  **两版** `VerifySignature`+`verifyKey` 的函数字节**完全相同**；整库只有 **4 字节**不同（`.text+0x194e` 在 `BufferManager::Initialize`、`.text+0x2346/0x2376` 在 `SDFileManager::getFirmwarePath`，都是立即数 `0x500→0x45/0x6d03→0x6d43/0x6700→0x6740`），`.rodata`（含所有验签字串）**逐字节相同**。
- `sauu`（两版）：`.plt/.dynsym/.rodata/.ARM.exidx` **逐字节相同**；`.text` 差 4,583 字节 / 272 段（重编译位移），`.rodata` 差 256 字节但那些位置全是 **函数指针/vtable/异常表**（如 `0x1ed8` 处 `0xe74d→0xe86d`）。`/etc/VerificationKey.pem` 的字面量池在**两版同一个 vaddr 0x10cb4**，引用它的代码块 0x10c40-0x10c76 **逐字节相同**：
  ```
  0x10c64 movs r1,#0 ; 0x10c66 ldr r2,[pc,#0x3c](="/etc/VerificationKey.pem") ; 0x10c68 movs r3,#0x97 ; 0x10c6a ldr r0,[pc,#0x74] ; 0x10c6c blx printf
  ```
  ⇒ 那是 `printf("…%s:%d,…")` 的 **`__FILE__`/行号 151(0x97)**，即 `SignatureVerification.cpp:151` 的日志 ⇒ **sauu 只是把该类链接进来并带日志**。
  **两版 sauu 全 .text 里没有任何 `bl`/`b` 指向 `RSA_verify@plt`(0xb60c)/`PEM_read_RSA_PUBKEY@plt`(0xbb70)/`RSA_free@plt`(0xbae4)，也没有任何字面量/pool 指向这些 stub（0 命中）** ⇒ sauu 自己不做 RSA 验签（2.03 也不做）。
⇒ **判定（这台机身当前生效的验签者）**：
1. 与 2.03 一样，真正执行 `RSA_verify`+`/etc/VerificationKey.pem` 的是 **`/usr/lib/libsdfileinputupdaterapi.so`**（2.00 机身里就在，且和 2.03 只差 4 字节），入口只有 `sdfileinput.elf`（= `execute_ufp.sh` 的 **MSCRYPT**/SD 卡路径，`sdfileinput.elf` 两版 SAME）和它的 `UFPDecryptorModule::execWriteFirm`。
2. **`sauu` 不是验签者**（2.00 与 2.03 都无调用点）⇒ **修正 §21.2/§21.6 的"sauu 验 272 B 尾"结论**：`sauu` 只是把 `SignatureVerification` 类一起编进去了（还带 `SignatureVerification.cpp` 字串与 PEM 路径日志），真正的调用在 `libsdfileinputupdaterapi.so`，且只挂在 **SD 卡媒体更新 / UFP decryptor** 两条路上。
3. **2.00 有 / 2.03 新增的部分**：`mf`（工厂工具）2.00 **没有**验签（没链 libcrypto），2.03 才加上；`libupdater0604.so` 2.00 **没有** `UD_GET_VERIFY_SIGN`/`IAMSIGNENABLED`/`IAMSIGNDISABLED`，2.03 才有；`/root/IAMSIGNENABLED` 标志文件只在 2.03 的 a1 里；整个 2.00 官方包解密体 `work/v203/full_dec_200.bin` 对 `IAMSIGN`/`VERIFY_SIGN` **0 命中**（2.03 的 `full_dec.bin` 命中 1 处）。
   ⇒ **"签名开关/门禁"这套东西是 2.03 才引入的**；这台机身（2.00 a1 + 2.00 body）的运行系统与更新模式里**没有**"读 a1 里的 IAMSIGNENABLED 决定要不要验签"的机制，只有 SD 卡路径无条件调用 `VerifySignature`。

## 8) 全零区与 12,999/16,256 差异块的解释

- 机身 a1 已用簇：`boot/`=3、`initrd.img`=4…297、`vmlinux.bin`=298…401、`kemco.txt`=402、`loadaddr.txt`=403、`p1chksum`=404、`dat2`=405、`dat3`=406
  ⇒ **最后一个被占用的字节 = 簇 406 末尾 = 0x65FFFF**；FAT1/FAT2 里簇 **407…506 全为 0x000（空闲）**，数量 **101 个空簇**。
  ⇒ `0x660000` 之后**正好**是簇 407 起 ⇒ 机身 a1 的 `0x660000…0x7FFFFF` = **完全没被目录/FAT 使用的空簇**，不是"被清零的已用区"。
- 2.03 侧已用到簇 412（p1chksum）⇒ 最后字节 `0x66A7FF`；它在 0x660000 之后有内容（initrd/vmlinux 尾部），另外 5 个非零 512B 块在 `0x66c200/0x66c400/0x66c600/0x670200/0x674200`，而这些簇（433+）**在 2.03 的 FAT1/FAT2 里也是 0x000** ⇒ 2.03 的"尾巴"是 **mkfs/打包时留在未使用簇里的陈旧/填充字节**（不是文件数据）。
- 因此 12,999 个 512 B 差异块（=80.2%）分解为：
  `boot sector+FSInfo 1`（只 4 字节真差：卷序列号）+ `FAT 4`（链形状不同：297/301 的 EOF 与 404-406 vs 410-412）+ `根目录 1`（多 dat2/dat3 两个条目、p1chksum 簇号/时间戳）+ `boot/ 目录 1`（4 个簇号/大小/时间戳）+ **`空闲簇区 946`** + **`超出簇区范围的尾部 12,046`**
  ⇒ **结论：差异块 92% 是"没被使用的簇里的旧内容/填充不同"，只有 7 个 512 B 块是元数据差，真正的文件内容差体现在 0x14200-0x65FFFF 的数据簇里（那是 2.00 payload vs 2.03 payload）。不存在"机身 a1 被清零"的证据。**

## 9) 可行性判断：能不能改 a1 里的 initrd 并同步改 p1chksum？

判定：**技术上完全可行，而且比原先估计的安全，但有 3 个硬约束。**
1. **p1chksum 就是 `md5sum` 两行文本**（§4），改完 initrd 只要 `md5sum` 重写这 105 B 即可；它在 FAT 里是单簇文件（机身簇 404 @0x654200，203 簇 412 @0x659200）⇒ **可在不搬动任何其他簇的前提下原地覆盖那 1024 B**（长度 ≤105<1024，簇链不动，FAT 不动）。**格式不含机型/长度信息**，改起来零风险。
2. **但 initrd 换大/换内容会撞 8 MB / 簇数上限**：机身 `boot/kemco.txt` 里 `initrd=0x00700000,0x00800000`（**8 MiB**），2.03 的才是 `0x01000000`（16 MiB）——两版 kemco.txt **只有 2 个字节不同（偏移 0x22/0x23）**。另外全卷只有 505 簇（517,120 B 空闲，=101 空簇）⇒ 若保留机身 2.00 的 `0x00800000`，新 initrd 必须 ≤ 8 MiB（机身现在 4,812,800 B，**余量约 3.36 MB**），而若沿用 **2.03 的 4,943,872 B initrd，它已超出 8 MiB 上限**（2.03 是靠自己的 kemco.txt 才成立）。⇒ **改 initrd 时必须同时看/改 `boot/kemco.txt` 的 `initrd=` 尺寸**（它不在 p1chksum 覆盖范围内！p1chksum 只覆盖 vmlinux+initrd）。
3. **谁读 p1chksum 仍未钉**：a1 initrd 全树 0 引用（本次再确认）⇒ 校验发生在 loader/EXBL。若它按 MD5 校验，改 initrd 后必须同步改 p1chksum；若它只是记录（不校验），改了也无害。**两条路都不需要知道它的算法细节**（文本 md5sum 可以直接照抄）。
4. **验签角度**：这台机身（2.00）没有 IAMSIGN 机制，`sauu` 不验签（§7）⇒ **改 a1 的 initrd 不会碰到任何 RSA 门禁**；只有走 **SD 卡媒体更新（`sdfileinput.elf`）** 才撞上 `libsdfileinputupdaterapi.so::VerifySignature`（RSA-2048 + `/etc/VerificationKey.pem`，`79be4fb5…` 与 2.03 同 key）。
5. 回退手段：机身 a1 已完整拉回（sha256 `82e1b199…`，两次一致），2.03 包 a1 在手，dat2/dat3 可用 `ud_datcnv.elf`（两版同 sha `2b3b085e…`）再生 ⇒ **可逆**。

## 10) 本次新产物

| 路径 | 内容 |
|---|---|
| `work/l1-camera/fat12.py` | 手写 FAT12（BPB/类型判定/目录含 LFN/簇链/按路径提取，带 sha256+md5+簇号输出） |
| `work/l1-camera/a1_extracted/` | 机身 7 个文件（§3 表） |
| `work/l1-camera/a1_extracted_203/` | 2.03 的 5 个 boot 文件 |
| `work/l1-camera/a1_initrd/` + `a1_initrd_manifest.tsv` | 机身 initrd CRAMFS 全解（621 条目 / 217 文件，path/size/sha256） |
| `work/l1-camera/a1_initrd_diff.txt` | 47 个内容不同文件的逐条 2.00/2.03 size+sha 前缀 |
| `work/l1-camera/tscan.py`、`armdis.py` | capstone Thumb2 反汇编 + objdump `@plt` 关联（用于 §7 调用点定位） |

## 11) 还没钉死的（本次离线能做到 vs 需要下一步）
1. **谁读 p1chksum**：仍不在 a1 userspace（两版都 0 引用）⇒ 只可能是 loader/EXBL/BootROM。能离线做的下一步：在 `work/v203/n15/nflasha15_203`、`work/v203/u203/*` 里找 `md5sum`/`p1chksum`/`0.0` 之类的引用（本次已确认 a1 树内没有）。
2. **`UFPDecryptorModule::execWriteFirm` 到底谁调**：它在 `libsdfileinputupdaterapi.so` 里导出（PLT 表可见），但 a1 树内**只有 `sdfileinput.elf` 链这个库**；a15/body 侧是否 dlopen 它（`DllHandler::Open`）还没查 —— 这决定 PC-app(.dat) 路径会不会撞上 RSA。离线可查：`work/v203/n15/*`、`work/v203/body20[03]` 里的 `DllHandler::Open` 参数字串与 `"verifyKey"` 字串。
3. `sauu` 的 `.text` 两版差 4,583 B（272 段）具体改了哪些函数没逐函数钉（可用 `.ARM.exidx` 做函数边界后逐函数 diff）。
