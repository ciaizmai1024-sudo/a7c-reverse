# R16-B/D: 验签链实验（r16pos/negA/negB/negC）

## 跑次与结果（全部 initrd 驱动、mode5 每轮重注入；A7C_MAP=g）
| 跑 | 卡 | initrd | 结果 |
|---|---|---|---|
| pos (首试) | r16pos(=v203 副本) | r16(删:uc) | t=2s `dmm_ctrl_Init` oops（删 :uc 破坏 dmm）→弃 |
| negA | r16negA(2.00 .dat+翻位@0x100000dc) | r16e | **Old 2.0/New 2.0 → Error 86**（版本门，与 p5 一致；翻位在消息区但到不了验签） |
| negB(1st) | r16negB(2.03, 文件 +0x2000000 翻1bit) | r16e | copy 到 90% 后内核 memcpy oops @0xb0800000（DDR1 线性窗顶=vmalloc 0xB0800000；`:uc` 512M 挤占 → 363MB 拷贝越窗） |
| negB2 | 同上 | **r16**(:uc 缩到 256M, start 不变 + `OPENSSL_armcap=0`) | 拷贝**完成**：`cpp:66 Firmware Copy Completed / cpp:69 total_data_size=363,197,712` → **`UdrAPI,196610,SignatureVerification.cpp:117,"signature"` → [FIRMUP NG] Error 42** |
| negC | 2.03, 文件 +0x14000000 翻1bit | r16 | 同 negB2：**cpp:117 "signature" → Error 42**（位置无关 ✓） |
| pos3 | 2.03 未改一字（从 r15v203 新副本，卡上 .dat md5 与 r15v203 完全一致=39909c96…） | r16 | **也 cpp:117 "signature" → Error 42**（同码 0x30002！） |

## 关键机理（反汇编 `SignatureVerification` 全链，libsdfileinputupdaterapi.so）
- `VerifySignature(verify_info_t, const char*)` @0xdd6c：
  `verifyKey(path)` → 非0则 FAIL(cpp:41)；`fopen`(46)；`PEM_read_RSA_PUBKEY`(51)；
  **`SHA256(msg,len)` → `RSA_verify(NID_sha256=0x2a0, 32, digest, sig, rsa)`**（cpp:65 fail）⇒ 相机侧算法 = **SHA-256 + RSA**。
- `verifyKey(path)` @0xdbcc：`open/lseek/mmap`（mmap 的就是 **VerificationKey.pem**）→
  **`SHA1_Init/Update/Final`（对 PEM 做 SHA-1）** → `osal_valloc_msg_wait + osal_snd_sync_msg`（**向 backup 模块/uIPC 查询 Backup 里存的钥匙指纹**）→ `strncmp` 比对。
  早先 pos/negB 首跑的 NEON-SHA1 非法指令崩溃就发生在这里（libcrypto+0xE579C `vld1.8`，QEMU 核没 NEON）；`OPENSSL_armcap=0` 修好。
- guest 里 cpp:117 "signature"(0x30002→Error 42) = **verifyKey 的指纹/钥匙比对失败**，发生在 `RSA_verify`(cpp:65) 之前：
  pos 与 neg 都在同一门死 ⇒ **本轮"过验签/验签失败"的正负对照在该门上不可分辨**（42 不再能区分签名内容错）。
  两个负样的 FAIL 判定只到"验签链内 verifyKey 门"，未到消息摘要本身；pos 也未到 RSA_verify。
- 验签时机（问题④）：在 **整个 FDAT 一次性拷进 RAM 完成之后**（`cpp:66/69` 才进 SignatureVerification；
  `SDFileInputUpdaterManager.cpp:214 "Read size = 363197724"`+`"Read size = 0"` 一次大读，无单独读尾 0x100 的 Fsys 读；
  摘要在缓冲区上做，不是流式）。
- 写表：pos3/negB2/negC 各 11 条 ZZSDWRITE = a2(0x800200/800a00/810a00) + 卡切片(0xb82e000.. vfat dir)，
  **没有任何固件分区写**（D 未开始）。

## 下一步（未竟项）
1. cpp:117 的比对到底是什么：dump a2 `Backup.bin/Backup.bak` 里的 `uudkey` 类记录，
   离线比对 SHA1(/etc/VerificationKey.pem)（本机 pem md5=ecbe36e0…）；若存储指纹来自真机 a1 应相等 ⇒ 差的可能在
   osal 应答结构/我们缺的 backup 状态（真机 `updater/` 目录还有 `comp/dat4` 等文件参与）。
2. 过了 verifyKey 才谈得上 cpp:65 "RSA_verify fail"(负) vs pass(正)；然后才是写固件分区枚度(D)。
3. 内存配方已定：cmdline `memrsv=0x10000000@0x20000000:uc`（保留 :uc 起始值，dmm 需要）+ `OPENSSL_armcap=0`（QEMU 核无 NEON）
   ——这是后续所有轮次的标准环境（initrd_r16.img 已内置）。
