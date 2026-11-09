# Exclusive process-lifetime lease for setup/resume/removal. Dot-sourcing has no side effects.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NipatActivityAssemblyPath([string] $Directory = $PSScriptRoot) {
    $assembly = Join-Path $Directory 'NipatActivityNative.dll'
    Assert-NipatActivityPathWithoutLinks $assembly
    if (-not (Test-Path -LiteralPath $assembly -PathType Leaf)) {
        throw 'Componente di coordinamento NIPAT mancante. Ripristinare il pacchetto con NIPAT-Setup.exe; per i sorgenti eseguire build-native.ps1 sulla macchina di sviluppo.'
    }
    $project = Split-Path -Parent (Split-Path -Parent $Directory)
    $inventoryPath = Join-Path $project '.distribution\application-files.json'
    $manifestPath = Join-Path $project '.distribution\installer-manifest.json'
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) {
            throw 'Inventario del pacchetto NIPAT mancante. Ripristinare con NIPAT-Setup.exe.'
        }
        $inventory = Get-Content -LiteralPath $inventoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $entries = @($inventory.files | Where-Object { $_.path -ceq 'installer/windows/NipatActivityNative.dll' })
        if ($inventory.schema_version -ne 1 -or $inventory.installation_channel -cne 'desktop' -or
            $inventory.source_commit -cne $manifest.source_commit -or $entries.Count -ne 1 -or
            $entries[0].sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entries[0].sha256) {
            throw 'Il componente di coordinamento non corrisponde al pacchetto verificato. Ripristinare con NIPAT-Setup.exe.'
        }
    }
    return $assembly
}

function Initialize-NipatActivityNative {
    if ('NipatActivityNative' -as [type]) { return }
    $assembly = Get-NipatActivityAssemblyPath
    Add-Type -Path $assembly
}

function Assert-NipatActivityPathWithoutLinks([string] $Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if (((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'La cartella di coordinamento NIPAT non puo attraversare collegamenti o junction.'
            }
        }
        $parent = [IO.Path]::GetDirectoryName($current.TrimEnd('\'))
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
}

function Get-NipatActivityLockPath {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA) -or $env:LOCALAPPDATA -notmatch '^[A-Za-z]:[\\/]') {
        throw 'LOCALAPPDATA non disponibile per coordinare le sessioni NIPAT.'
    }
    $path = Join-Path (Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop') 'activity.lock'
    Assert-NipatActivityPathWithoutLinks $path
    [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
    Assert-NipatActivityPathWithoutLinks $path
    return $path
}

function Enter-NipatInstallationActivity {
    Initialize-NipatActivityNative
    $previousToken = [Environment]::GetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', 'Process')
    if ([NipatActivityNative]::IsAuthorizedSetupChild($previousToken)) {
        # The actual ancestor keeps both the exclusive file handle and event alive.
        return [pscustomobject]@{ Borrowed = $true; Handle = $null; Event = $null; Token = $previousToken }
    }
    $handle = $null
    $event = $null
    try {
        $path = Get-NipatActivityLockPath
        try { $handle = [NipatActivityNative]::OpenExclusive($path) }
        catch {
            throw 'NIPAT non e disponibile per la preparazione: attendere il termine delle analisi e chiudere tutte le finestre NIPAT, quindi riprovare. Nessuna sessione viene interrotta.'
        }
        $nonce = [Guid]::NewGuid().ToString('N')
        $created = $false
        $event = [Threading.EventWaitHandle]::new($false, [Threading.EventResetMode]::ManualReset,
            ('Local\NIPAT-Desktop-SetupLease-' + $nonce), [ref] $created)
        if (-not $created) { throw 'Il coordinamento temporaneo NIPAT non e stato creato; riprovare.' }
        $token = "$PID`:$nonce"
        [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', $token, 'Process')
        return [pscustomobject]@{ Borrowed = $false; Handle = $handle; Event = $event; Token = $token }
    } catch {
        [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', $null, 'Process')
        if ($null -ne $event) { $event.Dispose() }
        if ($null -ne $handle) { $handle.Dispose() }
        throw
    }
}

function Exit-NipatInstallationActivity($Lease) {
    if ($null -eq $Lease -or $Lease.Borrowed) { return }
    try {
        [Environment]::SetEnvironmentVariable('NIPAT_SETUP_ACTIVITY_TOKEN', $null, 'Process')
        if ($null -ne $Lease.Event) { $Lease.Event.Dispose() }
    } finally {
        if ($null -ne $Lease.Handle) { $Lease.Handle.Dispose() }
    }
}
