param(
    [Parameter(Mandatory = $true)][string] $Descriptor,
    [switch] $NoPause
)

# Standalone worker copied outside the application before the current CLI exits.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$directory = Split-Path -Parent ([IO.Path]::GetFullPath($Descriptor))
$cancelFile = Join-Path $directory 'cancel'
$logFile = Join-Path $directory 'handoff.log'
$packageStream = $null
$activity = $null
$parent = $null
$result = 1

function Write-HandoffLog([string] $Message) {
    [IO.File]::AppendAllText($logFile, ([DateTime]::UtcNow.ToString('o') + ' ' + $Message + "`r`n"),
        (New-Object Text.UTF8Encoding($false)))
    Write-Host $Message
}

function Assert-NotCanceled {
    if (Test-Path -LiteralPath $cancelFile) { throw 'Aggiornamento annullato: nessun installer viene avviato.' }
}

function Assert-LocalPath([string] $Path) {
    if ($Path -cnotmatch '^[A-Za-z]:\\' -or $Path.Substring(2) -match '[<>:"|?*\x00-\x1f]') {
        throw 'Il passaggio all installer richiede percorsi assoluti su dischi locali.'
    }
    $full = [IO.Path]::GetFullPath($Path)
    $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($full))
    if (-not $drive.IsReady -or $drive.DriveType -ne [IO.DriveType]::Fixed) { throw 'Disco locale non disponibile.' }
    $current = $full
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if (((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Il percorso del componente di aggiornamento contiene un collegamento.'
            }
        }
        $next = [IO.Path]::GetDirectoryName($current.TrimEnd('\'))
        if ($next -eq $current) { break }
        $current = $next
    }
    return $full
}

function Quote-HandoffArgument([string] $Value) {
    # Windows argv quoting, without interpreting any value as PowerShell or cmd source.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Write-HandoffJson([string] $Name, $Value) {
    $file = Join-Path $directory $Name
    $temporary = Join-Path $directory ([Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
        [IO.File]::Move($temporary, $file)
    } finally { if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) } }
}

try {
    Assert-NotCanceled
    Assert-LocalPath $Descriptor | Out-Null
    $record = Get-Content -LiteralPath $Descriptor -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($record.PSObject.Properties).Count -ne 10 -or $record.schema_version -ne 1 -or
        $record.installation_channel -cne 'desktop' -or $record.parent_pid -le 0 -or
        $record.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $record.size -le 0 -or
        $record.source_commit -cnotmatch '^[a-f0-9]{40}$' -or
        $record.version -cnotmatch '^\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?$') {
        throw 'Richiesta di aggiornamento non valida.'
    }
    $project = Assert-LocalPath $record.project_dir
    $package = Assert-LocalPath $record.package
    $data = Assert-LocalPath $record.data_dir
    if (-not (Test-Path -LiteralPath $project -PathType Container) -or
        -not (Test-Path -LiteralPath $package -PathType Leaf) -or [IO.Path]::GetExtension($package) -ine '.exe') {
        throw 'Installer o applicazione non disponibili.'
    }
    $parent = [Diagnostics.Process]::GetProcessById([int] $record.parent_pid)
    # Opening the process handle before acknowledgement avoids a reused PID.
    $null = $parent.Handle
    Assert-NotCanceled
    Write-HandoffJson 'ready.json' ([ordered]@{ schema_version = 1; worker_pid = $PID; parent_pid = [int]$record.parent_pid })
    Write-HandoffLog 'Chiusura della sessione NIPAT in corso...'
    $deadline = [DateTime]::UtcNow.AddMinutes(2)
    while (-not $parent.WaitForExit(100)) {
        Assert-NotCanceled
        if ([DateTime]::UtcNow -gt $deadline) { throw 'La sessione NIPAT non si e chiusa. Ripetere l aggiornamento dal menu.' }
    }
    Assert-NotCanceled
    if ($parent.ExitCode -ne 85) {
        throw 'La sessione non ha confermato il passaggio all installer. Nessun aggiornamento viene avviato.'
    }
    $lockPath = Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop\activity.lock'
    Assert-LocalPath $lockPath | Out-Null
    try { $activity = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch { throw 'Sono aperte altre sessioni o analisi NIPAT. Chiuderle al termine del lavoro e ripetere l aggiornamento. Nessuna analisi e stata interrotta.' }
    $packageStream = [IO.File]::Open($package, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    if ($packageStream.Length -ne $record.size) { throw 'Dimensione dell installer modificata. Ripetere il download.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($sha.ComputeHash($packageStream)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($digest -cne $record.sha256) { throw 'SHA-256 dell installer modificato. Nessun file viene eseguito.' }
    Assert-NotCanceled
    # Inno repeats this exclusive acquisition before modifying any application file.
    $activity.Dispose(); $activity = $null
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $package
    $start.Arguments = '/NIPATUPDATE=1 /NORESTART /DIR=' + (Quote-HandoffArgument $project)
    $start.WorkingDirectory = $directory
    $start.UseShellExecute = $false
    Assert-NotCanceled
    Write-HandoffLog ('Avvio installer NIPAT ' + $record.version + '...')
    $installer = [Diagnostics.Process]::Start($start)
    try { $installer.WaitForExit(); $code = $installer.ExitCode } finally { $installer.Dispose() }
    $packageStream.Dispose(); $packageStream = $null
    if ($code -eq 3010) {
        Write-HandoffLog 'Riavvio di Windows richiesto. Riavviare il PC e completare la preparazione dal menu Start.'
        $result = 3010
    } elseif ($code -ne 0) {
        throw "Installazione non completata (codice $code). Consultare il setup e riprendere la preparazione dal menu Start."
    } else {
        # The existing entry point performs the full ready/manifest/runtime binding check.
        $runner = Join-Path $project 'scripts\windows\run.ps1'
        $stateFile = Join-Path $project '.runtime\installer\state.json'
        $state = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.phase -cne 'ready' -or $state.installation_channel -cne 'desktop' -or
            $state.version -cne $record.version -or $state.source_commit -cne $record.source_commit) {
            throw 'Preparazione non conclusa. Completare NIPAT Desktop dal menu Start prima di avviare analisi.'
        }
        $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $launch = New-Object Diagnostics.ProcessStartInfo
        $launch.FileName = $powershell
        $launch.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' + (Quote-HandoffArgument $runner) + ' wizard'
        $launch.WorkingDirectory = $data
        $launch.UseShellExecute = $false
        $launch.EnvironmentVariables.Remove('NIPAT_SETUP_ACTIVITY_TOKEN')
        $opened = [Diagnostics.Process]::Start($launch)
        $opened.Dispose()
        Write-HandoffLog 'Installer completato. Avvio di NIPAT tramite il controllo dell installazione.'
        $result = 0
    }
} catch {
    $message = $_.Exception.Message
    [IO.File]::WriteAllText((Join-Path $directory 'error.txt'), $message, (New-Object Text.UTF8Encoding($false)))
    Write-HandoffLog ('ERRORE: ' + $message)
} finally {
    if ($null -ne $packageStream) { $packageStream.Dispose() }
    if ($null -ne $activity) { $activity.Dispose() }
    if ($null -ne $parent) { $parent.Dispose() }
}
if ($result -ne 0 -and -not $NoPause) {
    Write-Host ('Diagnostica: ' + $directory)
    Read-Host 'Premere Invio per chiudere questa finestra' | Out-Null
}
exit $result
