// Deliberately fixed-scope elevated helper. No arguments, user-supplied commands,
// paths, scripts, manifests or configuration files are accepted by this process.
using System;
using System.Diagnostics;
using Microsoft.Win32;

internal static class EnableWsl
{
    private static int Run(string executable, string arguments)
    {
        var start = new ProcessStartInfo {
            FileName = System.IO.Path.Combine(Environment.SystemDirectory, executable),
            Arguments = arguments,
            UseShellExecute = false
        };
        using (var process = Process.Start(start)) {
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    private static int Main(string[] args)
    {
        if (args.Length != 0 || !Environment.Is64BitProcess) return 87;
        try {
            using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion")) {
                int build;
                if (key == null || !Int32.TryParse(Convert.ToString(key.GetValue("CurrentBuildNumber")), out build) || build < 22000)
                    return 50;
            }
            Console.WriteLine("NIPAT: attivazione dei soli componenti Windows necessari a WSL2.");
            bool reboot = false;
            foreach (var feature in new[] { "Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform" }) {
                int code = Run("dism.exe", "/Online /Enable-Feature /FeatureName:" + feature + " /All /NoRestart");
                if (code == 3010) reboot = true;
                else if (code != 0) return code;
            }
            // Finish installing WSL in a second ordinary-user setup run after reboot.
            if (reboot) return 3010;
            int install = Run("wsl.exe", "--install --no-distribution --web-download");
            if (install == 1641) return 3010;
            if (install != 0) return install;
            return 0;
        } catch (Exception error) {
            Console.Error.WriteLine("Prerequisiti WSL non configurati: " + error.Message);
            return 1;
        }
    }
}
