// Console entry point for the Windows WSL installation.
// User arguments are data in the child environment, never PowerShell source.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

internal static class NipatLauncher
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint GetConsoleProcessList(uint[] processes, uint count);

    private static bool OwnsConsole()
    {
        try {
            return !Console.IsInputRedirected && !Console.IsOutputRedirected &&
                GetConsoleProcessList(new uint[2], 2) == 1;
        } catch {
            return false;
        }
    }

    // Quote one Windows command-line argument, including trailing backslashes.
    // Only the trusted bridge path is passed on the PowerShell command line.
    private static string QuoteArgument(string value)
    {
        var quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char item in value) {
            if (item == '\\') {
                slashes++;
            } else if (item == '"') {
                quoted.Append('\\', slashes * 2 + 1).Append(item);
                slashes = 0;
            } else {
                quoted.Append('\\', slashes).Append(item);
                slashes = 0;
            }
        }
        return quoted.Append('\\', slashes * 2).Append('"').ToString();
    }

    private static int Run(string[] arguments)
    {
        string project = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string bridge = Path.Combine(project, "installer", "windows", "launch.ps1");
        string runner = Path.Combine(project, "scripts", "windows", "run.ps1");
        if (!File.Exists(bridge) || !File.Exists(runner)) {
            throw new FileNotFoundException(
                "Pacchetto NIPAT incompleto. Ripristinare l'installazione con NIPAT-Setup.exe; NIPAT.exe deve restare nella cartella del programma.");
        }
        string powershell = Path.Combine(Environment.SystemDirectory,
            "WindowsPowerShell", "v1.0", "powershell.exe");
        if (!File.Exists(powershell)) {
            throw new FileNotFoundException("Windows PowerShell non e' disponibile in questo sistema.");
        }
        if (arguments.Length == 0) arguments = new[] { "wizard" };
        var encoded = new string[arguments.Length];
        for (int index = 0; index < arguments.Length; index++) {
            encoded[index] = Convert.ToBase64String(Encoding.UTF8.GetBytes(arguments[index]));
        }
        var start = new ProcessStartInfo {
            FileName = powershell,
            Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File " + QuoteArgument(bridge),
            WorkingDirectory = Environment.CurrentDirectory,
            UseShellExecute = false
        };
        start.EnvironmentVariables["NIPAT_LAUNCH_ARGUMENTS"] = String.Join("\n", encoded);
        start.EnvironmentVariables["NIPAT_LAUNCH_ARGUMENT_COUNT"] = arguments.Length.ToString(
            System.Globalization.CultureInfo.InvariantCulture);
        // The scientific child handles Ctrl+C; keep the wrapper alive to return
        // that child's status rather than abandoning it in the background.
        ConsoleCancelEventHandler cancellation = delegate(object sender, ConsoleCancelEventArgs item) {
            item.Cancel = true;
        };
        Console.CancelKeyPress += cancellation;
        try {
            using (var process = Process.Start(start)) {
                process.WaitForExit();
                return process.ExitCode;
            }
        } finally {
            Console.CancelKeyPress -= cancellation;
        }
    }

    private static int Main(string[] arguments)
    {
        bool ownConsole = OwnsConsole();
        int code;
        try {
            code = Run(arguments);
        } catch (Exception error) {
            Console.Error.WriteLine("Avvio NIPAT non riuscito: " + error.Message);
            code = 1;
        }
        if (code != 0 && ownConsole) {
            Console.Error.WriteLine("NIPAT si e' chiuso con codice " + code + ". Consultare il messaggio precedente.");
            Console.WriteLine("Premere un tasto per chiudere questa finestra.");
            try { Console.ReadKey(true); } catch (InvalidOperationException) { }
        }
        return code;
    }
}
