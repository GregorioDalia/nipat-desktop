param(
    [ValidateSet('inventory', 'cleanup', 'recover')][string] $Operation = 'inventory',
    [string] $Project = '',
    [string] $TargetId = '',
    [int] $WaitForProcessId = 0,
    [string] $ReadyFile = '',
    [switch] $LibraryOnly
)

# Dot-sourced libraries declare their own Project/LibraryOnly parameters. Preserve
# this invocation before importing them so an ordinary command is not silently
# converted into a library import (or redirected to the default installation).
$nipatMaintenanceInvocation = @{
    Project = $Project; Operation = $Operation; TargetId = $TargetId
    WaitForProcessId = $WaitForProcessId; ReadyFile = $ReadyFile
    LibraryOnly = [bool]$LibraryOnly
}
# Ordinary maintenance uses the same ownership checks as uninstall, but protects
# the active and most recent previous runtime. No general Docker/WSL prune exists.
. (Join-Path $PSScriptRoot 'uninstall-runtime.ps1') -LibraryOnly
. (Join-Path $PSScriptRoot 'repair-installation.ps1') -LibraryOnly
$Project = $nipatMaintenanceInvocation.Project
$Operation = $nipatMaintenanceInvocation.Operation
$TargetId = $nipatMaintenanceInvocation.TargetId
$WaitForProcessId = $nipatMaintenanceInvocation.WaitForProcessId
$ReadyFile = $nipatMaintenanceInvocation.ReadyFile
$LibraryOnly = $nipatMaintenanceInvocation.LibraryOnly

function Get-NipatMaintenanceId([string] $Kind, [string] $Value) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value.ToLowerInvariant()))).Replace('-', '').ToLowerInvariant()
        return ($Kind + '-' + $hash)
    } finally { $hasher.Dispose() }
}

function Get-NipatMaintenanceSize([string] $Path) {
    Assert-NipatRemovalTree $Path
    if (-not (Test-Path -LiteralPath $Path)) { return [long]0 }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer) { return [long]$item.Length }
    $total = [long]0
    foreach ($file in @(Get-ChildItem -LiteralPath $Path -File -Recurse -Force)) { $total += $file.Length }
    return $total
}

function Assert-NipatRepairableInstallation([string] $Project) {
    $manifest = Read-NipatInstallerManifest (Join-Path $Project '.distribution\installer-manifest.json')
    $inventoryPath = Join-Path $Project '.distribution\application-files.json'
    $payload = Get-Content -LiteralPath $inventoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-NipatApplicationPayload $payload
    if ($payload.source_commit -cne $manifest.source_commit) { throw 'Inventario e manifest appartengono a versioni diverse; reinstallare il pacchetto.' }
    foreach ($entry in $payload.files) {
        $path = Get-NipatRepairTarget $Project $entry.path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-NipatRepairFileHash $path) -cne $entry.sha256) {
            throw ('File applicativo mancante o modificato: ' + $entry.path + '. Reinstallare lo stesso pacchetto verificato.')
        }
    }
    return $manifest
}

function Get-NipatMaintenanceBackups([string] $Project) {
    $root = Join-Path (Get-NipatInstallLayoutHistoryDirectory) 'backups'
    Assert-NipatInstallPathWithoutLinks $root -Tree
    $records = @()
    if (Test-Path -LiteralPath $root -PathType Container) {
        foreach ($directory in @(Get-ChildItem -LiteralPath $root -Directory)) {
            $path = Join-Path $directory.FullName 'repair-journal.json'
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
            try {
                $journal = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
                Assert-NipatInstallationChannel $journal 'Il backup'
                if ($journal.schema_version -ne 1 -or $journal.app_dir -ine $Project) { continue }
                $records += [pscustomobject]@{
                    id = $directory.Name; path = $directory.FullName; status = $journal.status
                    created_utc = $journal.created_utc; recoverable = $false
                    reason = 'Backup dei file sostituiti; non rappresenta una precedente installazione completa.'
                }
            } catch { continue }
        }
    }
    return @($records | Sort-Object created_utc -Descending)
}

