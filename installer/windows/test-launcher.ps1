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

function Invoke-TestLauncher([string] $Executable, [string[]] $Arguments = @(), [int] $ExitCode = 0, [hashtable] $Environment = @{}) {
    if (Test-Path -LiteralPath $script:CapturePath) { Remove-Item -LiteralPath $script:CapturePath }
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $Executable
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' ')
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

    # Exercise the compiled launcher through the real bridge, runner, setup and
    # readiness state. Only external Python installation and Docker are simulated;
    # these tests must not download software or require a daemon on the CI host.
    $project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    foreach ($name in @('common.ps1', 'portable-bootstrap.ps1', 'setup.ps1', 'run.ps1')) {
        Copy-Item -LiteralPath (Join-Path $project "scripts\windows\$name") -Destination (Join-Path $app "scripts\windows\$name")
    }
    Copy-Item -LiteralPath (Join-Path $project 'pyproject.toml') -Destination (Join-Path $app 'pyproject.toml')
    $metadata = Get-Content -LiteralPath (Join-Path $app 'pyproject.toml') -Raw
    $version = [regex]::Match($metadata, '(?m)^version\s*=\s*"([^"]+)"').Groups[1].Value
    $distribution = Join-Path $app '.distribution'
    [IO.Directory]::CreateDirectory($distribution) | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $distribution 'runtime.tar'), [byte[]]@(1, 2, 3, 4))
    [IO.File]::WriteAllBytes((Join-Path $distribution 'python-3.12.10-embed-amd64.zip'), [byte[]]@(1))
    $runtime = [ordered]@{
        schema_version = 1; os = 'linux'; architecture = 'amd64'
        image_id = 'sha256:' + ('a' * 64); source_commit = 'c' * 40; archive_bytes = 4
        archive_sha256 = (Get-FileHash -LiteralPath (Join-Path $distribution 'runtime.tar') -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $runtime | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $distribution 'runtime.json') -Encoding UTF8
    [ordered]@{
        schema_version = 1; package_version = $version
        source_git = @{ available = $true; dirty = $false; commit = $runtime.source_commit }
        python = @{ version = '3.12.10'; architecture = 'amd64'; archive_sha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3' }
        runtime = $runtime
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $app 'release.json') -Encoding UTF8
    @{ schema_version = 1; distribution = 'docker-desktop-installer' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $distribution 'docker-desktop.json') -Encoding UTF8

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
    @'

# Test-only external dependency boundaries appended to an isolated project copy.
function Assert-NipatDocker { }
function Install-NipatPython([string] $Project) {
    Add-Content -LiteralPath $env:NIPAT_FIXTURE_EVENTS -Value 'install:python'
    $directory = Join-Path $Project '.runtime\python'
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    Copy-Item -LiteralPath $env:NIPAT_FIXTURE_PYTHON -Destination (Get-NipatPython $Project) -Force
    '3.12.10' | Set-Content -LiteralPath (Join-Path $directory 'nipat-python.ready') -Encoding ASCII
    '.' | Set-Content -LiteralPath (Join-Path $directory 'python312._pth') -Encoding ASCII
    return (Get-NipatPython $Project)
}
function Install-NipatRuntime([string] $Project) {
    Add-Content -LiteralPath $env:NIPAT_FIXTURE_EVENTS -Value 'install:runtime'
    $image = 'sha256:' + ('b' * 64)
    $image | Set-Content -LiteralPath (Join-Path $Project '.runtime\runtime-image.txt') -Encoding ASCII
    $env:NIPAT_RUNTIME_IMAGE = $image
}
function Get-NipatImage([string] $Image) {
    if ($Image -ceq ('sha256:' + ('b' * 64))) {
        return [pscustomobject]@{ Id = $Image; Os = 'linux'; Architecture = 'amd64' }
    }
    return $null
}
'@ | Add-Content -LiteralPath (Join-Path $app 'scripts\windows\common.ps1') -Encoding UTF8
    $events = Join-Path $temporary 'events.txt'
    $fail = Join-Path $temporary 'self-test-failure.flag'
    $localAppData = Join-Path $temporary 'user profile'
    $data = Join-Path $localAppData 'NIPAT-DockerDesktop\data'
    $runs = Join-Path $localAppData 'NIPAT-DockerDesktop\runs'
    [IO.Directory]::CreateDirectory($data) | Out-Null
    [IO.Directory]::CreateDirectory($runs) | Out-Null
    'existing input' | Set-Content -LiteralPath (Join-Path $data 'preserved.txt') -Encoding ASCII
    'existing result' | Set-Content -LiteralPath (Join-Path $runs 'preserved.txt') -Encoding ASCII
    $environment = @{
        NIPAT_FIXTURE_PYTHON = $fakePython; NIPAT_FIXTURE_EVENTS = $events; NIPAT_FIXTURE_FAIL = $fail
        LOCALAPPDATA = $localAppData; NIPAT_WORKSPACE_DIR = $null; NIPAT_DATA_DIR = $null; NIPAT_RUNS_DIR = $null
        NIPAT_BACKEND = 'wsl'; NIPAT_WSL_DISTRO = 'Unrelated-WSL'; NIPAT_RUNTIME_IMAGE = $null
    }
    $readyPath = Join-Path $app '.runtime\portable-setup.json'
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('real first-launch preparation succeeds: ' + $result.Output)
    Assert-Test (Test-Path -LiteralPath $readyPath) 'real setup writes readiness only after checks'
    $calls = @(Get-Content -LiteralPath $events)
    Assert-Test (($calls -join ',') -ceq 'install:python,install:runtime,python:doctor,python:self-test,python:wizard') 'first launch prepares, checks and opens the menu in order'
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test (Test-SamePath $capture[0] $script:CallerDirectory) 'preparation preserves caller directory for relative inputs'
    Assert-Test ($capture[1] -ceq 'native') 'Docker installer ignores an inherited WSL selection'
    Assert-Test ((Test-SamePath $capture[2] $data) -and (Test-SamePath $capture[3] $runs)) 'Docker installation uses its separate per-user data and results'

    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('second prepared launch succeeds: ' + $result.Output)
    $calls = @(Get-Content -LiteralPath $events)
    Assert-Test (@($calls | Where-Object { $_ -ceq 'install:runtime' }).Count -eq 1 -and @($calls | Where-Object { $_ -ceq 'python:self-test' }).Count -eq 1) 'second launch neither reloads the image nor repeats the setup self-test'
    Assert-Test (@($calls | Where-Object { $_ -ceq 'python:wizard' }).Count -eq 2) 'second launch opens the menu directly'

    # A changed component forces preparation even if a previous ready record exists.
    # Its subsequent failure must remove that old success, not merely leave it stale.
    'changed configuration' | Add-Content -LiteralPath (Join-Path $app '.runtime\python\python312._pth') -Encoding ASCII
    'fail' | Set-Content -LiteralPath $fail -Encoding ASCII
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0) 'failed reference test returns failure through the actual launcher'
    Assert-Test (-not (Test-Path -LiteralPath $readyPath) -and -not (Test-Path -LiteralPath $script:CapturePath)) 'failed setup does not claim ready or open the menu'
    Assert-Test ($result.Output -match 'Test di riferimento falliti' -and $result.Output -match 'setup.log') 'failed preparation provides diagnostic guidance'
    $setupLog = Join-Path $app '.runtime\setup.log'
    Assert-Test ((Test-Path -LiteralPath $setupLog) -and
        (Get-Content -LiteralPath $setupLog -Raw) -match 'Test di riferimento falliti') 'setup diagnostics contain the failure at the literal application path'
    Remove-Item -LiteralPath $fail
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -eq 0 -and (Test-Path -LiteralPath $readyPath)) ('same executable retries a failed preparation: ' + $result.Output)
    Assert-Test ((Get-Content -LiteralPath (Join-Path $data 'preserved.txt') -Raw).Trim() -ceq 'existing input' -and (Get-Content -LiteralPath (Join-Path $runs 'preserved.txt') -Raw).Trim() -ceq 'existing result') 'preparation and retry preserve existing data and results'

    Remove-Item -LiteralPath $readyPath
    $beforePreview = @(Get-Content -LiteralPath $events | Where-Object { $_ -like 'install:*' }).Count
    $result = Invoke-TestLauncher -Executable $executable -Arguments @('--dry-run', 'wizard') -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('dry-run preview remains available without preparing: ' + $result.Output)
    $afterPreview = @(Get-Content -LiteralPath $events | Where-Object { $_ -like 'install:*' }).Count
    Assert-Test ($beforePreview -eq $afterPreview -and -not (Test-Path -LiteralPath $readyPath)) 'preview has no implicit setup or false readiness'
    # Exercise the ready WSL Preview through the compiled executable and real
    # launch scripts. Scientific execution remains at the fake Python boundary.
    foreach ($name in @('bootstrap-common.ps1', 'install-profile.ps1', 'install-profile.json')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $app "installer\windows\$name")
    }
    foreach ($name in @('docker-desktop.json', 'runtime.json', 'runtime.tar')) {
        Remove-Item -LiteralPath (Join-Path $distribution $name)
    }
    Remove-Item -LiteralPath (Join-Path $app 'release.json')
    $profile = Get-Content -LiteralPath (Join-Path $app 'installer\windows\install-profile.json') -Raw -Encoding UTF8 | ConvertFrom-Json
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
    Assert-Test ($result.ExitCode -eq 0) ('ready Preview launches from a stable configured shell: ' + $result.Output)
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ($capture[1] -ceq 'wsl' -and $capture[5] -ceq $distro -and $capture[6] -ceq $backend.runtime_image) 'Preview selects only its verified WSL distribution and image'
    Assert-Test ((Test-SamePath $capture[2] $candidateData) -and (Test-SamePath $capture[3] $candidateRuns) -and
        (Test-SamePath $capture[4] $candidateBase) -and (Test-SamePath $capture[7] $app)) 'installed Preview resets inherited stable project, workspace, data and runs'
    Assert-Test ($capture[8] -ceq '-m' -and $capture[9] -ceq 'nipat' -and $capture[10] -ceq 'wizard') 'ready Preview opens the guided CLI without preparation'

    $explicitRuns = Join-Path $temporary 'explicit user results'
    $result = Invoke-TestLauncher -Executable $executable -Arguments @('--runs-dir', $explicitRuns, 'wizard') -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('Preview preserves explicit output override: ' + $result.Output)
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ($capture[10] -ceq '--runs-dir' -and $capture[11] -ceq $explicitRuns -and $capture[12] -ceq 'wizard') 'explicit CLI output directory reaches Python unchanged'

    $beforeRejected = @(Get-Content -LiteralPath $events).Count
    foreach ($foreignChannel in @('stable', $null)) {
        $backend.installation_channel = $foreignChannel
        $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
        $result = Invoke-TestLauncher -Executable $executable -Environment $environment
        Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'foreign or markerless backend never reaches Python'
    }
    $backend.installation_channel = $profile.channel
    $backend.wsl_distro = 'NIPAT-Runtime'
    $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'candidate backend cannot select the stable WSL distribution'
    $backend.wsl_distro = $distro
    $backend | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backendPath -Encoding UTF8
    $state.installation_channel = 'stable'
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'stable readiness state cannot authorize a Preview launch'
    $state.installation_channel = $profile.channel
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    $manifest.installation_profile.channel = 'stable'
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $script:CapturePath)) 'foreign installer manifest is rejected before running Python'
    Assert-Test (@(Get-Content -LiteralPath $events).Count -eq $beforeRejected) 'rejected installed identities execute neither setup nor analysis'
    Assert-Test ((Get-FileHash -LiteralPath $stableMarker -Algorithm SHA256).Hash -ceq $stableHash) 'launches and rejected identities preserve stable data'

    # Source checkouts intentionally keep environment-based configuration; the
    # installed-only reset must not discard the developer's chosen paths.
    Remove-Item -LiteralPath $manifestPath
    Remove-Item -LiteralPath $backendPath
    Remove-Item -LiteralPath (Join-Path $app '.runtime\runtime-image.txt')
    $result = Invoke-TestLauncher -Executable $executable -Environment $environment
    Assert-Test ($result.ExitCode -eq 0) ('source launch keeps explicit environment configuration: ' + $result.Output)
    $capture = @(Get-Content -LiteralPath $script:CapturePath | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) })
    Assert-Test ((Test-SamePath $capture[2] $stableData) -and (Test-SamePath $capture[3] $stableRuns) -and
        (Test-SamePath $capture[4] $stableBase)) 'source checkouts retain deliberate environment data, results and workspace'
    Write-Host "PASS: $checks launcher assertions."
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
