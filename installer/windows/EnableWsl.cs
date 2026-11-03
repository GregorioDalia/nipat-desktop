// Deliberately fixed-scope elevated helper. No arguments, user-supplied commands,
// paths, scripts, manifests or configuration files are accepted by this process.
using System;
using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Win32;

// Pure decisions are exercised by test-windows-environment.ps1, also on Server CI.
public static class NipatWindowsPolicy
{
    public static bool Supports(bool os64, bool process64, string architecture, int build, string installationType)
    {
        return os64 && process64 && String.Equals(architecture, "AMD64", StringComparison.OrdinalIgnoreCase)
            && String.Equals(installationType, "Client", StringComparison.OrdinalIgnoreCase)
            && (build == 19045 || build >= 22000);
    }

    public static bool ModernWsl(int code, string text)
    {
        if (code != 0) return false;
        var lines = (text ?? "").Replace("\0", "").Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        string first = Array.Find(lines, line => !String.IsNullOrWhiteSpace(line)) ?? "";
        var match = Regex.Match(first, @"\b[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?\b");
        Version version;
        return match.Success && Version.TryParse(match.Value, out version) && version >= new Version(1, 0, 0);
    }

    public static string Command(bool modern, string help)
    {
        help = (help ?? "").Replace("\0", "");
        string web = help.Contains("--web-download") ? " --web-download" : "";
        // Prefer updating an existing package (including legacy inbox WSL).
        if (help.Contains("--update")) return "--update" + web;
        if (!modern && help.Contains("--install") && help.Contains("--no-distribution"))
            return "--install --no-distribution" + web;
        return null; // Never fall back to a bare --install, which installs Ubuntu.
    }
}

internal static class EnableWsl
{
    private static int Run(string executable, string arguments, out string output)
    {
        var start = new ProcessStartInfo {
            FileName = System.IO.Path.Combine(Environment.SystemDirectory, executable),
            Arguments = arguments,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            CreateNoWindow = true
        };
        using (var process = Process.Start(start)) {
            process.StandardInput.Close();
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(30 * 60 * 1000)) {
                process.Kill();
                output = "Timeout configurazione WSL. Attendere la conclusione delle operazioni Windows prima di riprovare.";
                return 1460;
            }
            output = (stdout.Result + "\n" + stderr.Result).Replace("\0", "").Trim();
            if (output.Length > 0) Console.WriteLine(output);
            return process.ExitCode;
        }
    }

    private static int Main(string[] args)
    {
        if (args.Length != 0) return 87;
        try {
            using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion")) {
                int build;
                string architecture = Environment.GetEnvironmentVariable("PROCESSOR_ARCHITEW6432");
                if (String.IsNullOrEmpty(architecture)) architecture = Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE");
                if (key == null || !Int32.TryParse(Convert.ToString(key.GetValue("CurrentBuildNumber")), out build)
                    || !NipatWindowsPolicy.Supports(Environment.Is64BitOperatingSystem, Environment.Is64BitProcess,
                        architecture, build, Convert.ToString(key.GetValue("InstallationType")))) {
                    Console.Error.WriteLine("NIPAT richiede Windows 10 22H2 x64 (build 19045) oppure Windows 11 x64. Windows Server, ARM e 32 bit non sono supportati.");
                    return 50;
                }
            }
            Console.WriteLine("NIPAT: attivazione dei soli componenti Windows necessari a WSL2.");
            bool reboot = false;
            string output;
            foreach (var feature in new[] { "Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform" }) {
                int code = Run("dism.exe", "/Online /Enable-Feature /FeatureName:" + feature + " /All /NoRestart", out output);
                if (code == 3010) reboot = true;
                else if (code != 0) return code;
            }
            // Finish installing WSL in a second ordinary-user setup run after reboot.
            if (reboot) return 3010;
            int versionCode = Run("wsl.exe", "--version", out output);
            bool modern = NipatWindowsPolicy.ModernWsl(versionCode, output);
            Run("wsl.exe", "--help", out output);
            string help = output;
            string command = NipatWindowsPolicy.Command(modern, help);
            if (command == null) {
                Console.Error.WriteLine("WSL Windows non espone le opzioni di installazione sicura. Installare gli aggiornamenti Windows/WSL da Microsoft e riaprire NIPAT-Setup.exe. https://learn.microsoft.com/windows/wsl/install");
                return 50;
            }
            int install = Run("wsl.exe", command, out output);
            if (install == 1641) return 3010;
            if (install != 0) return install;
            versionCode = Run("wsl.exe", "--version", out output);
            if (!NipatWindowsPolicy.ModernWsl(versionCode, output)) {
                // Older inbox --update may update only the kernel. Install the
                // packaged WSL only if explicitly supported without a distro.
                Run("wsl.exe", "--help", out help);
                if (!help.Contains("--install") || !help.Contains("--no-distribution")) return 50;
                command = "--install --no-distribution" + (help.Contains("--web-download") ? " --web-download" : "");
                install = Run("wsl.exe", command, out output);
                return install == 1641 ? 3010 : install;
            }
            return 0;
        } catch (Exception error) {
            Console.Error.WriteLine("Prerequisiti WSL non configurati: " + error.Message);
            return 1;
        }
    }
}
