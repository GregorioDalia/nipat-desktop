/* Open the bundled CLI in Terminal without depending on a shell profile. */
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char executable[PATH_MAX], real[PATH_MAX], command[PATH_MAX];
    uint32_t size = sizeof executable;
    if (_NSGetExecutablePath(executable, &size) != 0 || !realpath(executable, real))
        return 1;
    char *directory = strrchr(real, '/');
    if (!directory) return 1;
    *directory = '\0';
    directory = strrchr(real, '/');
    if (!directory) return 1;
    *directory = '\0';
    if (snprintf(command, sizeof command, "%s/Resources/NIPAT.command", real)
        >= (int)sizeof command) return 1;
    execl("/usr/bin/open", "open", "-a", "Terminal", command, (char *)NULL);
    perror("NIPAT: Terminal");
    return 1;
}
