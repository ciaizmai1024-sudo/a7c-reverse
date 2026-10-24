/* r14fshim.c — Round14b: LD_PRELOAD shim that gives the A7C mode5 updater
 * (sdfileinput.elf / libsdfileinputupdaterapi.so / libupdatercommon.so) a
 * "card" without any CXD900x0 PCIe-DME / mcmn SD host model in QEMU.
 *
 * It implements exactly the Fsys_* imports those two objects need, on top of a
 * real vfat that the guest already loop-mounts (from /dev/nflasha11 = the 500MB
 * partition at USER-offset 0xb800000) at CARDROOT.
 *
 * Semantics taken from the disassembly (E1):
 *   Updater::FsysFileHandler layout: [0]=vptr [4]=int handle [8]=opened flag
 *   Open  -> Fsys_Open(path, &handle, flags) : 0 = OK, handle must be NON-ZERO
 *   Close -> Fsys_Close(handle)              : 0 = OK
 *   Read  -> Fsys_Read(handle, buf, len)     : return used with >=0 test
 *   Seek  -> Fsys_Seek(handle, off, whence)  : 0 = OK
 * Deviations are printed with the R14FSHIM prefix into the serial log.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

#define CARDROOT "/ramdsk/mnt"
#define MAXF 24
static int g_fd[MAXF];       /* handle(1..MAXF) -> fd ; handle 0 means "closed" */
static long g_pos[MAXF];
static int g_mounted;

static void lg(const char *fmt, const char *a, const char *b, long v)
{
    fprintf(stderr, "R14FSHIM %s a=%s b=%s v=%ld\n", fmt, a ? a : "-", b ? b : "-", v);
    fflush(stderr);
}

/* map a Fsys path ("A:/BODYDATA.DAT", "/mmca1/x", "BODYDATA.DAT" ...) to CARDROOT */
static void mapp(const char *in, char *out, int n)
{
    const char *p = in;
    if (p) {
        const char *q = strrchr(p, '/');
        if (q) p = q + 1;
        if (!*p) p = "BODYDATA.DAT";
    } else p = "BODYDATA.DAT";
    snprintf(out, n, CARDROOT "/%s", p);
}

int Fsys_Init(void)                      { g_mounted = 0; lg("Init", 0, 0, 0); return 0; }
int Fsys_Exit(void)                      { lg("Exit", 0, 0, 0); return 0; }
int mcmn_init(void)                      { lg("mcmn_init-forced-0", 0, 0, 0); return 0; }

int Fsys_Mount(const char *dev, unsigned f, const char *mnt, unsigned g)
{
    struct stat st;
    lg("Mount", dev, mnt, f);
    if (stat(CARDROOT "/BODYDATA.DAT", &st) != 0) { lg("Mount-no-card-file", 0, 0, errno); return 0x80000041; }
    g_mounted = 1;
    return 0;
}
int Fsys_Unmount(const char *dev)        { lg("Unmount", dev, 0, 0); g_mounted = 0; return 0; }

int Fsys_Open(const char *path, int *handle, unsigned flags)
{
    char p[512]; int i, fd;
    mapp(path, p, sizeof p);
    fd = open(p, (flags & 2) ? O_RDWR : O_RDONLY);
    lg("Open", path, p, flags);
    if (fd < 0) { lg("Open-fail", p, 0, errno); return 0x80000001; }
    for (i = 1; i <= MAXF; i++) if (g_fd[i] == 0) break;
    if (i > MAXF) { close(fd); return 0x80000002; }
    g_fd[i] = fd; g_pos[i] = 0;
    if (handle) *handle = i;            /* MUST be non-zero (handler checks it) */
    lg("Open-ok", p, 0, i);
    return 0;
}
int Fsys_Close(int h)
{
    lg("Close", 0, 0, h);
    if (h < 1 || h > MAXF || !g_fd[h]) return 0x80000003;
    close(g_fd[h]); g_fd[h] = 0;
    return 0;
}
int Fsys_Read(int h, void *buf, unsigned len)
{
    ssize_t r;
    if (h < 1 || h > MAXF || !g_fd[h]) { lg("Read-badhandle", 0, 0, h); return -1; }
    r = read(g_fd[h], buf, len);
    if (r > 0) g_pos[h] += r;
    if (r < 0) lg("Read-fail", 0, 0, errno);
    else if (r == 0) lg("Read-eof", 0, 0, len);
    return (int)r;
}
int Fsys_Write(int h, void *buf, unsigned len)
{
    ssize_t r;
    if (h < 1 || h > MAXF || !g_fd[h]) return -1;
    r = write(g_fd[h], buf, len);
    if (r > 0) g_pos[h] += r;
    return (int)r;
}
int Fsys_Seek(int h, long off, int whence)
{
    off_t r;
    if (h < 1 || h > MAXF || !g_fd[h]) { lg("Seek-badhandle", 0, 0, h); return 0x80000004; }
    r = lseek(g_fd[h], off, whence ? whence : SEEK_SET);
    lg("Seek", 0, 0, (long)r);
    if (r < 0) return 0x80000005;
    g_pos[h] = (long)r;
    return 0;                           /* 0 = OK (wrapper tail-calls and tests) */
}
/* Fsys_Seek variants that return the position through an out-param */
int Fsys_Seek64(int h, long long off, int whence, long long *pos)
{
    off_t r = lseek(g_fd[h], (off_t)off, whence ? whence : SEEK_SET);
    if (pos) *pos = r;
    return r < 0 ? 0x80000005 : 0;
}

/* directory enumeration: struct layout unknown -> only fill the first bytes with
 * the name (deviation). Enough to satisfy "find BODYDATA.DAT on the card". */
int Fsys_FindFirst(const char *pattern, void *info)
{
    char p[512]; struct stat st;
    mapp(pattern, p, sizeof p);
    lg("FindFirst", pattern, p, 0);
    if (stat(p, &st) != 0) return 0x80000010;
    memset(info, 0, 260);
    memcpy(info, strrchr(p, '/') + 1, strlen(strrchr(p, '/') + 1));
    return 0;
}
int Fsys_FindNext(void *info)           { lg("FindNext-end", 0, 0, 0); return 0x80000011; }

/* some callers ask for size through the Fsys stat-ish API */
int Fsys_GetFileSize(const char *path, unsigned *size)
{
    char p[512]; struct stat st;
    mapp(path, p, sizeof p);
    if (stat(p, &st) != 0) return 0x80000012;
    *size = (unsigned)st.st_size;
    lg("GetFileSize", path, p, st.st_size);
    return 0;
}
