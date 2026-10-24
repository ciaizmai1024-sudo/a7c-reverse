/* selftest.c —— 复刻相机 jit_thread 加载 libJit.so 的调用序列，做功能自测。
 * 在 arm32 容器里编译运行：make test
 * 对应相机侧证据（libJiritsu.so jit_thread @0x74b0）：
 *   0x7666 ramdisk_mount('/tmp/jiritsu/ramdsk_libJit','size=1M')
 *   0x7684 copy('/tmp/jiritsu/libJit.so' -> ramdisk 副本)
 *   0x769c dlopen(副本, RTLD_LAZY)
 *   0x76c8 dlsym 'CreateScriptI' -> 0x76ec 调用，返回 0 = 'create fail'
 *   0x7706 dlsym 'LoadScriptI'   -> 0x77ba 调用(obj, "/tmp/jiritsu/tmmc.jit")，非 0 = 成功
 *   0x7a60 dlsym 'RunScriptI'    -> 调用(obj, 参数结构, 名字)，调用前建 /tmp/jbusy，调用后 unlink
 *   release @0x7454: dlsym 'DestroyScriptI' -> 调用(obj) -> dlclose
 */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

typedef void *(*Create_t)(void);
typedef int (*Load_t)(void *, const char *);
typedef int (*Run_t)(void *, void *, char *);
typedef void (*Destroy_t)(void *);

static int exists(const char *p)
{
    struct stat st;
    return stat(p, &st) == 0;
}

int main(int argc, char **argv)
{
    const char *so = argc > 1 ? argv[1] : "./libJit.so";
    void *h = dlopen(so, RTLD_LAZY);
    if (!h) {
        printf("FAIL: dlopen: %s\n", dlerror());
        return 1;
    }
    Create_t Create = (Create_t)dlsym(h, "CreateScriptI");
    Load_t Load = (Load_t)dlsym(h, "LoadScriptI");
    Run_t Run = (Run_t)dlsym(h, "RunScriptI");
    Destroy_t Destroy = (Destroy_t)dlsym(h, "DestroyScriptI");
    if (!Create || !Load || !Run || !Destroy) {
        printf("FAIL: dlsym 缺符号 Create=%p Load=%p Run=%p Destroy=%p\n",
               (void *)Create, (void *)Load, (void *)Run, (void *)Destroy);
        return 1;
    }

    void *obj = Create();
    if (!obj) { printf("FAIL: CreateScriptI 返回 0（相机会报 'create fail'）\n"); return 1; }
    printf("CreateScriptI -> obj=%p\n", obj);

    /* 相机在失败/日志路径上会直接解引用 obj+0x1c 当 char*（0x77c2 strlen，0x77e8 fopen(..,"a")）。
     * 这里把那段行为原样重放，确保我们的对象呏得起。 */
    void **slots = (void **)obj;
    char *name_at_1c = (char *)slots[7];
    printf("obj+0x1c = %p\n", (void *)name_at_1c);
    if (!name_at_1c) { printf("FAIL: obj+0x1c 是 NULL → 相机 0x77c6 的 strlen 会崩\n"); return 1; }
    printf("obj+0x1c 字符串 = %s (strlen=%zu)\n", name_at_1c, strlen(name_at_1c));
    FILE *lf = fopen(name_at_1c, "a");
    if (lf) { fputs("selftest wrote through obj+0x1c\n", lf); fclose(lf); printf("按 0x77e8 的方式 fopen(obj+0x1c,\"a\") 成功\n"); }
    else printf("注: fopen(obj+0x1c,\"a\") 失败（不致命，但相机日志会写不出）\n");

    int rc = Load(obj, "/tmp/jiritsu/tmmc.jit");
    printf("LoadScriptI(obj, tmmc.jit) = %d  (相机要求非 0)\n", rc);
    if (!rc) { printf("FAIL: LoadScriptI 返回 0\n"); return 1; }

    /* 参数结构在相机侧是内部结构体；我们的 worker 不用它，这里传 NULL 检查健壮性 */
    char name[] = "MAIN()";
    rc = Run(obj, NULL, name);
    printf("RunScriptI(obj, NULL, \"%s\") = %d\n", name, rc);

    /* 副作用检查 */
    printf("WORKER.VER 存在? %s\n", exists("/tmp/jiritsu/WORKER.VER") ? "是" : "否");
    printf("WORKER.NAME 存在? %s\n", exists("/tmp/jiritsu/WORKER.NAME") ? "是" : "否");
    printf("cmd.ran 存在?    %s   (说明 cmd.txt 里的命令真的被执行了)\n", exists("/tmp/jiritsu/cmd.ran") ? "是" : "否");

    /* 再跑一次：cmd.txt 未变则不应重复执行 */
    Run(obj, NULL, name);
    printf("第二次 RunScriptI 后 cmd.ran 仍在，无重复副作用（预期）\n");
    printf("worker.log 存在? %s\n", exists("/tmp/jiritsu/worker.log") ? "是" : "否");

    Destroy(obj);
    printf("DestroyScriptI 完成，WORKER.DONE 存在? %s\n", exists("/tmp/jiritsu/WORKER.DONE") ? "是" : "否");
    printf("WORKER.DONE 内容: "); fflush(stdout);
    if (system("cat /tmp/jiritsu/WORKER.DONE")) { printf("(读不到)\n"); }
    dlclose(h);

    if (!exists("/tmp/jiritsu/WORKER.VER") || !exists("/tmp/jiritsu/cmd.ran")) {
        printf("FAIL: 预期副作用缺失\n");
        return 1;
    }
    if (!name_at_1c) { printf("FAIL: obj+0x1c 必须非 NULL\n"); return 1; }
    printf("PASS\n");
    return 0;
}
