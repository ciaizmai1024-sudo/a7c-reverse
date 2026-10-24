# FDAT 的 AES-256-CBC key 与 verifyKey 指纹的真正来源 = SoC 物理窗（OTP/eFuse 侧）

> 本轮（Round 19 前后）由三路拼出来：2015 MacBook 上的 `qoderclicn` 子代理拆 `crypter.elf`/`libupdatertalk.so`/`libupdaterufp.so`，
> 主会话拆 `libInfraSKD.so`（本地 `llvm-objdump`，Thumb），QEMU 侧提供运行时实测值。地址与字面量我都逐条复核过。

## 1. 分层结果

| 层 | 模块 | 管什么 | key/IV 来源 |
|---|---|---|---|
| 帧头 512 B | `libupdatertalk.so`（a1 `/usr/lib`，3,404 B，Thumb） | `Dec_ScrambleInit`/`Dec_Scramble` = **AES-128-ECB 单块**（`AES_set_decrypt_key(KeyArray, 0x80, &decx)`；`AES_decrypt` + `memcpy` 原地） | `KeyArray` = **完整 SHA256("")**（前 16 B 实际用，后 16 B 不读）；`decx`(244 B)= OpenSSL `AES_KEY`，`rounds=10` |
| 调用方 | `libupdaterufp.so`（a15 里，符号 UND + `DT_NEEDED libupdatertalk.so`） | `udtr_get_firm_info_inmedia`：`Fsys_Read` 读 0x204 → 对 **0x200 做 32 次 `Dec_Scramble`**（就是帧头 512 B）；解完再 `Backup_read(0xe7002e)` | 不产 key |
| **AES-256-CBC** | **`libInfraSKD.so`**（a1 `/usr/lib`，10,160 B；源文件 `astra_data.c`；导出 `SKData_Init`/`SKData_Exit`；内含 `__GetCommonKeyData`/`__GetPublicKeyHash`） | `EVP_aes_256_cbc` + `EVP_CipherInit/Update` + `SHA256` | **`/dev/mem` 物理窗**（见下） |

## 2. `SKData_Init`（0xc04）逐条复核后的等价 C

```c
fd = open("/dev/mem", 0);
mapA = mmap(0, 0x400, PROT_READ /*1*/, MAP_SHARED /*1*/, fd, /*offset*/ 0xFFFF5000);
*(glob) = mapA;                       // lit@0xd00 + pc
lseek(fd, 0, SEEK_SET);
mapB = mmap(0, 0x20,  PROT_READ, MAP_SHARED, fd, /*offset*/ 0xF340F000);   // ★32 字节
osal_reg_sync_msg_queue_cb(...);      // 通过 uIPC 消息队列对外服务（主系统也用它）
```

字面量核对：`lit@0xcd8 = 0xffff5000`（mmap#1 偏移）、`lit@0xcdc = 0xf340f000`（mmap#2 偏移）、`movs r1,#0x400` / `movs r1,#0x20`、
`/dev/mem` 字符串在 `.rodata 0x1e0d`，`astra_data.c` 在 `0x1dba`，`AstraData_Init` 在 `0x12b6`。

⇒ **AES-256-CBC 的 key = 物理 `0xF340F000` 的 32 字节**；`0xFFFF5000` 的 1 KiB 极可能是 `__GetPublicKeyHash` 那侧（verifyKey 的 20 字节指纹）。

## 3. 一次性解释掉的现象

- **两把 key 在整块 eMMC/.dat 里都搜不到** ⇒ 本来就不在 flash 里，在 SoC 窗口（OTP/eFuse 侧）。
- **`KEY_90045` 这个命名**（`c1aa8f7c46341ffed15589fc8170a6bb5925e85f6282d7f95ba3fdf5d303e06b`）＝ **CXD90045 平台 key**，按机型恒定 ⇒ 同一个官方包在整批 A7C 上都能解（我们离线 2.00/2.03 全部帧校验通过也印证）。
- **QEMU 里测到 `7e68a34d461f1388620c91d76ac1113f78efb47fa3d5b5be6d025a40cd14fc3b`** ⇒ 那就是 **QEMU 里 `0xF340F000` 那 32 字节的实际内容**（板级模型给的东西，不是真 key）⇒ `verifySum` 报 `6157:664` 的唯一原因。
- **R17 抓到 verifyKey 比对值 `b = 20×00`、且整块 eMMC 里没有任何 PEM 摘要归一化** ⇒ 指纹不在 flash，QEMU 里那扇窗是 0 ⇒ 与 `0xFFFF5000` 完全吻合。
- **R18 `-DFIXKEY` 换 key 就通**、`libupdatertalk` 里"没有 256 位/没有 IV"的矛盾 ⇒ 都通了：CBC 层根本不在那两只库里。

## 4. 立刻可做的事

1. **QEMU（已下达 R19）**：读 guest 物理 `0xF340F000`(32 B) 与 `0xFFFF5000`(1 KiB) 存盘；查 `hw/arm/bionz.c`/设备树里这两个地址是什么区域、内容从哪来；
   **把 `0xF340F000` 填成 `c1aa8f7c…`（真平台 key）再跑** ⇒ `verifySum` 应当自己就过，不必挂 `-DFIXKEY`，然后进 burn 拿写枚度。
   若 `0xFFFF5000` 里能对上 `SHA1(VerificationKey.pem)=184bbeff…`，verifyKey 这个谜也一并解掉。
2. **真机（只读、排在建批次里）**：`/dev/mem` 读 `0xF340F000`(32 B)、`0xFFFF5000`(1 KiB)。
   注意这是 SoC 高位窗（不是 `mem=` 里的 DDR，也不是 `0x635c6000` 那类 DSP 地址）：**先小读、别整页乱读**，风险 R1（读 OTP 控制器一般安全，但没验证过）。
3. 顺带记一个新常量：`libupdaterufp` 在解密之后调 `Backup_read(0xe7002e)` —— R19 排 Backup 条目时把这个 ID 也带上。

## 5. 对自签路线的影响（改写信任根判断）

信任链不是"flash 里的一把 PEM"，而是 **SoC 窗口里的 key/哈希 + 读它的代码**：

- `verifyKey` 拿 `SHA1(PEM)` 跟 **OTP 侧**比 ⇒ **换 PEM 不能靠刷 a1 解决**（OTP 改不了）。
- 但比较动作是**代码**做的（`__GetPublicKeyHash`，a1 一份、a15 里 `+0xde58482` 还有一份）⇒ **改代码可行**：
  把 getter 改成返回我们 PEM 的 SHA1（或干脆让它读 flash 里一个条目）。
- 于是路线变成：**L2.6 raw 写 a1（带打过补丁的 `libInfraSKD.so` + 我们的 PEM）= 信任根 bootstrap**，
  之后自签 .dat（CBC key 那 32 字节也可以让补丁从别处取）就能一路过 verifyKey → RSA_verify → 解密。
- 另一条更省事的：**QEMU/真机里那扇 `0xF340F000` 窗本身就是入口**——如果补丁让 key/哈希来自 flash，
  就等于把 OTP 依赖搬进可写分区，后续实验全部离线可做。

（`notes/crypter-decrypt-boundary.md` 记 crypter/ufp/talk 的边界与地址；本文件记 key/哈希来源。）
