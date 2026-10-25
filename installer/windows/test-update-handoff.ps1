# Integration check: real worker processes and a recording executable, no WSL installation.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat handoff & ' + [char]0x03A9 + '-' + [Guid]::NewGuid().ToString('N'))
$oldLocal = $env:LOCALAPPDATA
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$script:Children = @()
$primaryFailure = $null

function Assert-Test([bool] $Condition, [string] $Description) {
    if (-not $Condition) { throw ('FAIL: ' + $Description) }
    Write-Host ('PASS: ' + $Description)
}
function Quote-Test([string] $Value) {
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Wait-TestFile([string] $File) {
    $limit = [DateTime]::UtcNow.AddSeconds(20)
    while (-not (Test-Path -LiteralPath $File)) {
        if ([DateTime]::UtcNow -gt $limit) { throw "Timed out waiting for $File" }
        Start-Sleep -Milliseconds 50
    }
}
function Write-TestJson([string] $File, $Object) {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $File)) | Out-Null
    [IO.File]::WriteAllText($File, ($Object | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
}
function Start-TestProcess([string] $Arguments, $Environment = @{}) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $powershell
    $start.Arguments = $Arguments
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    foreach ($key in $Environment.Keys) { $start.EnvironmentVariables[$key] = $Environment[$key] }
    $process = [Diagnostics.Process]::Start($start)
    $script:Children += $process
    return $process
}

function Wait-TestRelaunch([string] $Root) {
    $recordFile = Join-Path $Root 'reopened-process.json'
    Wait-TestFile $recordFile
    $record = Get-Content -LiteralPath $recordFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $process = $null
    try {
        $process = [Diagnostics.Process]::GetProcessById([int]$record.pid)
        # A process that already exited needs no further wait. Never attach
        # cleanup to an unrelated process that has reused its PID.
        if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$record.started_ticks) {
            $process.Dispose()
            return
        }
    } catch [ArgumentException] { return }
      catch [InvalidOperationException] { if ($null -ne $process) { $process.Dispose() }; return }
    $script:Children += $process
    Assert-Test ($process.WaitForExit(20000)) 'reopened fixture entry point finishes before directory cleanup'
    Assert-Test ($process.ExitCode -eq 0) 'reopened fixture entry point exits successfully'
}