function Get-NipatMaintenanceInventory([string] $Project, $Plan = $null) {
    $warnings = @()
    if ($null -eq $Plan) { $Plan = Get-NipatRuntimeRemovalPlan $Project -InspectOnly }
    $backendPath = Join-Path $Project '.runtime\backend.json'
    $active = ''
    if (Test-Path -LiteralPath $backendPath -PathType Leaf) {
        $backend = Get-Content -LiteralPath $backendPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-NipatInstallationChannel $backend 'La configurazione attiva'
        $active = [string]$backend.wsl_distro
        if (@($Plan.Targets | Where-Object { $_.Distro -ceq $active }).Count -ne 1) {
            throw 'Il runtime attivo non corrisponde a un registro verificato; nessuna pulizia viene proposta.'
        }
    }
    $previous = @($Plan.Targets | Where-Object { $_.Distro -cne $active } |
        Sort-Object @{Expression = { (Get-Item -LiteralPath $_.OwnershipPath).LastWriteTimeUtc }; Descending = $true}, Distro |
        Select-Object -First 1)
    $previousName = if ($previous.Count) { $previous[0].Distro } else { '' }
    $manifest = Read-NipatInstallerManifest (Join-Path $Project '.distribution\installer-manifest.json')
    $keepHashes = @($manifest.assets.rootfs.sha256, $manifest.assets.scientific_image.sha256)
    $backups = @(Get-NipatMaintenanceBackups $Project)
    # Preserve the archives referenced by the most recent saved manifest as well.
    foreach ($backup in @($backups | Select-Object -First 1)) {
        $oldManifestPath = Join-Path $backup.path 'files\.distribution\installer-manifest.json'
        if (Test-Path -LiteralPath $oldManifestPath -PathType Leaf) {
            try {
                $old = Get-Content -LiteralPath $oldManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
                Assert-NipatInstallationProfile $old.installation_profile
                $keepHashes += @($old.assets.rootfs.sha256, $old.assets.scientific_image.sha256)
            } catch { $warnings += 'Manifest precedente non leggibile: gli archivi della cache saranno conservati.' }
        }
    }
    $runtimes = @($Plan.Targets | ForEach-Object {
        $isActive = $_.Distro -ceq $active
        $retained = $_.Distro -ceq $previousName
        $removable = [bool]$active -and -not $isActive -and -not $retained
        if ($isActive -or $retained) { $keepHashes += $_.RootfsSha256 }
        [pscustomobject]@{
            id = (Get-NipatMaintenanceId 'runtime' $_.Distro); name = $_.Distro
            path = $_.Directory; size_bytes = (Get-NipatMaintenanceSize $_.Directory)
            active = $isActive; retained = $retained; removable = $removable
            reason = if ($isActive) { 'Ambiente attivo.' } elseif ($retained) { 'Ambiente precedente piu recente conservato.' }
                elseif (-not $active) { 'Nessun ambiente attivo verificato; completare prima la preparazione.' }
                else { 'Ambiente precedente verificabile; la rimozione richiede conferma e un nuovo controllo di proprieta.' }
        }
    })
    $cache = @($Plan.CacheFiles | ForEach-Object {
        $removable = [bool]$active -and $_.Sha256 -notin $keepHashes -and $warnings.Count -eq 0
        [pscustomobject]@{
            id = (Get-NipatMaintenanceId 'cache' $_.Path); name = [IO.Path]::GetFileName($_.Path)
            path = $_.Path; size_bytes = (Get-NipatMaintenanceSize $_.Path); removable = $removable
            reason = if ($removable) { 'Archivio precedente; integrita ricontrollata prima della rimozione.' }
                else { 'Archivio conservato per installazione o recupero.' }
        }
    })
    $canRepair = $true
    $repairReason = 'Ripete preparazione e autotest della versione installata; conserva dati e risultati.'
    try { Assert-NipatRepairableInstallation $Project | Out-Null }
    catch { $canRepair = $false; $repairReason = $_.Exception.Message }
    return [pscustomobject]@{
        schema_version = 1; platform = 'windows'; runtimes = $runtimes; cache = $cache; backups = $backups
        recovery = [pscustomobject]@{ id = 'current-installation'; recoverable = $canRepair; reason = $repairReason }
        warnings = $warnings
    }
}

