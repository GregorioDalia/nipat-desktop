param(
    [string] $LayoutFile = '',
    [string] $PayloadFile = '',
    [string] $ReportFile = '',
    [string] $ErrorFile = '',
    [switch] $LibraryOnly
)

# Pre-copy repair of an existing Preview. Importing this file has no effects.
# The setup supplies its embedded inventory; existing inventory is evidence
# only for removing an unchanged obsolete file, never a blanket ownership grant.
. (Join-Path $PSScriptRoot 'install-profile.ps1')

function Assert-NipatPayloadRelativePath([string] $Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -match '[\\<>:"|?*\x00-\x1f]' -or
        $Path.StartsWith('/') -or $Path.EndsWith('/') -or $Path.Contains('//')) {
        throw "Percorso del contenuto applicativo non valido: $Path"
    }
    foreach ($part in $Path.Split('/')) {
        if ($part -in @('.', '..') -or $part -match '[. ]$' -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)' -or
            $part -ieq '.git' -or $part -ieq '.runtime') {
            throw "Percorso riservato o ambiguo nel contenuto applicativo: $Path"
        }
    }
    if ($Path -ieq '.distribution/application-files.json') {
        throw 'L inventario applicativo non puo elencare se stesso.'
    }
}

function Assert-NipatApplicationPayload($Payload) {
    if ($Payload -is [Collections.IDictionary]) { $Payload = [pscustomobject]$Payload }
    if ($null -eq $Payload -or @($Payload.PSObject.Properties).Count -ne 4 -or
        -not (($Payload.schema_version -is [int]) -or ($Payload.schema_version -is [long])) -or
        $Payload.schema_version -ne 1 -or $Payload.source_commit -isnot [string] -or
        $Payload.source_commit -cnotmatch '^[a-f0-9]{40}$' -or $Payload.files -isnot [Array] -or
        $Payload.files.Count -eq 0) { throw 'Inventario del contenuto applicativo non valido.' }
    Assert-NipatInstallationChannel $Payload 'Il contenuto applicativo'
    $paths = @{}
    foreach ($entry in $Payload.files) {
        if ($entry -is [Collections.IDictionary]) { $entry = [pscustomobject]$entry }
        if ($null -eq $entry -or @($entry.PSObject.Properties).Count -ne 2 -or
            $entry.path -isnot [string] -or $entry.sha256 -isnot [string] -or
            $entry.sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Voce dell inventario applicativo non valida.' }
        Assert-NipatPayloadRelativePath $entry.path
        if ($paths.ContainsKey($entry.path)) { throw "Percorso duplicato, anche per maiuscole/minuscole: $($entry.path)" }
        $paths[$entry.path] = $true
    }
    foreach ($path in $paths.Keys) {
        $parent = $path
        while ($parent.Contains('/')) {
            $parent = $parent.Substring(0, $parent.LastIndexOf('/'))
            if ($paths.ContainsKey($parent)) { throw "Un file dell inventario e anche una cartella: $parent" }
        }
    }
}

function Get-NipatRepairTarget([string] $App, [string] $Relative) {
    $root = (Resolve-NipatInstallPath $App).TrimEnd('\')
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative -match '[\\<>:"|?*\x00-\x1f]' -or
        $Relative.StartsWith('/') -or $Relative.EndsWith('/') -or $Relative.Contains('//') -or
        @($Relative.Split('/') | Where-Object { $_ -in @('.', '..') }).Count -gt 0) {
        throw 'Percorso di recupero non valido.'
    }
    $path = [IO.Path]::GetFullPath((Join-Path $root $Relative.Replace('/', '\')))
    if (-not $path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Un percorso di recupero esce dalla cartella applicativa.'
    }
    Assert-NipatInstallPathWithoutLinks ([IO.Path]::GetDirectoryName($path))
    if (Test-Path -LiteralPath $path) {
        $entry = Get-Item -LiteralPath $path -Force
        if ($entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Il file da installare o recuperare e una cartella o un collegamento: $path"
        }
    }
    return $path
}

function Get-NipatRepairFileHash([string] $Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Convert-NipatLegacySourcePayload($Manifest) {
    if ($null -eq $Manifest -or
        -not (($Manifest.schema_version -is [int]) -or ($Manifest.schema_version -is [long])) -or
        $Manifest.schema_version -ne 1 -or $Manifest.source_commit -isnot [string] -or
        $Manifest.source_commit -cnotmatch '^[a-f0-9]{40}$' -or
        $Manifest.source_sha256 -isnot [pscustomobject] -or
        @($Manifest.source_sha256.PSObject.Properties).Count -eq 0) {
        throw 'Inventario dei sorgenti della precedente installazione non valido.'
    }
    Assert-NipatInstallationProfile $Manifest.installation_profile
    $payload = [pscustomobject]@{
        schema_version = 1; installation_channel = (Get-NipatInstallationProfile).channel
        source_commit = $Manifest.source_commit
        files = [object[]]@($Manifest.source_sha256.PSObject.Properties | ForEach-Object {
            [pscustomobject]@{ path = $_.Name; sha256 = $_.Value }
        })
    }
    Assert-NipatApplicationPayload $payload
    return $payload
}

function New-NipatApplicationRepairPlan($Layout, $Payload) {
    Assert-NipatApplicationPayload $Payload
    Assert-NipatInstallLayout $Layout -CheckExisting
    $app = Resolve-NipatInstallPath $Layout.app_dir
    $backups = @{}
    $snapshots = @{}
    $incoming = @{}
    $stale = @()
    $oldInventoryStatus = 'absent'
    $mode = if ((Test-Path -LiteralPath $app -PathType Container) -and
        @(Get-ChildItem -LiteralPath $app -Force).Count -gt 0) { 'repair' } else { 'install' }
    foreach ($entry in $Payload.files) {
        $path = Get-NipatRepairTarget $app $entry.path
        $exists = Test-Path -LiteralPath $path -PathType Leaf
        $hash = if ($exists) { Get-NipatRepairFileHash $path } else { $null }
        $incoming[$entry.path] = $true
        $snapshots[$entry.path] = [pscustomobject]@{ path = $entry.path; original_path = $path; exists = $exists; sha256 = $hash }
        if ($exists -and $hash -cne $entry.sha256) {
            $backups[$entry.path] = [pscustomobject]@{ path = $entry.path; original_path = $path; sha256 = $hash; reason = 'incoming-replacement' }
        }
    }
    foreach ($relative in @('.distribution/application-files.json', '.distribution/installer-manifest.json', '.nipat-app.ini', '.runtime/install-layout.json',
        '.runtime/installer/state.json', '.runtime/backend.json', '.runtime/runtime-image.txt')) {
        $path = Get-NipatRepairTarget $app $relative
        $exists = Test-Path -LiteralPath $path -PathType Leaf
        $hash = if ($exists) { Get-NipatRepairFileHash $path } else { $null }
        $snapshots[$relative] = [pscustomobject]@{ path = $relative; original_path = $path; exists = $exists; sha256 = $hash }
        if ($exists) {
            $backups[$relative] = [pscustomobject]@{ path = $relative; original_path = $path; sha256 = $hash; reason = 'installation-metadata' }
        }
    }
    $python = Join-Path $app '.runtime\python'
    if (Test-Path -LiteralPath $python) {
        Assert-NipatInstallPathWithoutLinks $python -Tree
        foreach ($file in @(Get-ChildItem -LiteralPath $python -File -Recurse -Force)) {
            $relative = $file.FullName.Substring($app.Length + 1).Replace('\', '/')
            $path = Get-NipatRepairTarget $app $relative
            $hash = Get-NipatRepairFileHash $path
            $backups[$relative] = [pscustomobject]@{ path = $relative; original_path = $path; sha256 = $hash; reason = 'generated-python' }
            $snapshots[$relative] = [pscustomobject]@{ path = $relative; original_path = $path; exists = $true; sha256 = $hash }
        }
    }
    $oldInventoryPath = Join-Path $app '.distribution\application-files.json'
    $legacyManifestPath = Join-Path $app '.distribution\installer-manifest.json'
    $oldInventory = $null
    if (Test-Path -LiteralPath $oldInventoryPath -PathType Leaf) {
        try {
            $candidate = Get-Content -LiteralPath $oldInventoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
            Assert-NipatApplicationPayload $candidate
            $oldInventory = $candidate
            $oldInventoryStatus = 'valid'
        } catch {
            # A damaged/older inventory never authorizes deletion. Its bytes are
            # still backed up; the new package may repair the inventory itself.
            $oldInventoryStatus = 'invalid-preserved'
        }
    } elseif (Test-Path -LiteralPath $legacyManifestPath -PathType Leaf) {
        try {
            $candidate = Get-Content -LiteralPath $legacyManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $oldInventory = Convert-NipatLegacySourcePayload $candidate
            $oldInventoryStatus = 'legacy-source-manifest'
        } catch { $oldInventoryStatus = 'invalid-preserved' }
    }
    if ($null -ne $oldInventory) {
        foreach ($entry in $oldInventory.files) {
            if ($incoming.ContainsKey($entry.path)) { continue }
            $path = Get-NipatRepairTarget $app $entry.path
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $hash = Get-NipatRepairFileHash $path
                $reason = if ($hash -ceq $entry.sha256) { 'obsolete-managed-file' } else { 'obsolete-modified-preserved' }
                $record = [pscustomobject]@{ path = $entry.path; original_path = $path; sha256 = $hash; reason = $reason }
                # Inno may retain an old uninstall entry for this path. Keep
                # locally modified obsolete bytes both in place and outside
                # the application, even though they are not deleted here.
                $backups[$entry.path] = $record
                $snapshots[$entry.path] = [pscustomobject]@{ path = $entry.path; original_path = $path; exists = $true; sha256 = $hash }
                if ($hash -ceq $entry.sha256) {
                    $stale += $record
                }
            }
        }
    }
    return [pscustomobject]@{
        Layout = $Layout; Payload = $Payload; Mode = $mode; AppDirectory = $app
        Backups = @($backups.Values | Sort-Object path); Snapshots = @($snapshots.Values | Sort-Object path)
        StaleFiles = @($stale | Sort-Object path); OldInventoryStatus = $oldInventoryStatus
    }
}

function Assert-NipatApplicationRepairSnapshot($Plan) {
    Assert-NipatApplicationPayload $Plan.Payload
    Assert-NipatInstallLayout $Plan.Layout -CheckExisting
    if ((Resolve-NipatInstallPath $Plan.Layout.app_dir) -ine $Plan.AppDirectory) {
        throw 'La destinazione applicativa e cambiata durante la preparazione.'
    }
    foreach ($snapshot in $Plan.Snapshots) {
        $path = Get-NipatRepairTarget $Plan.AppDirectory $snapshot.path
        $exists = Test-Path -LiteralPath $path -PathType Leaf
        if ($exists -ne $snapshot.exists -or
            ($exists -and (Get-NipatRepairFileHash $path) -cne $snapshot.sha256)) {
            throw "Il file e cambiato durante la preparazione: $path. Ripetere il setup dopo aver chiuso NIPAT."
        }
    }
}

function Write-NipatRepairJournal([string] $Path, $Journal) {
    $json = ($Journal | ConvertTo-Json -Depth 12) + "`n"
    $temporary = $Path + '.writing-' + [Guid]::NewGuid().ToString('N')
    try {
        [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Path) }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Copy-NipatRepairBackup([string] $Source, [string] $Destination) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Destination)) | Out-Null
    [IO.File]::Copy($Source, $Destination, $false)
}

function Invoke-NipatApplicationRepairPlan($Plan) {
    Assert-NipatApplicationRepairSnapshot $Plan
    if ($Plan.Backups.Count -eq 0 -and $Plan.Mode -ceq 'install') {
        return [pscustomobject]@{ Mode = $Plan.Mode; BackupDirectory = ''; BackedUpFiles = 0; RemovedFiles = 0 }
    }
    $backupRoot = Join-Path (Get-NipatInstallLayoutHistoryDirectory) 'backups'
    Assert-NipatInstallPathWithoutLinks $backupRoot -Tree
    foreach ($field in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        if (Test-NipatInstallPathOverlap $backupRoot $Plan.Layout.$field) {
            throw 'La cartella dei backup si sovrappone a una destinazione applicativa o di analisi.'
        }
    }
    $backup = Join-Path $backupRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    $files = Join-Path $backup 'files'
    [IO.Directory]::CreateDirectory($files) | Out-Null
    $journalPath = Join-Path $backup 'repair-journal.json'
    $entries = @($Plan.Backups | ForEach-Object {
        [pscustomobject]@{
            path = $_.path; original_path = $_.original_path; sha256 = $_.sha256; reason = $_.reason
            backup_path = (Join-Path $files $_.path.Replace('/', '\'))
        }
    })
    $journal = [ordered]@{
        schema_version = 1; installation_channel = (Get-NipatInstallationProfile).channel
        source_commit = $Plan.Payload.source_commit; app_dir = $Plan.AppDirectory
        created_utc = [DateTime]::UtcNow.ToString('o'); status = 'backing-up'
        old_inventory_status = $Plan.OldInventoryStatus; files = $entries
        removed_files = @(); last_error = $null
    }
    try {
        Write-NipatRepairJournal $journalPath $journal
        foreach ($entry in $entries) {
            $source = Get-NipatRepairTarget $Plan.AppDirectory $entry.path
            if ((Get-NipatRepairFileHash $source) -cne $entry.sha256) { throw "File modificato prima del backup: $source" }
            Assert-NipatInstallPathWithoutLinks $backup -Tree
            Copy-NipatRepairBackup $source $entry.backup_path
            if ((Get-NipatRepairFileHash $entry.backup_path) -cne $entry.sha256) { throw "Backup non verificato: $($entry.path)" }
        }
        # No application file is deleted unless every required copy is intact
        # and all source snapshots still agree with the initial plan.
        Assert-NipatApplicationRepairSnapshot $Plan
        foreach ($entry in $entries) {
            if ((Get-NipatRepairFileHash $entry.backup_path) -cne $entry.sha256) { throw 'Un file del backup e cambiato durante la verifica.' }
        }
        $journal.status = 'backup-verified'
        Write-NipatRepairJournal $journalPath $journal
        foreach ($entry in $Plan.StaleFiles) {
            $path = Get-NipatRepairTarget $Plan.AppDirectory $entry.path
            if ((Get-NipatRepairFileHash $path) -cne $entry.sha256) { throw "File obsoleto modificato prima della rimozione: $path" }
            [IO.File]::Delete($path)
            $journal.removed_files += $entry.path
            Write-NipatRepairJournal $journalPath $journal
        }
        $journal.status = 'prepared-for-copy'
        Write-NipatRepairJournal $journalPath $journal
        Write-Host "Backup dei file sostituiti: $backup"
        return [pscustomobject]@{
            Mode = $Plan.Mode; BackupDirectory = $backup; BackedUpFiles = $entries.Count
            RemovedFiles = $Plan.StaleFiles.Count
        }
    } catch {
        $failure = $_.Exception.Message
        $journal.status = 'failed'
        $journal.last_error = $failure
        try { Write-NipatRepairJournal $journalPath $journal } catch { Write-Host 'Impossibile completare il registro del backup.' }
        throw "Preparazione interrotta: $failure Backup conservato in $backup."
    }
}

if (-not $LibraryOnly) {
    try {
        foreach ($value in @($LayoutFile, $PayloadFile, $ReportFile, $ErrorFile)) {
            if ([string]::IsNullOrWhiteSpace($value)) { throw 'Parametri della preparazione applicativa incompleti.' }
        }
        if (Test-Path -LiteralPath $ReportFile -PathType Leaf) { [IO.File]::Delete($ReportFile) }
        if (Test-Path -LiteralPath $ErrorFile -PathType Leaf) { [IO.File]::Delete($ErrorFile) }
        $layout = Get-Content -LiteralPath $LayoutFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $payload = Get-Content -LiteralPath $PayloadFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $plan = New-NipatApplicationRepairPlan $layout $payload
        $result = Invoke-NipatApplicationRepairPlan $plan
        [IO.File]::WriteAllLines($ReportFile,
            [string[]]@('[NIPAT]', ('mode=' + $result.Mode), ('backup_dir=' + $result.BackupDirectory)), [Text.Encoding]::Unicode)
        exit 0
    } catch {
        $failure = $_.Exception.Message
        try { [IO.File]::WriteAllText($ErrorFile, $failure, (New-Object Text.UTF8Encoding($false))) }
        catch { [Console]::Error.WriteLine('Impossibile registrare il motivo del mancato ripristino applicativo.') }
        exit 1
    }
}
