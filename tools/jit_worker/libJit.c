/* libJit.so —— A7C(一代, ILCE-7C v2.00, ARM32/Thumb) Jiritsu 通道的自定义 worker。
 *
 * 加载方式（证据：libJiritsu.so jit_thread @0x74b0）：
 *   set_firm(0x4006) 把 tar 解到 /tmp/jiritsu(=/dev/nflasha6)  ->  我们的 libJit.so 落在那
 *   jit_thread: 检查 /tmp/jiritsu/jinit(崩溃残留) -> ramdisk_mount('/tmp/jiritsu/ramdsk_libJit','size=1M')
 *              -> copy('/tmp/jiritsu/libJit.so' -> '/tmp/jiritsu/ramdsk_libJit/libJit.so')
 *              -> dlopen(...,RTLD_LAZY) -> dlsym 下列 4 个符号并调用
 *   引擎装载请求：CImJiritsu::req(qid, 1, '/tmp/jiritsu/tmmc.jit', 'MAIN()', '/tmp/jiritsu/libJit.so')
 *
 * 调用约定（从调用点抄来）：
 *   0x76ec  blx CreateScriptI            ; 无参数，返回对象指针，0 = 失败('create fail')
 *   0x77ba  blx LoadScriptI              ; r0=obj(this+0x14) r1='/tmp/jiritsu/tmmc.jit'，非 0 = 成功
 *   0x7a60  blx RunScriptI               ; r0=obj r1=参数结构(内部) r2=名字/路径；调用前 open('/tmp/jbusy',O_CREAT|0755)，调用后 unlink
 *   0x7462  blx DestroyScriptI           ; 参数 obj
 * 因为我们同时控制两边，签名可以取最宽松的形态（只要不崩、按约定返回值）。
 *
 * 行为：RunScriptI 里
 *   1) 写 /tmp/jiritsu/WORKER.VER（心跳/版本）
 *   2) 若 /tmp/jiritsu/cmd.txt 与上次不同 -> 用 system() 执行它，输出到 /tmp/jiritsu/cmd.log
 *      （这样就能用 SET_FILE2(0x4010) 写命令 + 触发 START 来反复下命令，不必 preload）
 * 纪律：不要在这里做长阻塞（相机看门狗/UI 线程）；写文件只在 /tmp/jiritsu 下。
 *
 * ★同芯片（ZV-E10 = CXD90045）实测纠正（详见 notes/camtool.md）：
 *   1) 写 libJit.so 要走 Jiritsu `SET_FILE2(0x4010)`（=write(16)）；用 FileControl(0xff01) 写同一路径**不会触发加载**。
 *   2) `FIRMUP(0x4006)`/`FORMAT(0x4003)` 在他们机子上**卡死服务**→ 默认不发；上面的 set_firm 流程是备选。
 *   3) **真正被保证执行的入口是 dlopen 时的构造函数**（他们的载荷只靠 ctor）→ 所以下面把同样的活也挂在 ctor 上，
 *      RunScriptI 只作为“引擎发了脚本请求”时的次要触发。两边共用 do_work()，靠 cmd.txt 内容比对去重。
 *   4) dlopen **按名字缓存**：同会话里崩过一次后不再跑 ctor → 部署时把文件大小 pad 几十字节，或重启相机。
 *   5) write(16) 返回 0x10000000 = 空/非法 ELF（干净失败）；抛 USB 异常 = ctor/dlopen 崩，im.elf 死 → 相机 30–40 s 自动重启。
 */
#include <stddef.h>

/* 不依赖任何交叉头文件：自己声明用到的 libc 函数。
 * 这些符号 libJiritsu.so 自己也在用（strlen/memcpy/open/write/close/snprintf/fopen 一类），
 * dlopen 时由相机上的 libc 解析。 */
typedef struct _FILE FILE;
#ifndef EOF
#define EOF (-1)
#endif
extern FILE *fopen(const char *, const char *);
extern int fclose(FILE *);
extern int fgetc(FILE *);
extern int fputs(const char *, FILE *);
extern size_t strlen(const char *);
extern int strcmp(const char *, const char *);
extern int snprintf(char *, size_t, const char *, ...);
extern int system(const char *);
extern int unlink(const char *);

