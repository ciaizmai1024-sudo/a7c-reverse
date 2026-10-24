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

## ★静态实读（主会话，2.00 的 `a1_initrd/usr/lib/libInfraSKD.so`，10,160 B，Thumb-2）
**这只库自己就是解密者**：导入 `EVP_aes_256_cbc`、`EVP_CipherInit`、`EVP_CipherUpdate`、`EVP_CIPHER_CTX_new/free/set_padding`、**`SHA256`**、`snprintf`、`memcpy/memset`、`open/mmap/munmap/lseek/close`、`osal_reg_sync_msg_queue_cb/osal_unreg_msg_queue_cb`（**没有** `osal_snd_sync_msg`）。PLT 跳板 `0x7fc–0x8e0`（用 `tools/elf_imports.py` 一一对上符号）。
rodata 里的名字：**`astra_data.c`（源文件名）**、**`AstraData_Init`**、**`__GetCommonKeyData`**、**`__GetPublicKeyHash`**、`/dev/mem`、`%04x`、`%02x`、`[ERR]… getData failed`/`failed 1`/`failed 2`、`Failed 1/2/3`、`error AstraData_Init osal_reg_sync_msg_queue_cb %d`。
代码骨架（`tools/skd_dis2.py` 反出）：
- `0xc04–0xd24` = init：`open(/dev/mem)`→`mmap(0x400 @ 0xFFFF5000)`(PROT_READ)→存全局→`mmap(0x20 @ 0xF340F000)`→存全局→`blx osal_reg_sync_msg_queue_cb`（失败打 `0xf6` 那条错误）。
- `0xd28–0xd5c` = 反初始化：`munmap(…,0x400)`、`munmap(…,0x20)`。
- `0x9ec` = **按"类型 0x00–0x13"查 `{表指针, 条数}` 跳转表**的序列化器：逐条取字段，两个来源全局分别限幅 **`0x400`（＝1 KiB，正是 `0xFFFF5000` 那个窗）** 和 **`0x1f`**；`0x980` 是它下面的取数/拼串子程序（含 `snprintf` 循环 `cmp r5,#0x10`）。
- `0xa7c–0xbd6` = 分派器：`cmp r3,#1/2/3/4` 四种操作，里面出现 `open`(0x804 区)、`snprintf`、`memcpy`、0x20 字节缓冲、以及一次带 0x20 入/出缓冲的调用（不是 `EVP_*` 就是 uIPC/ioctl 式调用）——**key 的来源就在这条链里**。
## 我本轮排除的（别重复劳动）
key ≠ `0xF340F000` 那 32 字节的原值；≠ 对全零窗/1 KiB 零/空/已知 key 做 `md5/sha1/sha224/sha256/sha384/sha512/sha3/blake2s`（含二次哈希、hex 文本再哈希）；≠ `EVP_BytesToKey(MD5/SHA*,salt=NULL,cnt=1/2/1000/4096/10000)`；≠ 用 `KEY_90045`/`SHA256("")`/`pi` 常数做的 `AES-ECB/CBC/CTR` 包裹（加/解密两向）；≠ `HMAC-*(key∈{90045,SHA空,pi,零})`；≠ `sha256('0'*n)` n≤8192（含 `\n`/NUL/`0x` 前缀）与带分隔符的零 hex 文本（字段 `00/0000/00000000`，1–256 个，分隔符 空/空格/`:`/`,`/`-`/换行/制表/`0x`）。
⇒ **说明 key 的输入不是"那两个窗的零"本身**；要么还混进了 uIPC/驱动的应答，要么整条 KDF 的输入含别的（QEMU 与真机不同的）材料。
