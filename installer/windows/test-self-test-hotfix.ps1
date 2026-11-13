# Executes the recovery helper with synthetic client/bootstrap processes; no WSL or science is run.
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-hotfix-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$hotfix = Join-Path $project 'scripts\windows\repair-0850-self-test.ps1'
$baseCommit = 'b54ef493ba7f0539a8786b97874fe946b2d26393'
$hotfixCommit = '0123456789abcdef0123456789abcdef01234567'
$oldHash = 'e66854186e85f75d9ee7843e90a7b513556b1249f1dada78f687601db598529a'
$newHash = '22d68e6a0851d1ee1fb00799dc9447bdbffbc17645061ff03deaf7875dab6cbf'
$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "Hotfix check failed: $Message" }
    $script:checks++
}
function Write-TestFile([string] $Path, [string] $Text) {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}
function Get-Hash([string] $Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function New-Fixture([string] $Name) {
    $app = Join-Path $temporary ($Name + ' application with spaces')
    $windows = Join-Path $app 'installer\windows'
    [IO.Directory]::CreateDirectory($windows) | Out-Null
    foreach ($name in @('bootstrap-common.ps1', 'install-profile.ps1', 'install-profile.json', 'install-layout.ps1', 'activity-lock.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $windows $name)
    }
    Add-Content -LiteralPath (Join-Path $windows 'bootstrap-common.ps1') -Encoding UTF8 -Value @'
function Assert-NipatWindowsUser { }
function Assert-NipatInstallationLocation([string] $Project) { }
'@
    Add-Content -LiteralPath (Join-Path $windows 'activity-lock.ps1') -Encoding UTF8 -Value @'
function Enter-NipatInstallationActivity {
    [IO.File]::WriteAllText((Join-Path $AppDirectory '.runtime\fixture-lease'), 'held')
    return [pscustomobject]@{ Borrowed = $false }
}
function Exit-NipatInstallationActivity($Lease) { [IO.File]::Delete((Join-Path $AppDirectory '.runtime\fixture-lease')) }
'@
    Write-TestFile (Join-Path $windows 'bootstrap.ps1') @'
param([switch] $Resume)
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
$app = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Resume -or (Test-Path (Join-Path $app '.runtime\fixture-lease'))) { exit 92 }
[IO.File]::AppendAllText((Join-Path $app '.runtime\bootstrap-calls'), "called`n")
$path = Join-Path $app '.runtime\installer\state.json'
$state = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
if (Test-Path (Join-Path $app '.runtime\bootstrap-failure')) {
    $state.phase = 'failed'; Write-NipatJsonAtomic $path $state
    [Console]::Out.WriteLine('fixture bootstrap stdout')
    [Console]::Error.WriteLine('fixture bootstrap failure')
    exit 7
}
$state.phase = 'ready'; Write-NipatJsonAtomic $path $state
Write-Host 'fixture bootstrap ready'
exit 0
'@
    $assets = [ordered]@{}
    foreach ($kind in @('rootfs', 'scientific_image')) {
        $file = $kind + '-0.8.50.tar.gz'
        $assets[$kind] = @{ file = $file; sha256 = ('b' * 64); size = 123
            url = ('https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.50/' + $file) }
    }
    Write-NipatJsonAtomic (Join-Path $app '.distribution\installer-manifest.json') @{
        schema_version = 1; version = '0.8.50'; release_tag = 'v0.8.50'; source_commit = $baseCommit
        installation_profile = (Get-NipatInstallationProfile); runtime_image = ('sha256:' + ('c' * 64)); assets = $assets
    }
    Write-NipatJsonAtomic (Join-Path $app '.distribution\application-files.json') @{ original_inventory = $true }
    Write-NipatJsonAtomic (Join-Path $app '.runtime\installer\state.json') @{
        schema_version = 1; version = '0.8.50'; source_commit = $baseCommit
        installation_channel = 'desktop'; app_dir = $app; phase = 'failed'
    }
    Write-TestFile (Join-Path $app 'scripts\verify_cpin_update.py') $original
    [IO.Directory]::CreateDirectory((Join-Path $app '.runtime\python')) | Out-Null
    Copy-Item -LiteralPath $fakePython -Destination (Join-Path $app '.runtime\python\python.exe')
    return $app
}
function Invoke-Hotfix([string] $App) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $hotfix, '-AppDirectory', $App, '-HotfixSourceCommit', $hotfixCommit)
    $start.Arguments = (($arguments | ForEach-Object { ConvertTo-NipatNativeArgument $_ }) -join ' ')
    $start.UseShellExecute = $false; $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) { $process.Kill(); throw 'Hotfix fixture timed out.' }
        return [pscustomobject]@{ Code = $process.ExitCode; Output = ($stdout.Result + $stderr.Result) }
    } finally { $process.Dispose() }
}
try {
    $fixed = [IO.File]::ReadAllText((Join-Path $project 'scripts\verify_cpin_update.py')).Replace("`r`n", "`n")
    $insertion = "# Embedded Python excludes the script directory from its default search path.`nsys.path.insert(0, str(Path(__file__).resolve().parent))`n`n"
    $original = $fixed.Replace($insertion, '')
    $fakePython = Join-Path $temporary 'python.exe'
    $source = Join-Path $temporary 'client.cs'
    Write-TestFile $source @'
using System;
using System.IO;
public static class Client {
    public static int Main(string[] args) {
        if (args.Length != 5 || args[0] != "-X" || args[1] != "utf8" || args[2] != "-u" || args[4] != "--help") return 93;
        if (!File.ReadAllText(args[3]).Contains("sys.path.insert(0, str(Path(__file__).resolve().parent))")) {
            Console.Error.WriteLine("ModuleNotFoundError: verify_contamination_update"); return 1;
        }
        Console.WriteLine("usage: fixture --help"); return 0;
    }
}
'@
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $compiler /nologo /target:exe /platform:x64 "/out:$fakePython" $source
    if ($LASTEXITCODE -ne 0) { throw 'Could not compile the synthetic client.' }
    $app = New-Fixture 'success'
    $target = Join-Path $app 'scripts\verify_cpin_update.py'
    Assert-Test ((Get-Hash $target) -ceq $oldHash) 'fixture is the exact official original'
    $manifest = Join-Path $app '.distribution\installer-manifest.json'; $manifestHash = Get-Hash $manifest
    $inventory = Join-Path $app '.distribution\application-files.json'; $inventoryHash = Get-Hash $inventory
    $result = Invoke-Hotfix $app
    Assert-Test ($result.Code -eq 0) ('success exit: ' + $result.Output)
    $receipts = @(Get-ChildItem (Join-Path $app '.runtime\installer') -Recurse -Filter receipt.json)
    Assert-Test ($receipts.Count -eq 1) 'one receipt for one attempt'
    $receipt = Get-Content $receipts[0].FullName -Raw | ConvertFrom-Json
    Assert-Test ($receipt.status -ceq 'ready' -and $receipt.help_before_exit -eq 1 -and $receipt.help_after_exit -eq 0 -and
        $receipt.bootstrap_exit -eq 0 -and $receipt.final_phase -ceq 'ready') 'help alone does not activate; successful bootstrap does'
    Assert-Test ($receipt.installation_source_commit -ceq $baseCommit -and $receipt.hotfix_source_commit -ceq $hotfixCommit) 'separate provenance retained'
    Assert-Test ((Get-Hash $target) -ceq $newHash -and (Get-Hash $receipt.backup) -ceq $oldHash) 'exact patch and original backup'
    Assert-Test ((Get-Hash $manifest) -ceq $manifestHash -and (Get-Hash $inventory) -ceq $inventoryHash) 'release manifest and inventory untouched'
    $again = Invoke-Hotfix $app
    Assert-Test ($again.Code -eq 0 -and (Get-Hash $target) -ceq $newHash) ('idempotent retry: ' + $again.Output)
    $newReceipts = @(Get-ChildItem (Join-Path $app '.runtime\installer') -Recurse -Filter receipt.json | Where-Object { $_.FullName -cne $receipts[0].FullName })
    $retry = Get-Content $newReceipts[0].FullName -Raw | ConvertFrom-Json
    Assert-Test ($null -eq $retry.backup -and $retry.help_before_exit -eq 0 -and $retry.bootstrap_exit -eq 0 -and
        (Get-Content (Join-Path $app '.runtime\bootstrap-calls')).Count -eq 2) 'retry preserves backup and repeats bootstrap'
    $bad = New-Fixture 'unknown hash'
    $badTarget = Join-Path $bad 'scripts\verify_cpin_update.py'; Add-Content $badTarget '# local modification'
    $before = Get-Hash $badTarget; $rejected = Invoke-Hotfix $bad
    Assert-Test ($rejected.Code -ne 0 -and (Get-Hash $badTarget) -ceq $before -and
        -not (Test-Path (Join-Path $bad '.runtime\bootstrap-calls'))) 'unknown source refused before patch/bootstrap'
    $failed = New-Fixture 'bootstrap failure'
    Write-TestFile (Join-Path $failed '.runtime\bootstrap-failure') 'fail'
    $failure = Invoke-Hotfix $failed
    $failureReceipt = @(Get-ChildItem (Join-Path $failed '.runtime\installer') -Recurse -Filter receipt.json)[0]
    $record = Get-Content $failureReceipt.FullName -Raw | ConvertFrom-Json
    Assert-Test ($failure.Code -ne 0 -and $record.status -ceq 'failed' -and $record.bootstrap_exit -eq 7 -and
        $record.final_phase -ceq 'failed') 'nonzero bootstrap cannot claim ready'
    Assert-Test ((Get-Content (Join-Path $failureReceipt.DirectoryName 'bootstrap.stderr.log') -Raw).Contains('fixture bootstrap failure') -and
        (Get-Content (Join-Path $failureReceipt.DirectoryName 'bootstrap.stdout.log') -Raw).Contains('fixture bootstrap stdout')) 'both bootstrap diagnostics retained'
    foreach ($fixture in @($app, $bad, $failed)) {
        Assert-Test (-not (Test-Path (Join-Path $fixture '.runtime\fixture-lease'))) 'lease released on every outcome'
    }
    Write-Host "PASS: $checks recovery-helper checks (synthetic client/bootstrap; no scientific execution)."
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force }
