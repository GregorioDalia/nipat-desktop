param([string] $LauncherPath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "Launcher check failed: $Message" }
    $script:checks++
}

# An executable or PowerShell may expand an inherited 8.3 TEMP path. Compare
# existing paths by their long spelling rather than treating that as a cwd change.
if (-not ('NipatLauncherTestPaths' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
public static class NipatLauncherTestPaths
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetLongPathName(string path, StringBuilder buffer, uint size);

    public static string Normalize(string path)
    {
        path = Path.GetFullPath(path);
        var buffer = new StringBuilder(1024);
        uint length = GetLongPathName(path, buffer, (uint)buffer.Capacity);
        if (length >= buffer.Capacity) {
            buffer.Capacity = checked((int)length);
            length = GetLongPathName(path, buffer, (uint)buffer.Capacity);
        }
        if (length == 0 || length >= buffer.Capacity) {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return buffer.ToString();
    }
}
'@
}

function Test-SamePath([string] $Actual, [string] $Expected) {
    return [string]::Equals(
        [NipatLauncherTestPaths]::Normalize($Actual),
        [NipatLauncherTestPaths]::Normalize($Expected),
        [StringComparison]::OrdinalIgnoreCase)
}

function ConvertTo-WindowsArgument([AllowEmptyString()][string] $Value) {
    $result = New-Object Text.StringBuilder
    [void]$result.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes++
        } elseif ($character -eq '"') {
            [void]$result.Append([char]'\', $slashes * 2 + 1)
            [void]$result.Append($character)
            $slashes = 0
        } else {
            [void]$result.Append([char]'\', $slashes)
            [void]$result.Append($character)
            $slashes = 0
        }
    }
    [void]$result.Append([char]'\', $slashes * 2)
    [void]$result.Append('"')
    return $result.ToString()
}

function Invoke-TestLauncher([string] $Executable, [string[]] $Arguments = @(), [int] $ExitCode = 0, [hashtable] $Environment = @{}, [switch] $BatchFile) {
    if (Test-Path -LiteralPath $script:CapturePath) { Remove-Item -LiteralPath $script:CapturePath }
    $start = New-Object Diagnostics.ProcessStartInfo
    if ($BatchFile) {
        if ($Arguments.Count -ne 0) { throw 'The guided batch entry point takes no arguments.' }
        $start.FileName = Join-Path $env:WINDIR 'System32\cmd.exe'
        # cmd /s removes the outer pair; the inner quotes protect spaces and &.
        $start.Arguments = '/d /s /c ""' + $Executable + '""'
    } else {
        $start.FileName = $Executable
        $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' ')
    }
    $start.WorkingDirectory = $script:CallerDirectory
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables['NIPAT_LAUNCH_TEST_CAPTURE'] = $script:CapturePath
    $start.EnvironmentVariables['NIPAT_LAUNCH_TEST_EXIT'] = [string]$ExitCode
    foreach ($name in $Environment.Keys) {
        if ($null -eq $Environment[$name]) { $start.EnvironmentVariables.Remove($name) }
        else { $start.EnvironmentVariables[$name] = [string]$Environment[$name] }
    }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(20000)) {
            $process.Kill()
            throw 'Launcher did not return within 20 seconds; possible unwanted pause.'
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = $stdout.Result + $stderr.Result
        }
    } finally {
        $process.Dispose()
    }
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-launcher-test-' + [Guid]::NewGuid().ToString('N'))
try {
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    # Model the full directory spelling recorded by the installer, even when
    # the runner inherited an 8.3 TEMP environment variable.
    $temporary = [NipatLauncherTestPaths]::Normalize($temporary)
    if ([string]::IsNullOrWhiteSpace($LauncherPath)) {
        $LauncherPath = Join-Path $temporary 'compiled\NIPAT.exe'
        & (Join-Path $PSScriptRoot 'build-launcher.ps1') -OutputPath $LauncherPath
    }
    $source = (Get-Item -LiteralPath $LauncherPath -ErrorAction Stop).FullName
    $app = Join-Path $temporary ('NIPAT app & [literal] ' + [char]0x00E8)
    $script:CallerDirectory = Join-Path $temporary 'caller working directory'
    $script:CapturePath = Join-Path $temporary 'received.json'
    [IO.Directory]::CreateDirectory($script:CallerDirectory) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $app 'installer\windows')) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $app 'scripts\windows')) | Out-Null
    $executable = Join-Path $app 'NIPAT.exe'
    Copy-Item -LiteralPath $source -Destination $executable
    $project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $guidedCommand = Join-Path $app '2_AVVIA.cmd'
    Copy-Item -LiteralPath (Join-Path $project '2_AVVIA.cmd') -Destination $guidedCommand
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launch.ps1') -Destination (Join-Path $app 'installer\windows\launch.ps1')
    $runner = Join-Path $app 'scripts\windows\run.ps1'
    @'