function Assert-NipatMaintenanceSelection($Inventory, [string] $Operation, [string] $TargetId) {
    if ($Operation -ceq 'recover') {
        if ($TargetId -cne 'current-installation' -or -not $Inventory.recovery.recoverable) {
            throw 'La riparazione richiesta non e disponibile. Reinstallare il pacchetto verificato.'
        }
        return
    }
    $selected = @(@($Inventory.runtimes) + @($Inventory.cache) | Where-Object { $_.id -ceq $TargetId })
    if ($selected.Count -ne 1 -or -not $selected[0].removable) {
        throw 'La destinazione non e un elemento NIPAT precedente e rimovibile. Nessuna rimozione viene eseguita.'
    }
}

function Assert-NipatMaintenanceNotCancelled([string] $ReadyFile) {
    if ($ReadyFile -and (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $ReadyFile) 'cancelled.json'))) {
        throw 'Passaggio alla manutenzione annullato. Nessuna nuova operazione viene avviata.'
    }
}

function Wait-NipatMaintenanceClient($Process, [string] $ReadyFile, [int] $TimeoutSeconds = 300) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not $Process.WaitForExit(100)) {
        Assert-NipatMaintenanceNotCancelled $ReadyFile
        if ([DateTime]::UtcNow -gt $deadline) { throw 'NIPAT non e stato chiuso; nessuna manutenzione eseguita.' }
    }
    Assert-NipatMaintenanceNotCancelled $ReadyFile
    if ($Process.ExitCode -ne 85) {
        throw 'La sessione non ha confermato il passaggio alla manutenzione. Nessuna modifica viene eseguita.'
    }
}

function Invoke-NipatMaintenanceCleanup([string] $Project, [string] $TargetId, [string] $ReadyFile = '') {
    $plan = Get-NipatRuntimeRemovalPlan $Project
    $inventory = Get-NipatMaintenanceInventory $Project $plan
    Assert-NipatMaintenanceSelection $inventory 'cleanup' $TargetId
    $targets = @($plan.Targets | Where-Object { (Get-NipatMaintenanceId 'runtime' $_.Distro) -ceq $TargetId })
    $cache = @($plan.CacheFiles | Where-Object { (Get-NipatMaintenanceId 'cache' $_.Path) -ceq $TargetId })
    $selection = [pscustomobject]@{
        Targets = $targets; CacheFiles = $cache; RuntimeRoots = @(); CacheRoots = @(); ProtectedRoots = $plan.ProtectedRoots
    }
    Assert-NipatMaintenanceNotCancelled $ReadyFile
    Invoke-NipatRuntimeRemoval $selection
}

function Write-NipatMaintenanceReady([string] $Project, [string] $Path, [string] $Operation, [string] $TargetId) {
    $root = [IO.Path]::GetFullPath((Join-Path $Project '.runtime\maintenance')).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($full) -cne 'ready.json' -or (Test-Path -LiteralPath $full)) {
        throw 'Percorso della conferma di manutenzione non valido o gia utilizzato.'
    }
    Assert-NipatInstallPathWithoutLinks ([IO.Path]::GetDirectoryName($full)) -Tree
    Write-NipatJsonAtomic $full ([ordered]@{
        schema_version = 1; status = 'waiting-for-client'; operation = $Operation; target_id = $TargetId
    })
}

