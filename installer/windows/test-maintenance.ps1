# Real temporary-file inventory/selection tests, no installed WSL or registry writes.
. (Join-Path $PSScriptRoot 'maintenance.ps1') -LibraryOnly
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-maintenance-' + [Guid]::NewGuid().ToString('N'))
$project = Join-Path $temporary 'app'
[IO.Directory]::CreateDirectory($project) | Out-Null
$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw ('FAIL: ' + $Message) }
    $script:checks++
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}
function Add-MaintenanceFile([string] $Path, [string] $Text) {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
    return $Path
}
$manifestFunction = (Get-Command Read-NipatInstallerManifest).ScriptBlock
$repairFunction = (Get-Command Assert-NipatRepairableInstallation).ScriptBlock
$backupsFunction = (Get-Command Get-NipatMaintenanceBackups).ScriptBlock
$planFunction = (Get-Command Get-NipatRuntimeRemovalPlan).ScriptBlock
$removeFunction = (Get-Command Invoke-NipatRuntimeRemoval).ScriptBlock
try {
    # Exercise the real script entrypoint: imported -LibraryOnly parameters must
    # not swallow a caller's operation or replace its explicitly selected path.
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $start.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' +
        (Join-Path $PSScriptRoot 'maintenance.ps1') + '" -Operation inventory -Project "' +
        (Join-Path $temporary 'missing-app') + '"'
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.RedirectStandardInput = $true
    $child = New-Object Diagnostics.Process
    $child.StartInfo = $start
    try {
        [void]$child.Start()
        $child.StandardInput.Close()
        if (-not $child.WaitForExit(30000)) { $child.Kill(); throw 'Maintenance entrypoint did not terminate.' }
        $entryError = $child.StandardError.ReadToEnd()
        Assert-Test ($child.ExitCode -eq 1 -and $entryError.Contains('Manutenzione interrotta:')) 'production entrypoint rejects a missing application instead of silently importing itself'
    } finally { $child.Dispose() }
    $script:manifest = [pscustomobject]@{
        source_commit = ('a' * 40)
        assets = [pscustomobject]@{ rootfs = [pscustomobject]@{ sha256 = ('1' * 64) }; scientific_image = [pscustomobject]@{ sha256 = ('2' * 64) } }
    }
    function Read-NipatInstallerManifest([string] $Path) { return $script:manifest }
    function Assert-NipatRepairableInstallation([string] $Project) { return $script:manifest }
    function Get-NipatMaintenanceBackups([string] $Project) { return @() }
    $targets = @()
    foreach ($name in @('active', 'previous', 'obsolete')) {
        $directory = Join-Path $temporary $name
        Add-MaintenanceFile (Join-Path $directory 'ext4.vhdx') ('disk-' + $name) | Out-Null
        $receipt = Add-MaintenanceFile (Join-Path $temporary ($name + '.json')) '{}'
        (Get-Item -LiteralPath $receipt).LastWriteTimeUtc = [DateTime]::UtcNow.AddDays(
            $(if ($name -ceq 'obsolete') { -2 } else { -1 }))
        $targets += [pscustomobject]@{
            Distro = ('NIPAT-Experimental08-' + $name); Directory = $directory; OwnershipPath = $receipt
            RootfsSha256 = $(if ($name -ceq 'active') { '1' * 64 } elseif ($name -ceq 'previous') { '3' * 64 } else { '4' * 64 })
        }
    }
    $cache = @()
    foreach ($digit in @('1', '2', '3', '5')) {
        $path = Add-MaintenanceFile (Join-Path $temporary ('cache-' + $digit + '.tar.gz')) ('archive-' + $digit)
        $cache += [pscustomobject]@{ Path = $path; Sha256 = ($digit * 64) }
    }
    $script:plan = [pscustomobject]@{ Targets = $targets; CacheFiles = $cache; ProtectedRoots = @($project) }
    Add-MaintenanceFile (Join-Path $project '.runtime\backend.json') '{"installation_channel":"experimental08","wsl_distro":"NIPAT-Experimental08-active"}' | Out-Null
    $inventory = Get-NipatMaintenanceInventory $project $plan
    Assert-Test ($inventory.schema_version -eq 1 -and $inventory.runtimes.Count -eq 3) 'inventory contains exact owned runtimes'
    $active = @($inventory.runtimes | Where-Object active)[0]
    $previous = @($inventory.runtimes | Where-Object retained)[0]
    $obsolete = @($inventory.runtimes | Where-Object removable)[0]
    Assert-Test (-not $active.removable -and -not $previous.removable -and $obsolete.name -ceq 'NIPAT-Experimental08-obsolete') 'active and most recent previous runtimes are protected'
    Assert-Test ($obsolete.size_bytes -gt 0 -and @($inventory.cache | Where-Object removable).Count -eq 1) 'sizes reported and current/previous archives retained'
    Assert-Rejected { Assert-NipatMaintenanceSelection $inventory 'cleanup' $active.id } 'active runtime cannot be selected'
    Assert-Rejected { Assert-NipatMaintenanceSelection $inventory 'cleanup' $previous.id } 'retained runtime cannot be selected'
    Assert-Rejected { Assert-NipatMaintenanceSelection $inventory 'cleanup' 'unrecognized-id' } 'unknown target cannot be selected'
    Assert-NipatMaintenanceSelection $inventory 'cleanup' $obsolete.id
    Assert-NipatMaintenanceSelection $inventory 'recover' 'current-installation'
    Assert-Rejected { Assert-NipatMaintenanceSelection $inventory 'recover' 'backup-directory' } 'partial backups never authorize version rollback'
    function Get-NipatRuntimeRemovalPlan([string] $Project, [switch] $InspectOnly) { return $script:plan }
    $script:removedSelection = $null
    function Invoke-NipatRuntimeRemoval($Plan) { $script:removedSelection = $Plan }
    Invoke-NipatMaintenanceCleanup $project $obsolete.id
    Assert-Test ($removedSelection.Targets.Count -eq 1 -and $removedSelection.Targets[0].Distro -ceq $obsolete.name -and
        $removedSelection.CacheFiles.Count -eq 0 -and $removedSelection.RuntimeRoots.Count -eq 0) 'cleanup delegates only the selected exact target, no roots or other runtime'
    $cacheTarget = @($inventory.cache | Where-Object removable)[0]
    Invoke-NipatMaintenanceCleanup $project $cacheTarget.id
    Assert-Test ($removedSelection.Targets.Count -eq 0 -and $removedSelection.CacheFiles.Count -eq 1) 'cache cleanup delegates exactly one verified archive'
    [IO.File]::Delete((Join-Path $project '.runtime\backend.json'))
    $incomplete = Get-NipatMaintenanceInventory $project $plan
    Assert-Test (@($incomplete.runtimes | Where-Object removable).Count -eq 0 -and @($incomplete.cache | Where-Object removable).Count -eq 0) 'without an active runtime ordinary cleanup remains unavailable'
    $ready = Join-Path $project '.runtime\maintenance\test\ready.json'
    [IO.Directory]::CreateDirectory((Split-Path -Parent $ready)) | Out-Null
    Write-NipatMaintenanceReady $project $ready 'recover' 'current-installation'
    $ack = Get-Content -LiteralPath $ready -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($ack.status -ceq 'waiting-for-client' -and $ack.target_id -ceq 'current-installation') 'handoff acknowledgement identifies the requested action'
    Assert-Rejected { Write-NipatMaintenanceReady $project $ready 'cleanup' 'target' } 'existing acknowledgement is never overwritten'
    Assert-Rejected { Write-NipatMaintenanceReady $project (Join-Path $temporary 'outside\ready.json') 'cleanup' 'target' } 'handoff acknowledgement cannot escape application maintenance directory'
    Add-MaintenanceFile (Join-Path (Split-Path -Parent $ready) 'cancelled.json') '{}' | Out-Null
    Assert-Rejected { Assert-NipatMaintenanceNotCancelled $ready } 'cancelled handoff cannot proceed after the client closes'
    foreach ($case in @(
        @{ Name = 'normal-exit'; Code = 0; Cancelled = $false; Accepted = $false },
        @{ Name = 'failed-client'; Code = 1; Cancelled = $false; Accepted = $false },
        @{ Name = 'confirmed-handoff'; Code = 85; Cancelled = $false; Accepted = $true },
        @{ Name = 'cancelled-handoff'; Code = 85; Cancelled = $true; Accepted = $false }
    )) {
        $caseReady = Join-Path $project ('.runtime\maintenance\' + $case.Name + '\ready.json')
        if ($case.Cancelled) {
            Add-MaintenanceFile (Join-Path (Split-Path -Parent $caseReady) 'cancelled.json') '{}' | Out-Null
        }
        $clientStart = New-Object Diagnostics.ProcessStartInfo
        $clientStart.FileName = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $clientStart.Arguments = '-NoLogo -NoProfile -Command "exit ' + $case.Code + '"'
        $clientStart.UseShellExecute = $false
        $clientStart.CreateNoWindow = $true
        $client = [Diagnostics.Process]::Start($clientStart)
        $authorized = $false
        try {
            $null = $client.Handle
            try { Wait-NipatMaintenanceClient $client $caseReady 20; $authorized = $true } catch { }
            Assert-Test ($authorized -eq $case.Accepted) ($case.Name + ': only explicit exit 85 without cancellation authorizes mutation')
        } finally {
            if (-not $client.HasExited) { $client.Kill(); $client.WaitForExit(5000) | Out-Null }
            $client.Dispose()
        }
    }
    Set-Item Function:Assert-NipatRepairableInstallation -Value $repairFunction
    $source = Add-MaintenanceFile (Join-Path $project 'source.py') 'verified source'
    $payload = [pscustomobject]@{
        schema_version = 1; installation_channel = 'experimental08'; source_commit = $manifest.source_commit
        files = [object[]]@([pscustomobject]@{ path = 'source.py'; sha256 = (Get-NipatRepairFileHash $source) })
    }
    Add-MaintenanceFile (Join-Path $project '.distribution\application-files.json') ($payload | ConvertTo-Json -Depth 8) | Out-Null
    Assert-NipatRepairableInstallation $project | Out-Null
    Add-MaintenanceFile $source 'modified source' | Out-Null
    Assert-Rejected { Assert-NipatRepairableInstallation $project } 'repair refuses a modified payload before any bootstrap execution'
    [IO.File]::Delete($source)
    Assert-Rejected { Assert-NipatRepairableInstallation $project } 'repair refuses incomplete payload and asks for reinstall'
    Write-Host "PASS: $checks installation maintenance checks."
} finally {
    Set-Item Function:Read-NipatInstallerManifest -Value $manifestFunction
    Set-Item Function:Assert-NipatRepairableInstallation -Value $repairFunction
    Set-Item Function:Get-NipatMaintenanceBackups -Value $backupsFunction
    Set-Item Function:Get-NipatRuntimeRemovalPlan -Value $planFunction
    Set-Item Function:Invoke-NipatRuntimeRemoval -Value $removeFunction
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
