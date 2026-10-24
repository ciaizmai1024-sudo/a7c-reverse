/* loattach.c — Round14 tiny losetup (busybox lacks it).
 * usage: loattach /dev/loop0 /dev/nflasha11
 * LOOP_SET_FD only (offset 0, whole backing). Kernel 3.0.27 ioctl numbers. */
#include <stdio.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#define LOOP_SET_FD 0x4C00
int main(int c, char **v)
{
    int cfd, bfd, rc;
    if (c < 3) { fprintf(stderr, "usage: %s loopdev backing\n", v[0]); return 2; }
    cfd = open(v[1], O_RDWR);
    if (cfd < 0) { printf("LOATTACH-OPEN-C=ERR errno=%d\n", errno); return 1; }
    bfd = open(v[2], O_RDWR | O_LARGEFILE);
    if (bfd < 0) { printf("LOATTACH-OPEN-B=ERR errno=%d\n", errno); return 1; }
    rc = ioctl(cfd, LOOP_SET_FD, bfd);
    printf("LOATTACH-RC=%d errno=%d\n", rc, errno);
    close(bfd); close(cfd);
    return rc != 0;
}