try {
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    $env:LOCALAPPDATA = Join-Path $temporary 'user-local'
    [IO.Directory]::CreateDirectory((Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop')) | Out-Null
    $fixture = Join-Path $temporary 'recording-installer.exe'
    Add-Type -TypeDefinition @'
using System;
using System.IO;
class RecordingInstaller {
  static int Main(string[] args) {
    string root = Environment.GetEnvironmentVariable("NIPAT_HANDOFF_FIXTURE");
    if (args.Length > 0 && args[0] == "-m") {
      File.WriteAllLines(Path.Combine(root,"reopened.txt"), args);
      return 0;
    }
    File.WriteAllLines(Path.Combine(root,"invoked.txt"), args);
    string[] behavior = File.ReadAllLines(Path.Combine(root,"behavior.txt"));
    if (behavior[1] != "keep") {
      string app = Path.Combine(root,"app & space");
      string commit = new string('b',40);
      string runtime = "sha256:" + new string('c',64);
      string state = "{\"schema_version\":1,\"installation_channel\":\"desktop\",\"phase\":\""+behavior[1]+"\",\"version\":\"0.6.1\",\"source_commit\":\""+commit+"\",\"runtime_image\":\""+runtime+"\"}";
      File.WriteAllText(Path.Combine(app,".runtime","installer","state.json"),state);
      File.WriteAllText(Path.Combine(app,".distribution","installer-manifest.json"),state);
    }
    return Int32.Parse(behavior[0]);
  }
}
'@ -Language CSharp -OutputAssembly $fixture -OutputType ConsoleApplication
    $holder = Join-Path $temporary 'parent-holder.ps1'
    [IO.File]::WriteAllText($holder, @'
param([string]$Release,[int]$Code=85)
$limit=[DateTime]::UtcNow.AddMinutes(2)
while(-not(Test-Path -LiteralPath $Release)){if([DateTime]::UtcNow -gt $limit){exit 1};Start-Sleep -Milliseconds 50}
exit $Code
'@)
    foreach ($case in @('success', 'busy', 'tampered', 'canceled', 'unconfirmed', 'pending', 'reboot', 'failed', 'old-ready')) {
        $root = Join-Path $temporary $case
        $app = Join-Path $root 'app & space'
        $work = Join-Path $root 'outside app worker'
        $data = Join-Path $root 'research data'
        foreach ($dir in @($work,$data,(Join-Path $app 'scripts\windows'),(Join-Path $app 'installer\windows'),
            (Join-Path $app '.runtime\installer'),(Join-Path $app '.distribution'))) {
            [IO.Directory]::CreateDirectory($dir) | Out-Null
        }
        $sentinel = Join-Path $data 'preserve.txt'
        [IO.File]::WriteAllText($sentinel,'research data stays unchanged')
        $preference = Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop\preferences.json'
        [IO.File]::WriteAllText($preference,'{"schema_version":1,"language":"en"}')
        $sentinelHash = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
        $preferenceHash = (Get-FileHash -LiteralPath $preference -Algorithm SHA256).Hash
        Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\windows\run.ps1') -Destination (Join-Path $app 'scripts\windows\run.ps1')
        Copy-Item -LiteralPath $fixture -Destination (Join-Path $app 'python-fixture.exe')
        [IO.File]::WriteAllText((Join-Path $app 'scripts\windows\common.ps1'), @'
$fixtureRoot = $env:NIPAT_HANDOFF_FIXTURE
$fixtureProcess = [Diagnostics.Process]::GetCurrentProcess()
$fixtureRecord = @{pid=$PID;started_ticks=$fixtureProcess.StartTime.ToUniversalTime().Ticks} | ConvertTo-Json
$fixtureTemporary = Join-Path $fixtureRoot 'reopened-process.tmp'
[IO.File]::WriteAllText($fixtureTemporary,$fixtureRecord,(New-Object Text.UTF8Encoding($false)))
[IO.File]::Move($fixtureTemporary,(Join-Path $fixtureRoot 'reopened-process.json'))
$fixtureProcess.Dispose()
function Get-NipatProject { return (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) }
function Set-NipatEnvironment([string]$Project) {}
function Get-NipatPython([string]$Project) { return (Join-Path $Project 'python-fixture.exe') }
'@)
        [IO.File]::WriteAllText((Join-Path $app 'installer\windows\bootstrap-common.ps1'), @'
function Read-NipatInstallerManifest([string]$Path) { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
function Assert-NipatRuntimeBinding($Manifest,$State,$Configuration) {
 if($Manifest.source_commit -cne $State.source_commit){throw 'binding mismatch'}
}
'@)
        $state = [ordered]@{schema_version=1;installation_channel='desktop';phase='ready';version='0.6.0';source_commit=('a'*40);runtime_image=('sha256:'+('c'*64))}
        Write-TestJson (Join-Path $app '.runtime\installer\state.json') $state
        Write-TestJson (Join-Path $app '.distribution\installer-manifest.json') $state
        Write-TestJson (Join-Path $app '.runtime\backend.json') @{schema_version=1}
        $code = if($case -eq 'reboot'){3010}elseif($case -eq 'failed'){1}else{0}
        $phase = if($case -eq 'pending'){'verifying_installation'}elseif($case -eq 'old-ready'){'keep'}else{'ready'}
        [IO.File]::WriteAllLines((Join-Path $root 'behavior.txt'),[string[]]@([string]$code,$phase))
        $package = Join-Path $root 'NIPAT-Setup.exe'
        Copy-Item -LiteralPath $fixture -Destination $package
        $release = Join-Path $root 'release-parent'
        $parentCode = if ($case -eq 'unconfirmed') { 0 } else { 85 }
        $parent = Start-TestProcess ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' + (Quote-Test $holder) + ' -Release ' + (Quote-Test $release) + ' -Code ' + $parentCode)
        $descriptor = Join-Path $work 'handoff.json'
        Write-TestJson $descriptor ([ordered]@{
            schema_version=1;installation_channel='desktop';parent_pid=$parent.Id;project_dir=$app;package=$package
            sha256=(Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant();size=(Get-Item -LiteralPath $package).Length
            version='0.6.1';source_commit=('b'*40);data_dir=$data
        })
        $workerPath = Join-Path $work 'update-handoff.ps1'
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'update-handoff.ps1') -Destination $workerPath
        # The bundled worker sets only its own process policy, also when the
        # launching process has the default Restricted policy. No machine policy changes.
        $worker = Start-TestProcess ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' + (Quote-Test $workerPath) + ' -Descriptor ' + (Quote-Test $descriptor) + ' -NoPause') @{
            NIPAT_HANDOFF_FIXTURE=$root; PSExecutionPolicyPreference='Restricted'
        }
        Wait-TestFile (Join-Path $work 'ready.json')
        Assert-Test (-not (Test-Path -LiteralPath (Join-Path $root 'invoked.txt'))) "$case waits for the current CLI to exit"
        $shared = $null
        try {
            if($case -eq 'busy') {
                $shared=[IO.File]::Open((Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop\activity.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
            }
            if($case -eq 'tampered'){[IO.File]::AppendAllText($package,'modified after download')}
            if($case -eq 'canceled'){[IO.File]::WriteAllText((Join-Path $work 'cancel'),'cancel')}
            [IO.File]::WriteAllText($release,'exit')
            Assert-Test ($worker.WaitForExit(30000)) "$case worker completes"
        } finally {if($null -ne $shared){$shared.Dispose()}}
        if($case -eq 'success') {
            Wait-TestFile (Join-Path $root 'reopened.txt')
            Wait-TestRelaunch $root
        }
        if($case -in @('busy','tampered','canceled','unconfirmed')) {
            Assert-Test (-not(Test-Path -LiteralPath (Join-Path $root 'invoked.txt'))) "$case never starts an installer"
        } else {
            Assert-Test (Test-Path -LiteralPath (Join-Path $root 'invoked.txt')) "$case invokes the verified executable"
            $arguments=Get-Content -LiteralPath (Join-Path $root 'invoked.txt') -Encoding UTF8
            Assert-Test ($arguments -ccontains ('/DIR='+$app) -and $arguments -ccontains '/NIPATUPDATE=1') "$case preserves the application path as one argv value"
        }
        if($case -eq 'success') {
            Assert-Test ($worker.ExitCode -eq 0) 'two-version ready update reopens through production run.ps1'
        } else {
            Assert-Test (-not(Test-Path -LiteralPath (Join-Path $root 'reopened.txt'))) "$case does not reopen NIPAT"
            Assert-Test ($worker.ExitCode -ne 0) "$case reports an incomplete handoff"
        }
        Assert-Test ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ceq $sentinelHash -and
            (Get-FileHash -LiteralPath $preference -Algorithm SHA256).Hash -ceq $preferenceHash) "$case preserves research data and user preferences"
    }
} catch {
    $primaryFailure = $_
    throw
} finally {
    # Stop only test-owned processes, in reverse start order so releasing the
    # parent cannot race a still-live worker into launching another fixture.
    for($index=$script:Children.Count-1;$index -ge 0;$index--) {
        $child=$script:Children[$index]
        try{if(-not $child.HasExited){$child.Kill();$child.WaitForExit(5000)|Out-Null};$child.Dispose()}catch{}
    }
    $env:LOCALAPPDATA=$oldLocal
    try {
        if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Recurse -Force}
    } catch {
        if ($null -eq $primaryFailure) { throw }
        Write-Warning ('Cleanup after the original test failure also failed: ' + $_.Exception.Message)
    }
}