if (-not $LibraryOnly) {
    $lease = $null
    $result = 1
    $transcript = $false
    $failure = $null
    $logPath = $null
    $readyWritten = $false
    $parent = $null
    try {
        Assert-NipatWindowsUser
        if (-not $Project) { $Project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
        $Project = Resolve-NipatInstallPath $Project
        Assert-NipatInstallationLocation $Project
        $script:NipatWsl = Join-Path $env:WINDIR 'System32\wsl.exe'
        $inventory = Get-NipatMaintenanceInventory $Project
        if ($Operation -ceq 'inventory') {
            [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
            $inventory | ConvertTo-Json -Depth 12
            exit 0
        }
        Assert-NipatMaintenanceSelection $inventory $Operation $TargetId
        $logDirectory = Join-Path (Get-NipatInstallLayoutHistoryDirectory) 'logs'
        Assert-NipatInstallPathWithoutLinks $logDirectory -Tree
        [IO.Directory]::CreateDirectory($logDirectory) | Out-Null
        $logPath = Join-Path $logDirectory ('maintenance-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N') + '.log')
        Start-Transcript -LiteralPath $logPath -ErrorAction Stop | Out-Null
        $transcript = $true
        if ($WaitForProcessId -gt 0) {
            if ($WaitForProcessId -eq $PID -or -not $ReadyFile) { throw 'Passaggio dalla sessione NIPAT non valido.' }
            $parent = Get-Process -Id $WaitForProcessId -ErrorAction Stop
            # Retain the exact process before acknowledgement; a reused PID must
            # never authorize maintenance after an unrelated process exits.
            $null = $parent.Handle
            Write-NipatMaintenanceReady $Project $ReadyFile $Operation $TargetId
            $readyWritten = $true
            Wait-NipatMaintenanceClient $parent $ReadyFile
        } elseif ($ReadyFile) { throw 'La conferma richiede un processo NIPAT da attendere.' }
        $lease = Enter-NipatInstallationActivity
        Assert-NipatMaintenanceNotCancelled $ReadyFile
        if ($Operation -ceq 'cleanup') {
            Invoke-NipatMaintenanceCleanup $Project $TargetId $ReadyFile
        } else {
            Assert-NipatRepairableInstallation $Project | Out-Null
            Assert-NipatMaintenanceNotCancelled $ReadyFile
            # The child inherits the authenticated setup lease; it still performs
            # its own mutex, ownership, manifest, image and scientific checks.
            & (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Project 'installer\windows\bootstrap.ps1') -Resume
            if ($LASTEXITCODE -ne 0) { throw ('Preparazione non completata (codice ' + $LASTEXITCODE + '). Consultare setup.log.') }
        }
        $result = 0
    } catch {
        $failure = $_.Exception.Message
        [Console]::Error.WriteLine('Manutenzione interrotta: ' + $failure)
    } finally {
        Exit-NipatInstallationActivity $lease
        if ($null -ne $parent) { $parent.Dispose() }
        if ($transcript) { try { Stop-Transcript | Out-Null } catch { } }
        if ($readyWritten) {
            try {
                Write-NipatJsonAtomic (Join-Path (Split-Path -Parent $ReadyFile) 'result.json') ([ordered]@{
                    schema_version = 1; operation = $Operation; target_id = $TargetId
                    status = if ($result -eq 0) { 'succeeded' } else { 'failed' }
                    error = $failure; log_path = $logPath; finished_utc = [DateTime]::UtcNow.ToString('o')
                })
            } catch { [Console]::Error.WriteLine('Impossibile salvare il resoconto; conservare il log della manutenzione.') }
        }
    }
    if ($Operation -ne 'inventory' -and -not [Console]::IsInputRedirected) {
        try { Read-Host 'Premere Invio per chiudere' | Out-Null } catch { }
    }
    exit $result
}