$record = [pscustomobject]@{
    arguments = @($args)
    working_directory = (Get-Location).Path
    script_path = $PSCommandPath
    bridge_arguments_removed = [string]::IsNullOrEmpty($env:NIPAT_LAUNCH_ARGUMENTS)
    bridge_count_removed = [string]::IsNullOrEmpty($env:NIPAT_LAUNCH_ARGUMENT_COUNT)
}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $env:NIPAT_LAUNCH_TEST_CAPTURE -Encoding UTF8
exit ([int]$env:NIPAT_LAUNCH_TEST_EXIT)
'@ | Set-Content -LiteralPath $runner -Encoding UTF8

    $result = Invoke-TestLauncher -Executable $executable
    Assert-Test ($result.ExitCode -eq 0) ('default launch exit code: ' + $result.Output)
    $record = Get-Content -LiteralPath $script:CapturePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($record.arguments.Count -eq 1 -and $record.arguments[0] -ceq 'wizard') 'double-click defaults to wizard'
    Assert-Test (Test-SamePath $record.working_directory $script:CallerDirectory) 'caller working directory preserved'
    Assert-Test (Test-SamePath $record.script_path $runner) 'runner is relative to the executable, not the current directory'
    Assert-Test ($record.bridge_arguments_removed -and $record.bridge_count_removed) 'temporary launch data removed before running NIPAT'

    # The installer shortcut opens this exact batch file. Closed stdin lets its
    # final pause return in CI without replacing the command or its runner.
    $result = Invoke-TestLauncher -Executable $guidedCommand -BatchFile -ExitCode 23
    Assert-Test ($result.ExitCode -eq 23) ('guided command preserves failure through its final pause: ' + $result.Output)
    $record = Get-Content -LiteralPath $script:CapturePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($record.arguments.Count -eq 1 -and $record.arguments[0] -ceq 'wizard') 'guided command opens wizard with a fixed argument'
    Assert-Test (Test-SamePath $record.working_directory $script:CallerDirectory) 'guided command preserves caller working directory'
    Assert-Test (Test-SamePath $record.script_path $runner) 'guided command finds its runner in a path containing spaces, ampersand and Unicode'

    $argumentList = @(
        '--runs-dir', 'C:\folder with spaces\', '--dry-run', 'wizard', '',
        'quoted "value"', 'ends-with-backslash\', 'two\\slashes',
        "apostrophe's & [brackets]", '$HOME; $(throw ''must not execute'')',
        ('unicode ' + [char]0x00E8 + [char]0x03B1), "line one`nline two"
    )
    $result = Invoke-TestLauncher -Executable $executable -Arguments $argumentList -ExitCode 23
    Assert-Test ($result.ExitCode -eq 23) ('runner exit code preserved: ' + $result.Output)
    $record = Get-Content -LiteralPath $script:CapturePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($record.arguments.Count -eq $argumentList.Count) 'all arguments including empty values preserved'
    for ($index = 0; $index -lt $argumentList.Count; $index++) {
        Assert-Test ($record.arguments[$index] -ceq $argumentList[$index]) "argument $index is literal data"
    }
    Assert-Test (Test-SamePath $record.working_directory $script:CallerDirectory) 'explicit CLI arguments preserve caller directory'

    $result = Invoke-TestLauncher -Executable $executable -Arguments @('')
    Assert-Test ($result.ExitCode -eq 0) ('empty sole argument exit code: ' + $result.Output)
    $record = Get-Content -LiteralPath $script:CapturePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($record.arguments.Count -eq 1 -and $record.arguments[0] -ceq '') 'one empty argument does not become wizard'

    Remove-Item -LiteralPath $runner
    $result = Invoke-TestLauncher -Executable $executable
    Assert-Test ($result.ExitCode -eq 1) 'missing package files return a failure without hanging CI'
    Assert-Test ($result.Output -match 'Pacchetto NIPAT incompleto') 'incomplete package has an actionable error'
    Assert-Test (-not (Test-Path -LiteralPath $script:CapturePath)) 'missing runner is never invoked'

    # Exercise the actual bridge, runner and installed readiness checks. Python
    # is an offline process fixture; no WSL or scientific analysis is simulated.
    foreach ($name in @('common.ps1', 'setup.ps1', 'run.ps1')) {
        Copy-Item -LiteralPath (Join-Path $project "scripts\windows\$name") -Destination (Join-Path $app "scripts\windows\$name")
    }
    $metadata = Get-Content -LiteralPath (Join-Path $project 'pyproject.toml') -Raw
    $version = [regex]::Match($metadata, '(?m)^version\s*=\s*"([^"]+)"').Groups[1].Value
    $distribution = Join-Path $app '.distribution'
    [IO.Directory]::CreateDirectory($distribution) | Out-Null
    $fakeSource = Join-Path $temporary 'FixturePython.cs'
    $fakePython = Join-Path $temporary 'FixturePython.exe'
    @'