#define AREA        "/tmp/jiritsu"
#define VERFILE     AREA "/WORKER.VER"
#define CMDFILE     AREA "/cmd.txt"
#define LOGFILE     AREA "/cmd.log"
#define STMPSUFFIX  ".last"
#define LOGDIR      AREA "/worker.log"

#define WORKER_VERSION "jiritsu-worker 0.1 (a7c v2.00)"

static void wr(const char *path, const char *text)
{
    FILE *f = fopen(path, "w");
    if (f) { fputs(text, f); fclose(f); }
}

static void readfile(const char *path, char *buf, unsigned cap)
{
    FILE *f = fopen(path, "r");
    unsigned n = 0;
    cap--;
    if (!f) { buf[0] = 0; return; }
    while (n < cap) {
        int c = fgetc(f);
        if (c == EOF) break;
        buf[n++] = (char)c;
    }
    buf[n] = 0;
    fclose(f);
}

/* 脚本对象：加载器把它当不透明指针存/传，但**会解引用 obj+0x1c 当 char*【实测】**：
 *   0x77c2  ldr r6,[r3,#0x1c]; mov r0,r6; bl strlen    ← LoadScriptI 返回 0 时的失败路径，无 NULL 保护
 *   0x77e8  ldr r2,[r3,#0x1c]; ...; bl fopen           ← fopen(obj+0x1c, "a") 写日志
 *   0x791e  ldr r6,[r3,#0x1c]; cbnz …; 为 0 则用 'unknown'
 * 所以必须递一个真正可解引用的对象（不能是 0x19700101 这种假指针），且 +0x1c 处放合法字符串。
 */
static void *g_script_obj[16];            /* 0x40 字节，静态生命周期 */
#define OBJ_NAME_SLOT 7                   /* 0x1c / 4 */
static const char g_worker_log[] = LOGDIR;

void *CreateScriptI(void)
{
    int i;

    for (i = 0; i < 16; i++)
        g_script_obj[i] = 0;
    g_script_obj[OBJ_NAME_SLOT] = (void *)g_worker_log;
    return g_script_obj;                  /* 非 0 即可，但对象必须可解引用 */
}

int LoadScriptI(void *obj, const char *script_path)
{
    /* 非 0 = 成功。我们不看 tmmc.jit 的内容（自己就是执行体）。 */
    (void)obj; (void)script_path;
    return 1;
}

/* 核心工作体：ctor 与 RunScriptI 共用。cmd.txt 与上次相同则不重复执行。 */
static void do_work(const char *who, const char *name)
{
    char cmd[1024], last[1024], line[1280];

    wr(VERFILE, WORKER_VERSION "\n");
    if (name) { wr(AREA "/WORKER.NAME", name); }

    readfile(CMDFILE, cmd, sizeof cmd);
    readfile(CMDFILE STMPSUFFIX, last, sizeof last);
    if (cmd[0] && strcmp(cmd, last)) {
        snprintf(line, sizeof line,
                 "echo %s > " AREA "/cmd.who; cd " AREA " && ( %s ) > " LOGFILE " 2>&1", who, cmd);
        int rc = system(line);
        wr(AREA "/cmd.rc", rc == -1 ? "system failed" : "");
        wr(CMDFILE STMPSUFFIX, cmd);
    }
}

/* ★同芯片实测：dlopen 时构造函数一定会跑（他们的载荷只靠这个）。
 * 注意相机侧可能把 ctor 崩计成“服务消失”，所以 ctor 里只做不可能崩的事。 */
void __attribute__((constructor)) jit_ctor(void)
{
    do_work("ctor", 0);
}

int RunScriptI(void *obj, void *param, char *name)
{
    (void)obj; (void)param;
    do_work("RunScriptI", name);
    return 0;
}

void DestroyScriptI(void *obj)
{
    (void)obj;
    g_script_obj[OBJ_NAME_SLOT] = 0;
    wr(AREA "/WORKER.DONE", "1\n");
}
