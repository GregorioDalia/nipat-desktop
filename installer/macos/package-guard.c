/* Package transactions coordinate with CLI sessions without stopping analyses. */
#include <sys/file.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#define STATE "/Library/Application Support/NIPAT-Experimental08 Installer"
#define LOCK STATE "/activity.lock"
#define MARKER STATE "/update-in-progress"

static int fail(const char *message) {
    fprintf(stderr, "NIPAT: %s\n", message);
    return 1;
}

int main(int argc, char **argv) {
    (void)argc;
    struct stat info;
    if (geteuid() != 0) return fail("Installer must run as administrator.");
    umask(022);
    if (mkdir(STATE, 0755) < 0 && errno != EEXIST) return fail("Cannot create package state.");
    if (lstat(STATE, &info) < 0 || !S_ISDIR(info.st_mode) || info.st_uid != 0
        || (info.st_mode & 0777) != 0755) return fail("Unsafe package state directory.");
    int descriptor = open(LOCK, O_CREAT | O_RDONLY | O_NOFOLLOW, 0644);
    if (descriptor < 0 || fstat(descriptor, &info) < 0 || !S_ISREG(info.st_mode)
        || info.st_uid != 0 || (info.st_mode & 0777) != 0644)
        return fail("Unsafe package activity lock.");
    if (flock(descriptor, LOCK_EX | LOCK_NB) < 0)
        return fail("Close all NIPAT Experimental08 sessions before installing.");
    const char *name = strrchr(argv[0], '/');
    name = name ? name + 1 : argv[0];
    if (strcmp(name, "preinstall") == 0) {
        const char *app = "/Applications/NIPAT Experimental08.app";
        if (lstat(app, &info) == 0 && (!S_ISDIR(info.st_mode) || info.st_uid != 0))
            return fail("Application destination is not an installer-owned directory.");
        int marker = open(MARKER, O_CREAT | O_WRONLY | O_NOFOLLOW, 0644);
        if (marker < 0 || fstat(marker, &info) < 0 || !S_ISREG(info.st_mode)
            || info.st_uid != 0) return fail("Unsafe package update marker.");
        close(marker);
    } else if (strcmp(name, "postinstall") == 0) {
        if (unlink(MARKER) < 0 && errno != ENOENT) return fail("Cannot complete package transaction.");
    } else return fail("Unsupported package transaction.");
    close(descriptor);
    return 0;
}