using System;
using System.IO;
using System.Linq;
using System.Text;
class FixturePython {
    static string Encode(string value) { return Convert.ToBase64String(Encoding.UTF8.GetBytes(value ?? "")); }
    static int Main(string[] args) {
        if (String.Equals(Path.GetFileName(Environment.GetCommandLineArgs()[0]), "powershell.exe", StringComparison.OrdinalIgnoreCase)) {
            File.AppendAllText(Environment.GetEnvironmentVariable("NIPAT_FIXTURE_EVENTS"), "decoy:powershell\n");
            return 91;
        }
        string command = args.Contains("wizard") ? "wizard" : (args.Length > 2 ? args[2] : "other");
        File.AppendAllText(Environment.GetEnvironmentVariable("NIPAT_FIXTURE_EVENTS"), "python:" + command + "\n");
        if (command == "self-test" && File.Exists(Environment.GetEnvironmentVariable("NIPAT_FIXTURE_FAIL"))) return 17;
        if (command == "wizard") {
            string[] record = new string[] { Directory.GetCurrentDirectory(),
                Environment.GetEnvironmentVariable("NIPAT_BACKEND"),
                Environment.GetEnvironmentVariable("NIPAT_DATA_DIR"),
                Environment.GetEnvironmentVariable("NIPAT_RUNS_DIR"),
                Environment.GetEnvironmentVariable("NIPAT_WORKSPACE_DIR"),
                Environment.GetEnvironmentVariable("NIPAT_WSL_DISTRO"),
                Environment.GetEnvironmentVariable("NIPAT_RUNTIME_IMAGE"),
                Environment.GetEnvironmentVariable("NIPAT_PROJECT_DIR") }.Concat(args).Select(Encode).ToArray();
            File.WriteAllLines(Environment.GetEnvironmentVariable("NIPAT_LAUNCH_TEST_CAPTURE"), record);
        }
        return 0;
    }
}
'@ | Set-Content -LiteralPath $fakeSource -Encoding UTF8
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $compiler /nologo /target:exe /platform:x64 "/out:$fakePython" $fakeSource
    if ($LASTEXITCODE -ne 0) { throw 'Could not compile the offline Python process fixture.' }
    $pythonDirectory = Join-Path $app '.runtime\python'
    [IO.Directory]::CreateDirectory($pythonDirectory) | Out-Null
    Copy-Item -LiteralPath $fakePython -Destination (Join-Path $pythonDirectory 'python.exe')
    $events = Join-Path $temporary 'events.txt'
    $fail = Join-Path $temporary 'self-test-failure.flag'
    $localAppData = Join-Path $temporary 'user profile'
    $environment = @{
        NIPAT_FIXTURE_PYTHON = $fakePython; NIPAT_FIXTURE_EVENTS = $events; NIPAT_FIXTURE_FAIL = $fail
        LOCALAPPDATA = $localAppData; NIPAT_WORKSPACE_DIR = $null; NIPAT_DATA_DIR = $null; NIPAT_RUNS_DIR = $null
        NIPAT_BACKEND = 'wsl'; NIPAT_WSL_DISTRO = 'Unrelated-WSL'; NIPAT_RUNTIME_IMAGE = $null
    }
    # Exercise the ready WSL Desktop through the compiled executable and real
    # launch scripts. Scientific execution remains at the fake Python boundary.
    foreach ($name in @('bootstrap-common.ps1', 'install-profile.ps1', 'install-profile.json', 'install-layout.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $app "installer\windows\$name")
    }
    $profile = Get-Content -LiteralPath (Join-Path $app 'installer\windows\install-profile.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $profileChannel = [string]$profile.channel
    $candidateBase = Join-Path $localAppData $profile.data_dir_name
    $candidateData = Join-Path $candidateBase 'data'
    $candidateRuns = Join-Path $candidateBase 'runs'
    [IO.Directory]::CreateDirectory($candidateData) | Out-Null
    [IO.Directory]::CreateDirectory($candidateRuns) | Out-Null
    $rootfsHash = 'd' * 64
    $distro = $profile.distro_prefix + $rootfsHash.Substring(0, 40)
    $manifestPath = Join-Path $distribution 'installer-manifest.json'
    $manifest = [ordered]@{
        schema_version = 1; version = $version; release_tag = ('v' + $version)
        source_commit = 'e' * 40; runtime_image = ('sha256:' + ('a' * 64))
        installation_profile = $profile
        assets = @{
            rootfs = @{ file = ('rootfs-' + $version + '.tar.gz'); sha256 = $rootfsHash; size = 10
                url = ('https://github.com/GregorioDalia/nipat-desktop/releases/download/v' + $version + '/rootfs-' + $version + '.tar.gz') }
            scientific_image = @{ file = ('scientific-' + $version + '.tar.gz'); sha256 = ('f' * 64); size = 20
                url = ('https://github.com/GregorioDalia/nipat-desktop/releases/download/v' + $version + '/scientific-' + $version + '.tar.gz') }
        }
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $backendPath = Join-Path $app '.runtime\backend.json'
    $backend = [ordered]@{
        schema_version = 1; backend = 'wsl'; installation_channel = $profile.channel
        wsl_distro = $distro; rootfs_sha256 = $rootfsHash
        runtime_image = ('sha256:' + ('b' * 64)); source_runtime_image = $manifest.runtime_image
        source_commit = $manifest.source_commit; release_tag = $manifest.release_tag
        runtime_archive_sha256 = $manifest.assets.scientific_image.sha256
        data_dir = $candidateData; runs_dir = $candidateRuns
    }
    $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
    $stateDirectory = Join-Path $app '.runtime\installer'
    [IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
    $statePath = Join-Path $stateDirectory 'state.json'
    $state = [ordered]@{
        schema_version = 1; phase = 'ready'; installation_channel = $profile.channel
        source_commit = $manifest.source_commit; runtime_image = $manifest.runtime_image
        wsl_distro = $distro; rootfs_sha256 = $rootfsHash
        resolved_runtime_image = $backend.runtime_image
        runtime_archive_sha256 = $manifest.assets.scientific_image.sha256
    }
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $stableBase = Join-Path $localAppData 'NIPAT'
    $stableData = Join-Path $stableBase 'data'
    $stableRuns = Join-Path $stableBase 'runs'
    [IO.Directory]::CreateDirectory($stableData) | Out-Null
    [IO.Directory]::CreateDirectory($stableRuns) | Out-Null
    $stableMarker = Join-Path $stableBase 'stable-sentinel.txt'
    'stable installation untouched' | Set-Content -LiteralPath $stableMarker -Encoding ASCII
    $stableHash = (Get-FileHash -LiteralPath $stableMarker -Algorithm SHA256).Hash
    $environment.NIPAT_PROJECT_DIR = Join-Path $localAppData 'Programs\NIPAT'
    $environment.NIPAT_WORKSPACE_DIR = $stableBase
    $environment.NIPAT_DATA_DIR = $stableData
    $environment.NIPAT_RUNS_DIR = $stableRuns
    $environment.NIPAT_BACKEND = 'native'
    $environment.NIPAT_WSL_DISTRO = 'NIPAT-Runtime'
    $environment.NIPAT_RUNTIME_IMAGE = 'sha256:' + ('c' * 64)
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('ready Desktop launches from a stable configured shell: ' + $result.Output)
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ($capture[1] -ceq 'wsl' -and $capture[5] -ceq $distro -and $capture[6] -ceq $backend.runtime_image) 'Desktop selects only its verified WSL distribution and image'
    Assert-Test ((Test-SamePath $capture[2] $candidateData) -and (Test-SamePath $capture[3] $candidateRuns) -and
        (Test-SamePath $capture[4] $candidateBase) -and (Test-SamePath $capture[7] $app)) 'installed Desktop resets inherited stable project, workspace, data and runs'
    Assert-Test ($capture[8] -ceq '-m' -and $capture[9] -ceq 'nipat' -and $capture[10] -ceq 'wizard') 'ready Desktop opens the guided CLI without preparation'

    # A researcher may launch from a data folder containing executables. The
    # command must use Windows PowerShell itself, not a same-named local file.
    $decoyShell = Join-Path $script:CallerDirectory 'powershell.exe'
    Copy-Item -LiteralPath $fakePython -Destination $decoyShell
    try {
        $result = Invoke-TestLauncher -Executable $guidedCommand -BatchFile -Environment $environment
    } finally {
        Remove-Item -LiteralPath $decoyShell
    }
    Assert-Test ($result.ExitCode -eq 0) ('ready Desktop opens through the installer guided command: ' + $result.Output)
    Assert-Test (-not (@(Get-Content -LiteralPath $events) -contains 'decoy:powershell')) 'guided command does not execute PowerShell from the caller data directory'
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ($capture[1] -ceq 'wsl' -and $capture[5] -ceq $distro -and $capture[6] -ceq $backend.runtime_image) 'guided command selects the verified Desktop distribution and image'
    Assert-Test ((Test-SamePath $capture[0] $script:CallerDirectory) -and
        (Test-SamePath $capture[2] $candidateData) -and (Test-SamePath $capture[3] $candidateRuns) -and
        (Test-SamePath $capture[4] $candidateBase) -and (Test-SamePath $capture[7] $app)) 'guided command preserves cwd while isolating Desktop paths from inherited stable settings'
    Assert-Test ($capture[8] -ceq '-m' -and $capture[9] -ceq 'nipat' -and $capture[10] -ceq 'wizard') 'guided command reaches the same Python CLI'

    $explicitRuns = Join-Path $temporary 'explicit user results'
    $result = Invoke-TestLauncher -Executable $executable -Arguments @('--runs-dir', $explicitRuns, 'wizard') -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('Desktop preserves explicit output override: ' + $result.Output)
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ($capture[10] -ceq '--runs-dir' -and $capture[11] -ceq $explicitRuns -and $capture[12] -ceq 'wizard') 'explicit CLI output directory reaches Python unchanged'

    # Exercise the actual installed bridge with independent destinations. Keep
    # the earlier metadata for the legacy-path checks that follow this section.
    . (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
    $oldBackendJson = $backend | ConvertTo-Json -Depth 8
    $oldStateJson = $state | ConvertTo-Json -Depth 8
    $layoutPath = Join-Path $app '.runtime\install-layout.json'
    $layout = [ordered]@{
        schema_version = 1; installation_channel = $profileChannel; app_dir = $app
        runtime_dir = (Join-Path $temporary ('runtime & [selected] ' + [char]0x00E8))
        cache_dir = (Join-Path $temporary 'download cache')
        data_dir = (Join-Path $temporary 'research inputs')
        runs_dir = (Join-Path $temporary 'research results')
    }
    foreach ($name in @('runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        [IO.Directory]::CreateDirectory($layout[$name]) | Out-Null
    }
    foreach ($kind in @('runtime', 'cache')) {
        @('[NIPAT]', 'schema_version=1', ('installation_channel=' + $profileChannel), ('role=' + $kind)) |
            Set-Content -LiteralPath (Join-Path $layout[$kind + '_dir'] '.nipat-storage.ini') -Encoding ASCII
    }
    $inputSentinel = Join-Path $layout.data_dir 'existing input.txt'
    $resultSentinel = Join-Path $layout.runs_dir 'existing result.txt'
    'input unchanged' | Set-Content -LiteralPath $inputSentinel -Encoding ASCII
    'result unchanged' | Set-Content -LiteralPath $resultSentinel -Encoding ASCII
    $inputHash = (Get-FileHash -LiteralPath $inputSentinel -Algorithm SHA256).Hash
    $resultHash = (Get-FileHash -LiteralPath $resultSentinel -Algorithm SHA256).Hash
    $customDistro = Get-NipatRuntimeDistroName $rootfsHash $layout.runtime_dir
    foreach ($name in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        $backend[$name] = $layout[$name]
        $state[$name] = $layout[$name]
    }
    $backend.wsl_distro = $customDistro
    $state.wsl_distro = $customDistro
    $layout | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $layoutPath -Encoding UTF8
    $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $guidedCommand -BatchFile -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('custom installation launches from the guided shortcut entry point: ' + $result.Output)
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ($capture[5] -ceq $customDistro -and
        (Test-SamePath $capture[2] $layout.data_dir) -and (Test-SamePath $capture[3] $layout.runs_dir) -and
        (Test-SamePath $capture[7] $app)) 'the selected runtime and independent data/result directories reach the client'
    $beforeLayoutRejections = @(Get-Content -LiteralPath $events).Count
    Remove-Item -LiteralPath $layoutPath
    $result = Invoke-TestLauncher -Executable $guidedCommand -BatchFile -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'new destination-bound metadata requires the matching installation layout'
    $layout | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $layoutPath -Encoding UTF8
    foreach ($name in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        $backend[$name] = Join-Path $temporary ('different-' + $name)
        $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
        $result = Invoke-TestLauncher -Executable $guidedCommand -BatchFile -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) ("changed backend $name is rejected before Python")
        $backend[$name] = $layout[$name]
    }
    $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
    $state.runtime_dir = Join-Path $temporary 'different state runtime'
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'a readiness state for another destination cannot authorize the selected backend'
    $state.runtime_dir = $layout.runtime_dir
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $layout.app_dir = Join-Path $temporary 'another application'
    $layout | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $layoutPath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'a layout for a different application directory is rejected'
    Assert-Test (@(Get-Content -LiteralPath $events).Count -eq $beforeLayoutRejections) 'invalid destination bindings never reach Python'
    Assert-Test ((Get-FileHash -LiteralPath $inputSentinel -Algorithm SHA256).Hash -ceq $inputHash -and
        (Get-FileHash -LiteralPath $resultSentinel -Algorithm SHA256).Hash -ceq $resultHash) 'custom-location launch and rejection checks preserve existing inputs and results'
    Remove-Item -LiteralPath $layoutPath
    $oldBackendJson | Set-Content -LiteralPath $backendPath -Encoding UTF8
    $oldStateJson | Set-Content -LiteralPath $statePath -Encoding UTF8
    $backend = $oldBackendJson | ConvertFrom-Json
    $state = $oldStateJson | ConvertFrom-Json

    $beforeRejected = @(Get-Content -LiteralPath $events).Count
    foreach ($foreignChannel in @('stable', 'preview-0.5', $null)) {
        $backend.installation_channel = $foreignChannel
        $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
        $result = Invoke-TestLauncher -Executable $executable -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'foreign or markerless backend never reaches Python'
    }
    $backend.installation_channel = $profile.channel
    foreach ($foreignDistro in @('NIPAT-Runtime', ('NIPAT-05-Preview-' + $rootfsHash.Substring(0, 40)))) {
        $backend.wsl_distro = $foreignDistro
        $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
        $result = Invoke-TestLauncher -Executable $executable -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'Desktop backend cannot select a stable or Preview WSL distribution'
    }
    $backend.wsl_distro = $distro
    $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
    foreach ($foreignChannel in @('stable', 'preview-0.5')) {
        $state.installation_channel = $foreignChannel
        $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
        $result = Invoke-TestLauncher -Executable $executable -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'a foreign readiness state cannot authorize a Desktop launch'
    }
    $state.installation_channel = $profile.channel
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $manifest.installation_profile.channel = 'stable'
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'foreign installer manifest is rejected before running Python'
    Assert-Test (@(Get-Content -LiteralPath $events).Count -eq $beforeRejected) 'rejected installed identities execute neither setup nor analysis'
    Assert-Test ((Get-FileHash -LiteralPath $stableMarker -Algorithm SHA256).Hash -ceq $stableHash) 'launches and rejected identities preserve stable data'

    # Incomplete, failed and mismatched installation states never reach Python.
    $manifest.installation_profile.channel = $profileChannel
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    foreach ($phase in @('failed', 'awaiting_reboot', 'verifying_installation')) {
        $state.phase = $phase
        $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
        $result = Invoke-TestLauncher -Executable $executable -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) ("phase $phase does not authorize an analysis")
        Assert-Test ($result.Output -match 'completa preparazione') 'incomplete installation directs the user to the setup shortcut'
        $result = Invoke-TestLauncher -Executable $guidedCommand -BatchFile -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) ("guided command rejects phase $phase before Python")
        Assert-Test ($result.Output -match 'completa preparazione') 'guided command preserves setup recovery guidance'
    }
    $state.phase = 'ready'
    $state.source_commit = '1' * 40
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'state for another source commit is rejected'
    $state.source_commit = $manifest.source_commit
    $state.runtime_archive_sha256 = '2' * 64
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'state for another scientific archive is rejected'
    $result = Invoke-TestLauncher -Executable $guidedCommand -BatchFile -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'guided command rejects a state bound to another scientific archive'
    Remove-Item -LiteralPath $statePath
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'missing readiness state is rejected'
    $state.runtime_archive_sha256 = $manifest.assets.scientific_image.sha256
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('a verified ready state permits the next launch: ' + $result.Output)
    $pythonPath = Join-Path $pythonDirectory 'python.exe'
    Remove-Item -LiteralPath $pythonPath
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'missing packaged Python does not start analysis'
    Assert-Test ($result.Output -match 'completa preparazione') 'missing packaged Python offers the setup shortcut'
    Copy-Item -LiteralPath $fakePython -Destination $pythonPath

    # Setup dispatches installed packages to the WSL bootstrap and preserves a
    # reboot-required result. Bootstrap state transitions are covered separately.
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $setup = Join-Path $app 'scripts\windows\setup.ps1'
    @'
Add-Content -LiteralPath $env:NIPAT_FIXTURE_EVENTS -Value 'bootstrap:wsl'
exit 3010
'@ | Set-Content -LiteralPath (Join-Path $app 'installer\windows\bootstrap.ps1') -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $powershell -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup) -Environment $environment
    Assert-Test ($result.ExitCode -eq 3010) ('installed setup preserves WSL reboot-required status: ' + $result.Output)
    Assert-Test ((Get-Content -LiteralPath $events -Tail 1) -ceq 'bootstrap:wsl') 'installed setup delegates to the WSL bootstrap'

    # Source launch retains deliberate developer paths. Source setup requires an
    # explicit WSL configuration before it installs Python or creates directories.
    Remove-Item -LiteralPath $manifestPath
    Remove-Item -LiteralPath $backendPath
    $environment.NIPAT_BACKEND = 'wsl'
    $environment.NIPAT_WSL_DISTRO = 'NIPAT-Development'
    $environment.NIPAT_RUNTIME_IMAGE = 'sha256:' + ('c' * 64)
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('source launch keeps explicit environment configuration: ' + $result.Output)
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ((Test-SamePath $capture[2] $stableData) -and (Test-SamePath $capture[3] $stableRuns) -and
        (Test-SamePath $capture[4] $stableBase)) 'source checkouts retain deliberate environment data, results and workspace'
    Assert-Test ($capture[1] -ceq 'wsl' -and $capture[5] -ceq 'NIPAT-Development') 'source launch preserves the explicit WSL distribution'
    @'

# Offline replacement of the external Python download/install boundary.
function Install-NipatPython([string] $Project) {
    Add-Content -LiteralPath $env:NIPAT_FIXTURE_EVENTS -Value 'install:python'
    return (Get-NipatPython $Project)
}
'@ | Add-Content -LiteralPath (Join-Path $app 'scripts\windows\common.ps1') -Encoding UTF8
    $beforeSourceSetup = @(Get-Content -LiteralPath $events).Count
    foreach ($invalid in @(
        @{ NIPAT_BACKEND = 'native'; NIPAT_WSL_DISTRO = 'NIPAT-Development'; NIPAT_RUNTIME_IMAGE = ('sha256:' + ('c' * 64)) },
        @{ NIPAT_BACKEND = 'wsl'; NIPAT_WSL_DISTRO = ''; NIPAT_RUNTIME_IMAGE = ('sha256:' + ('c' * 64)) },
        @{ NIPAT_BACKEND = 'wsl'; NIPAT_WSL_DISTRO = 'NIPAT-Development'; NIPAT_RUNTIME_IMAGE = 'mutable:tag' }
    )) {
        $invalidEnvironment = $environment.Clone()
        foreach ($name in $invalid.Keys) { $invalidEnvironment[$name] = $invalid[$name] }
        $result = Invoke-TestLauncher -Executable $powershell -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup) -Environment $invalidEnvironment
        Assert-Test ($result.ExitCode -ne 0 -and $result.Output -match 'NIPAT-Setup.exe') 'source setup rejects incomplete or native runtime configuration with installer guidance'
    }
    Assert-Test (@(Get-Content -LiteralPath $events).Count -eq $beforeSourceSetup) 'invalid source configuration starts neither Python installation nor analysis'
    $sourceLock = [IO.File]::Open((Join-Path $app '.runtime\source-setup.lock'),
        [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        $result = Invoke-TestLauncher -Executable $powershell -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup) -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and $result.Output -match 'gia in corso') 'concurrent source setup is rejected before client changes'
        Assert-Test (@(Get-Content -LiteralPath $events).Count -eq $beforeSourceSetup) 'a held source lock prevents Python installation and analysis'
    } finally { $sourceLock.Dispose() }
    $result = Invoke-TestLauncher -Executable $powershell -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup) -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('configured WSL source client setup succeeds: ' + $result.Output)
    $setupCalls = @(Get-Content -LiteralPath $events | Select-Object -Skip $beforeSourceSetup)
    Assert-Test (($setupCalls -join ',') -ceq 'install:python,python:doctor,python:self-test') 'source setup prepares only Python then verifies the configured scientific image'
    'fail' | Set-Content -LiteralPath $fail -Encoding ASCII
    $result = Invoke-TestLauncher -Executable $powershell -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup) -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and $result.Output -match 'Autotest non superati') 'source setup propagates a failed scientific self-test'
    Assert-Test ((Get-FileHash -LiteralPath $stableMarker -Algorithm SHA256).Hash -ceq $stableHash) 'all launch and setup checks preserve existing user data'
    Write-Host "PASS: $checks launcher assertions."
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
