// Compiled during the reviewed build; never generated on the destination PC.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Microsoft.Win32.SafeHandles;
public static class NipatActivityNative {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry {
        public uint dwSize, cntUsage, th32ProcessID;
        public UIntPtr th32DefaultHeapID;
        public uint th32ModuleID, cntThreads, th32ParentProcessID;
        public int pcPriClassBase;
        public uint dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string szExeFile;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern SafeFileHandle CreateFileW(string name, uint access, uint sharing,
        IntPtr attributes, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint process);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32FirstW(IntPtr snapshot, ref ProcessEntry entry);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32NextW(IntPtr snapshot, ref ProcessEntry entry);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeWaitHandle OpenEventW(uint access, bool inherit, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    public static SafeFileHandle OpenExclusive(string path) {
        // OPEN_ALWAYS, GENERIC_READ, no sharing, non-inheritable (NULL security attributes).
        SafeFileHandle handle = CreateFileW(path, 0x80000000, 0, IntPtr.Zero, 4, 0x00200080, IntPtr.Zero);
        int error = Marshal.GetLastWin32Error();
        if (handle.IsInvalid) { handle.Dispose(); throw new Win32Exception(error); }
        return handle;
    }

    private static bool IsAncestor(uint candidate) {
        IntPtr snapshot = CreateToolhelp32Snapshot(2, 0);
        if (snapshot == new IntPtr(-1)) { return false; }
        var parents = new Dictionary<uint, uint>();
        try {
            var entry = new ProcessEntry();
            entry.dwSize = (uint)Marshal.SizeOf(typeof(ProcessEntry));
            bool found = Process32FirstW(snapshot, ref entry);
            while (found) {
                parents[entry.th32ProcessID] = entry.th32ParentProcessID;
                found = Process32NextW(snapshot, ref entry);
            }
        } finally { CloseHandle(snapshot); }
        uint current = (uint)Process.GetCurrentProcess().Id;
        var visited = new HashSet<uint>();
        for (int count = 0; count < 128; count++) {
            uint parent;
            if (!parents.TryGetValue(current, out parent) || parent == 0 || !visited.Add(parent)) { return false; }
            if (parent == candidate && parents.ContainsKey(parent)) { return true; }
            current = parent;
        }
        return false;
    }

    public static bool IsAuthorizedSetupChild(string token) {
        Match match = Regex.Match(token ?? "", @"\A([1-9][0-9]{0,9}):([a-f0-9]{32})\z");
        uint process;
        if (!match.Success || !UInt32.TryParse(match.Groups[1].Value, out process) || !IsAncestor(process)) { return false; }
        using (SafeWaitHandle handle = OpenEventW(0x00100000, false,
            "Local\\NIPAT-Desktop-SetupLease-" + match.Groups[2].Value)) {
            return !handle.IsInvalid;
        }
    }
}
