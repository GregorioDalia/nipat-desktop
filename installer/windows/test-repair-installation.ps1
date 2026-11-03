# Real temporary-file repair tests. No installed NIPAT, WSL, registry mutation,
# administrator privileges or network connection is required.
. (Join-Path $PSScriptRoot 'repair-installation.ps1') -LibraryOnly
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-repair-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$oldLocalAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = Join-Path $temporary 'isolated user profile'
$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:checks++
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}
function Write-RepairTestJson([string] $Path, $Value) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 12), (New-Object Text.UTF8Encoding($false)))
}
function Get-RepairTestHash([string] $Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function New-RepairTestPayload($Entries) {
    return [pscustomobject]@{
        schema_version = 1; installation_channel = 'desktop'; source_commit = ('a' * 40)
        files = [object[]]@($Entries)
    }
}
function Add-RepairTestFile([string] $App, [string] $Relative, [string] $Text) {
    $path = Join-Path $App $Relative.Replace('/', '\')
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
    [IO.File]::WriteAllText($path, $Text, (New-Object Text.UTF8Encoding($false)))
    return $path
}
function New-RepairTestLayout([string] $Name, [switch] $Empty) {
    $root = Join-Path $temporary $Name
    [IO.Directory]::CreateDirectory($root) | Out-Null
    $layout = [pscustomobject]@{
        schema_version = 1; installation_channel = 'desktop'; app_dir = (Join-Path $root 'app')
        runtime_dir = (Join-Path $root 'wsl'); cache_dir = (Join-Path $root 'cache')
        data_dir = (Join-Path $root 'research'); runs_dir = (Join-Path $root 'results')
    }
    if (-not $Empty) {
        Add-RepairTestFile $layout.app_dir '.nipat-app.ini' "[NIPAT]`nschema_version=1`ninstallation_channel=desktop`nrole=application`n" | Out-Null
    }
    return $layout
}
function Get-RepairTestJournals([string] $App) {
    $root = Join-Path (Get-NipatInstallLayoutHistoryDirectory) 'backups'
    if (-not (Test-Path -LiteralPath $root)) { return @() }
    return @(Get-ChildItem -LiteralPath $root -Filter 'repair-journal.json' -File -Recurse | ForEach-Object {
        $journal = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($journal.app_dir -ieq $App) { [pscustomobject]@{ Path = $_.FullName; Journal = $journal } }
    })
}

try {
    $payload = New-RepairTestPayload @(
        [pscustomobject]@{ path = 'README.md'; sha256 = (Get-RepairTestHash 'new readme') },
        [pscustomobject]@{ path = 'src/client.py'; sha256 = (Get-RepairTestHash 'new source') }
    )
    $layout = New-RepairTestLayout 'fresh' -Empty
    $plan = New-NipatApplicationRepairPlan $layout $payload
    $result = Invoke-NipatApplicationRepairPlan $plan
    Assert-Test ($result.Mode -ceq 'install' -and $result.BackupDirectory -ceq '' -and
        -not (Test-Path -LiteralPath $layout.app_dir)) 'fresh install neither creates backups nor writes application files'

    $layout = New-RepairTestLayout ('collision & unicode ' + [char]0x00E8)
    $collision = Add-RepairTestFile $layout.app_dir 'README.md' 'Researcher custom notes using this filename.'
    $unchanged = Add-RepairTestFile $layout.app_dir 'src/client.py' 'new source'
    $unknown = Add-RepairTestFile $layout.app_dir 'local-research.csv' 'subject,value'
    $data = Add-RepairTestFile $layout.data_dir 'input.txt' 'Original input.'
    $state = Add-RepairTestFile $layout.app_dir '.runtime/installer/state.json' '{"phase":"failed"}'
    Add-RepairTestFile $layout.app_dir '.runtime/install-layout.json' '{"previous":"layout"}' | Out-Null
    Add-RepairTestFile $layout.app_dir '.runtime/backend.json' '{"previous":"backend"}' | Out-Null
    Add-RepairTestFile $layout.app_dir '.runtime/runtime-image.txt' 'sha256:previous' | Out-Null
    Add-RepairTestFile $layout.app_dir '.runtime/python/python.exe' 'Previous embedded Python fixture.' | Out-Null
    Add-RepairTestFile $layout.app_dir '.runtime/python/user-helper.py' 'Unknown Python neighbor retained.' | Out-Null
    $plan = New-NipatApplicationRepairPlan $layout $payload
    Assert-Test (@($plan.Backups | Where-Object { $_.path -ceq 'README.md' }).Count -eq 1 -and
        @($plan.Backups | Where-Object { $_.path -ceq 'src/client.py' }).Count -eq 0) 'different incoming file is backed up; identical incoming file is snapshotted only'
    Assert-Test ($plan.Backups.Count -eq 8 -and $plan.StaleFiles.Count -eq 0) 'metadata, app marker and the entire Python file tree are included'
    $before = Get-NipatRepairFileHash $collision
    $result = Invoke-NipatApplicationRepairPlan $plan
    Assert-Test ($result.Mode -ceq 'repair' -and (Test-Path -LiteralPath $result.BackupDirectory -PathType Container)) 'repair provides a persistent backup directory'
    $saved = Join-Path $result.BackupDirectory 'files\README.md'
    Assert-Test ((Get-NipatRepairFileHash $saved) -ceq $before -and (Get-NipatRepairFileHash $collision) -ceq $before) 'colliding user content is preserved both in place and in backup before Inno copy'
    Assert-Test ((Test-Path -LiteralPath $unknown) -and (Test-Path -LiteralPath $data) -and
        (Test-Path -LiteralPath $unchanged) -and (Test-Path -LiteralPath $state)) 'unknown files, research input and existing application metadata are not deleted'
    $journal = Get-Content -LiteralPath (Join-Path $result.BackupDirectory 'repair-journal.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($journal.status -ceq 'prepared-for-copy' -and $journal.files.Count -eq 8 -and
        $journal.source_commit -ceq $payload.source_commit -and $journal.app_dir -ceq $layout.app_dir) 'journal records verified files, source identity and original directory'
    foreach ($entry in $journal.files) {
        Assert-Test ((Get-NipatRepairFileHash $entry.backup_path) -ceq $entry.sha256) ('backup hash matches: ' + $entry.path)
    }
    $again = Invoke-NipatApplicationRepairPlan (New-NipatApplicationRepairPlan $layout $payload)
    Assert-Test ($again.BackupDirectory -cne $result.BackupDirectory -and
        (Test-Path -LiteralPath $result.BackupDirectory)) 'a repeated preparation keeps the first backup and creates a distinct journal'

    $legacy = Get-NipatDefaultInstallLayout
    Write-RepairTestJson (Join-Path $legacy.app_dir '.runtime\installer\state.json') ([pscustomobject]@{
        schema_version = 1; installation_channel = 'desktop'; phase = 'ready'
        rootfs_sha256 = ('c' * 64); source_commit = ('b' * 40)
    })
    $legacyNeighbor = Add-RepairTestFile $legacy.app_dir 'local-notes.txt' 'Neighbor left beside generated runtime.'
    $legacyResult = Invoke-NipatApplicationRepairPlan (New-NipatApplicationRepairPlan $legacy $payload)
    Assert-Test ($legacyResult.Mode -ceq 'repair' -and (Test-Path -LiteralPath $legacyNeighbor)) 'recognized legacy remnants can be repaired without deleting unrelated neighbors'

    $layout = New-RepairTestLayout 'obsolete inventory'
    $obsolete = Add-RepairTestFile $layout.app_dir 'obsolete.py' 'unchanged old module'
    $modified = Add-RepairTestFile $layout.app_dir 'modified.py' 'locally edited old module'
    $extra = Add-RepairTestFile $layout.app_dir 'extra.tsv' 'unlisted research result'
    $old = New-RepairTestPayload @(
        [pscustomobject]@{ path = 'obsolete.py'; sha256 = (Get-RepairTestHash 'unchanged old module') },
        [pscustomobject]@{ path = 'modified.py'; sha256 = (Get-RepairTestHash 'original old module') }
    )
    $oldInventoryPath = Join-Path $layout.app_dir '.distribution\application-files.json'
    Write-RepairTestJson $oldInventoryPath $old
    $plan = New-NipatApplicationRepairPlan $layout $payload
    Assert-Test ($plan.StaleFiles.Count -eq 1 -and $plan.StaleFiles[0].path -ceq 'obsolete.py') 'only absent-from-new and byte-identical old files qualify for removal'
    $result = Invoke-NipatApplicationRepairPlan $plan
    Assert-Test (-not (Test-Path -LiteralPath $obsolete) -and (Test-Path -LiteralPath $modified) -and
        (Test-Path -LiteralPath $extra) -and (Test-Path -LiteralPath $oldInventoryPath)) 'obsolete managed file is removed while modified, unlisted and old inventory files remain before copy'
    Assert-Test ((Test-Path -LiteralPath (Join-Path $result.BackupDirectory 'files\obsolete.py')) -and
        (Test-Path -LiteralPath (Join-Path $result.BackupDirectory 'files\.distribution\application-files.json'))) 'deleted managed file and previous inventory both have verified backups'
    Assert-Test ((Get-NipatRepairFileHash (Join-Path $result.BackupDirectory 'files\modified.py')) -ceq
        (Get-NipatRepairFileHash $modified) -and
        @($plan.Backups | Where-Object { $_.path -ceq 'modified.py' -and $_.reason -ceq 'obsolete-modified-preserved' }).Count -eq 1) 'locally modified obsolete bytes also have an external backup for a later uninstall'

    $layout = New-RepairTestLayout 'damaged old inventory'
    $preserved = Add-RepairTestFile $layout.app_dir 'old.py' 'possibly managed but unverifiable'
    Add-RepairTestFile $layout.app_dir '.distribution/application-files.json' '{invalid inventory' | Out-Null
    $plan = New-NipatApplicationRepairPlan $layout $payload
    Assert-Test ($plan.OldInventoryStatus -ceq 'invalid-preserved' -and $plan.StaleFiles.Count -eq 0) 'damaged previous inventory never grants deletion authority'
    $result = Invoke-NipatApplicationRepairPlan $plan
    Assert-Test ((Test-Path -LiteralPath $preserved) -and
        (Test-Path -LiteralPath (Join-Path $result.BackupDirectory 'files\.distribution\application-files.json'))) 'old inventory is preserved for diagnosis while new package may repair it'

    $layout = New-RepairTestLayout 'legacy source inventory'
    $obsolete = Add-RepairTestFile $layout.app_dir 'old-exact.py' 'old exact source'
    $modified = Add-RepairTestFile $layout.app_dir 'old-modified.py' 'researcher modification'
    $legacyManifest = [pscustomobject]@{
        schema_version = 1; installation_profile = (Get-NipatInstallationProfile); source_commit = ('b' * 40)
        source_sha256 = [pscustomobject]@{
            'old-exact.py' = (Get-RepairTestHash 'old exact source')
            'old-modified.py' = (Get-RepairTestHash 'original source')
        }
    }
    Write-RepairTestJson (Join-Path $layout.app_dir '.distribution\installer-manifest.json') $legacyManifest
    $plan = New-NipatApplicationRepairPlan $layout $payload
    Assert-Test ($plan.OldInventoryStatus -ceq 'legacy-source-manifest' -and $plan.StaleFiles.Count -eq 1) 'pre-inventory installations use their validated source manifest'
    $result = Invoke-NipatApplicationRepairPlan $plan
    Assert-Test (-not (Test-Path -LiteralPath $obsolete) -and (Test-Path -LiteralPath $modified) -and
        (Get-NipatRepairFileHash (Join-Path $result.BackupDirectory 'files\old-modified.py')) -ceq (Get-NipatRepairFileHash $modified)) 'legacy source cleanup removes exact obsolete bytes and backs up modified bytes without deleting them'
    Assert-Test (Test-Path -LiteralPath (Join-Path $result.BackupDirectory 'files\.distribution\installer-manifest.json')) 'legacy manifest itself is always backed up'

    $layout = New-RepairTestLayout 'invalid modern inventory blocks fallback'
    $obsolete = Add-RepairTestFile $layout.app_dir 'old-exact.py' 'old exact source'
    Write-RepairTestJson (Join-Path $layout.app_dir '.distribution\installer-manifest.json') $legacyManifest
    Add-RepairTestFile $layout.app_dir '.distribution/application-files.json' '{invalid modern inventory' | Out-Null
    $plan = New-NipatApplicationRepairPlan $layout $payload
    Assert-Test ($plan.OldInventoryStatus -ceq 'invalid-preserved' -and $plan.StaleFiles.Count -eq 0) 'invalid present modern inventory never falls back to an older deletion authority'
    Invoke-NipatApplicationRepairPlan $plan | Out-Null
    Assert-Test (Test-Path -LiteralPath $obsolete) 'invalid current inventory preserves formerly listed source bytes'

    foreach ($bad in @('../outside.txt', '/absolute.txt', 'folder\file.txt', 'C:/other.txt',
        'folder//file.txt', './file.txt', '.git/config', 'folder/.runtime/state.json',
        'folder/CON.txt', 'folder/trailing.', '.distribution/application-files.json')) {
        $invalid = New-RepairTestPayload @([pscustomobject]@{ path = $bad; sha256 = ('a' * 64) })
        Assert-Rejected { Assert-NipatApplicationPayload $invalid } ('unsafe incoming path rejected: ' + $bad)
    }
    $invalid = New-RepairTestPayload @(
        [pscustomobject]@{ path = 'Readme.md'; sha256 = ('a' * 64) },
        [pscustomobject]@{ path = 'README.md'; sha256 = ('b' * 64) }
    )
    Assert-Rejected { Assert-NipatApplicationPayload $invalid } 'case-insensitive payload collision is rejected'
    $invalid = New-RepairTestPayload @(
        [pscustomobject]@{ path = 'folder'; sha256 = ('a' * 64) },
        [pscustomobject]@{ path = 'folder/file'; sha256 = ('b' * 64) }
    )
    Assert-Rejected { Assert-NipatApplicationPayload $invalid } 'payload file/directory prefix collision is rejected'

    $layout = New-RepairTestLayout 'file versus directory'
    [IO.Directory]::CreateDirectory((Join-Path $layout.app_dir 'README.md')) | Out-Null
    Assert-Rejected { New-NipatApplicationRepairPlan $layout $payload } 'incoming file cannot replace an existing directory'
    Assert-Test (@(Get-RepairTestJournals $layout.app_dir).Count -eq 0) 'directory conflict creates no backup and makes no app changes'
    $layout = New-RepairTestLayout 'parent is file'
    $parentFile = Add-RepairTestFile $layout.app_dir 'src' 'User content in parent filename.'
    Assert-Rejected { New-NipatApplicationRepairPlan $layout $payload } 'incoming directory cannot replace an existing parent file'
    Assert-Test ((Test-Path -LiteralPath $parentFile -PathType Leaf)) 'parent file remains untouched'

    $layout = New-RepairTestLayout 'research overlap'
    $layout.data_dir = $layout.app_dir
    Assert-Rejected { New-NipatApplicationRepairPlan $layout $payload } 'application/research overlap is rejected'

    $layout = New-RepairTestLayout 'failed backup'
    $colliding = Add-RepairTestFile $layout.app_dir 'README.md' 'Local readme.'
    $obsolete = Add-RepairTestFile $layout.app_dir 'obsolete.py' 'obsolete bytes'
    Write-RepairTestJson (Join-Path $layout.app_dir '.distribution\application-files.json') (New-RepairTestPayload @(
        [pscustomobject]@{ path = 'obsolete.py'; sha256 = (Get-RepairTestHash 'obsolete bytes') }
    ))
    $plan = New-NipatApplicationRepairPlan $layout $payload
    $copy = (Get-Command Copy-NipatRepairBackup).ScriptBlock
    $script:BackupCalls = 0
    function Copy-NipatRepairBackup([string] $Source, [string] $Destination) {
        $script:BackupCalls++
        if ($script:BackupCalls -eq 2) { throw 'Simulated disk/copy failure.' }
        & $script:copy $Source $Destination
    }
    try {
        Assert-Rejected { Invoke-NipatApplicationRepairPlan $plan } 'failed backup blocks all managed-file deletion'
    } finally { Set-Item Function:Copy-NipatRepairBackup -Value $copy }
    Assert-Test ((Test-Path -LiteralPath $obsolete) -and (Test-Path -LiteralPath $colliding)) 'application files remain intact after backup failure'
    $failed = @(Get-RepairTestJournals $layout.app_dir)
    Assert-Test ($failed.Count -eq 1 -and $failed[0].Journal.status -ceq 'failed' -and
        $failed[0].Journal.removed_files.Count -eq 0) 'failed backup remains outside app with an explicit failure journal'

    $layout = New-RepairTestLayout 'source changes during repair'
    $source = Add-RepairTestFile $layout.app_dir 'README.md' 'new readme'
    $plan = New-NipatApplicationRepairPlan $layout $payload
    [IO.File]::WriteAllText($source, 'Changed since initial snapshot.')
    Assert-Rejected { Invoke-NipatApplicationRepairPlan $plan } 'a changed originally-identical incoming file invalidates the plan'
    Assert-Test (@(Get-RepairTestJournals $layout.app_dir).Count -eq 0) 'snapshot mismatch is detected before creating a backup directory'

    $layout = New-RepairTestLayout 'junction refusal'
    $outside = Join-Path $temporary 'outside protected research'
    [IO.Directory]::CreateDirectory($outside) | Out-Null
    $sentinel = Add-RepairTestFile $outside 'keep.txt' 'Do not follow this directory.'
    $junction = Join-Path $layout.app_dir 'linked-data'
    New-Item -ItemType Junction -Path $junction -Target $outside | Out-Null
    try {
        Assert-Rejected { New-NipatApplicationRepairPlan $layout $payload } 'junction anywhere in existing application blocks repair'
        Assert-Test ((Test-Path -LiteralPath $sentinel) -and @(Get-RepairTestJournals $layout.app_dir).Count -eq 0) 'junction target and application are untouched'
    } finally { [IO.Directory]::Delete($junction, $false) }

    # Run the production CLI in a separate PowerShell process to check actual
    # exit codes and the encoding required by the Inno Unicode INI reader.
    $cli = Join-Path $temporary ('CLI files & ' + [char]0x00E8)
    [IO.Directory]::CreateDirectory($cli) | Out-Null
    $layout = New-RepairTestLayout 'cli fresh' -Empty
    $layoutPath = Join-Path $cli 'layout.json'
    $payloadPath = Join-Path $cli 'payload.json'
    $reportPath = Join-Path $cli 'report.ini'
    $errorPath = Join-Path $cli 'error.txt'
    Write-RepairTestJson $layoutPath $layout
    Write-RepairTestJson $payloadPath $payload
    $powershell = (Get-Process -Id $PID).Path
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'repair-installation.ps1') `
        -LayoutFile $layoutPath -PayloadFile $payloadPath -ReportFile $reportPath -ErrorFile $errorPath
    Assert-Test ($LASTEXITCODE -eq 0) 'production repair CLI completes for a fresh layout'
    $reportBytes = [IO.File]::ReadAllBytes($reportPath)
    $report = [IO.File]::ReadAllText($reportPath, [Text.Encoding]::Unicode)
    Assert-Test ($reportBytes[0] -eq 255 -and $reportBytes[1] -eq 254 -and
        $report.Contains('mode=install') -and $report.Contains('backup_dir=')) 'CLI writes a UTF-16 INI report with the expected fields'
    $invalid = New-RepairTestPayload @([pscustomobject]@{ path = '../invalid'; sha256 = ('a' * 64) })
    Write-RepairTestJson $payloadPath $invalid
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'repair-installation.ps1') `
        -LayoutFile $layoutPath -PayloadFile $payloadPath -ReportFile $reportPath -ErrorFile $errorPath
    Assert-Test ($LASTEXITCODE -eq 1 -and -not (Test-Path -LiteralPath $reportPath) -and
        (Test-Path -LiteralPath $errorPath)) 'failed CLI removes stale success report and writes an error'
    $errorBytes = [IO.File]::ReadAllBytes($errorPath)
    Assert-Test (-not ($errorBytes.Length -ge 3 -and $errorBytes[0] -eq 239 -and
        $errorBytes[1] -eq 187 -and $errorBytes[2] -eq 191)) 'CLI error uses UTF-8 without BOM'

    Write-Host "PASS: $checks application repair assertions."
} finally {
    $env:LOCALAPPDATA = $oldLocalAppData
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
