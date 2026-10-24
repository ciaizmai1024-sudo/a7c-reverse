#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>
int main(int c, char **v)
{
    int fd = open(v[1], O_RDWR);
    printf("R12-MCMN-OPEN=%d errno=%d\n", fd, errno);
    if (fd < 0) return 1;
    void *p = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    printf("R12-MCMN-MMAP=%p errno=%d\n", p, errno);
    if (p != MAP_FAILED) {
        printf("R12-MCMN-W0=%08x W1=%08x\n", *(unsigned *)p, *((unsigned *)p + 1));
        munmap(p, 4096);
    }
    close(fd);
    return 0;
}
