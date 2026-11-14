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

namespace Nipat {
    // The reviewed assembly owns one setup check and its descendants. Start
    // suspended so even a fast child cannot escape the job before assignment.
    public sealed class SetupCheckJob : IDisposable {
        [StructLayout(LayoutKind.Sequential)]
        private struct SecurityAttributes {
            public int length;
            public IntPtr descriptor;
            [MarshalAs(UnmanagedType.Bool)] public bool inherit;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct StartupInfo {
            public int cb;
            public string reserved, desktop, title;
            public int x, y, xSize, ySize, xCountChars, yCountChars, fillAttribute, flags;
            public short showWindow, reserved2Size;
            public IntPtr reserved2, input, output, error;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct ProcessInfo {
            public IntPtr process, thread;
            public int processId, threadId;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, uint code);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CreatePipe(out IntPtr read, out IntPtr write,
            ref SecurityAttributes attributes, int size);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(IntPtr handle, int mask, int flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CreateProcess(string application, System.Text.StringBuilder command,
            IntPtr processAttributes, IntPtr threadAttributes, bool inherit, uint flags,
            IntPtr environment, string directory, ref StartupInfo startup, out ProcessInfo process);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateProcess(IntPtr process, uint code);
        private IntPtr job;
        public System.IO.Stream Output { get; private set; }
        public System.IO.Stream Error { get; private set; }
        public SetupCheckJob() {
            job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        private static void Pipe(out IntPtr read, out IntPtr write, bool childReads) {
            SecurityAttributes attrs = new SecurityAttributes();
            attrs.length = Marshal.SizeOf(typeof(SecurityAttributes));
            attrs.inherit = true;
            if (!CreatePipe(out read, out write, ref attrs, 0))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            if (!SetHandleInformation(childReads ? write : read, 1, 0))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        private static void Close(ref IntPtr handle) {
            if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
        }
        public Process Start(string executable, string commandLine) {
            IntPtr outputRead = IntPtr.Zero, outputWrite = IntPtr.Zero;
            IntPtr errorRead = IntPtr.Zero, errorWrite = IntPtr.Zero;
            IntPtr inputRead = IntPtr.Zero, inputWrite = IntPtr.Zero;
            ProcessInfo child = new ProcessInfo();
            Process process = null;
            try {
                Pipe(out outputRead, out outputWrite, false);
                Pipe(out errorRead, out errorWrite, false);
                Pipe(out inputRead, out inputWrite, true);
                StartupInfo startup = new StartupInfo();
                startup.cb = Marshal.SizeOf(typeof(StartupInfo));
                startup.flags = 0x100; // STARTF_USESTDHANDLES
                startup.input = inputRead; startup.output = outputWrite; startup.error = errorWrite;
                if (!CreateProcess(executable, new System.Text.StringBuilder(commandLine),
                        IntPtr.Zero, IntPtr.Zero, true, 0x08000004, // NO_WINDOW | SUSPENDED
                        IntPtr.Zero, null, ref startup, out child))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                if (!AssignProcessToJobObject(job, child.process))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                Output = new System.IO.FileStream(new SafeFileHandle(outputRead, true), System.IO.FileAccess.Read);
                outputRead = IntPtr.Zero;
                Error = new System.IO.FileStream(new SafeFileHandle(errorRead, true), System.IO.FileAccess.Read);
                errorRead = IntPtr.Zero;
                // Retain a handle before resuming even a process that exits immediately.
                process = Process.GetProcessById(child.processId);
                IntPtr retained = process.Handle;
                if (ResumeThread(child.thread) == UInt32.MaxValue)
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                return process;
            } catch {
                if (child.process != IntPtr.Zero) TerminateProcess(child.process, 124);
                if (process != null) process.Dispose();
                throw;
            } finally {
                Close(ref outputRead); Close(ref outputWrite);
                Close(ref errorRead); Close(ref errorWrite);
                Close(ref inputRead); Close(ref inputWrite); // EOF, never a setup prompt
                Close(ref child.process); Close(ref child.thread);
            }
        }
        public void Stop() {
            if (job != IntPtr.Zero && !TerminateJobObject(job, 124))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        public void Dispose() {
            try {
                if (job != IntPtr.Zero) {
                    try { Stop(); } finally { CloseHandle(job); job = IntPtr.Zero; }
                }
            } finally {
                if (Output != null) Output.Dispose();
                if (Error != null) Error.Dispose();
            }
        }
    }
}
