param(
    [string]$InstallerPath,
    [string]$ApplicationDirectory,
    [ValidateRange(1, 168)][int]$Hours = 24,
    [ValidateRange(1, 100)][int]$MaxEvents = 30,
    [string]$OutputPath = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'NIPAT-Windows-security.json')
)

# Read-only diagnostics. No security settings, policies, exclusions, signatures
# or installation files are changed. The only write is the requested report.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$output = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $output) { throw 'Il file di diagnosi esiste gia; scegliere un altro OutputPath.' }

function Protect-NipatDiagnosticPath([string]$Value) {
    if ($null -eq $Value) { return $null }
    if ($env:USERPROFILE) {
        $Value = [regex]::Replace($Value, [regex]::Escape($env:USERPROFILE), '%USERPROFILE%', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    }
    # CodeIntegrity often uses NT device paths instead of a drive letter.
    return [regex]::Replace($Value, '(?:[A-Z]:|\\Device\\[^\\]+)?\\Users\\[^\\]+',
        '%USERPROFILE%', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

function Get-NipatDiagnosticFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = (Protect-NipatDiagnosticPath $Path); status = 'missing' }
    }
    $file = Get-Item -LiteralPath $Path
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    $publisher = $null
    if ($null -ne $signature.SignerCertificate) { $publisher = $signature.SignerCertificate.Subject }
    return [ordered]@{
        path = (Protect-NipatDiagnosticPath $file.FullName)
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        size = $file.Length
        signature_status = [string]$signature.Status
        publisher = $publisher
    }
}

$files = New-Object 'Collections.Generic.List[object]'
if ($InstallerPath) { $files.Add((Get-NipatDiagnosticFile $InstallerPath)) }
if ($ApplicationDirectory) {
    foreach ($relative in @('NIPAT.exe', 'installer\windows\EnableWsl.exe',
        'installer\windows\NipatActivityNative.dll', 'installer\windows\activity-lock.ps1',
        'installer\windows\bootstrap.ps1', 'unins000.exe')) {
        $files.Add((Get-NipatDiagnosticFile (Join-Path $ApplicationDirectory $relative)))
    }
}
$events = New-Object 'Collections.Generic.List[object]'
$eventStatus = 'available'
$eventError = $null
try {
    $observed = @(Get-WinEvent -FilterHashtable @{
        LogName = 'Microsoft-Windows-CodeIntegrity/Operational'
        Id = @(3076, 3077)
        StartTime = (Get-Date).AddHours(-$Hours)
    } -MaxEvents $MaxEvents -ErrorAction Stop)
    foreach ($event in $observed) {
        $xml = [xml]$event.ToXml()
        $fields = [ordered]@{}
        # Do not include messages, command lines, arbitrary XML or file content.
        foreach ($datum in $xml.Event.EventData.Data) {
            if ([string]$datum.Name -in @('FileName', 'ProcessName', 'PolicyName', 'PolicyId',
                'PolicyID', 'Status', 'RequestedSigningLevel', 'ValidatedSigningLevel', 'FileHash')) {
                $fields[[string]$datum.Name] = Protect-NipatDiagnosticPath ([string]$datum.InnerText)
            }
        }
        $events.Add([ordered]@{
            event_id = $event.Id; record_id = $event.RecordId
            time_utc = $event.TimeCreated.ToUniversalTime().ToString('o'); fields = $fields
        })
    }
} catch {
    if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { $eventStatus = 'no-matching-events' }
    else { $eventStatus = 'unavailable'; $eventError = $_.FullyQualifiedErrorId }
}
$sac = [ordered]@{ status = 'unavailable'; registry_value = $null }
try {
    $policy = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -Name VerifiedAndReputablePolicyState -ErrorAction Stop
    $sac = [ordered]@{ status = 'observed'; registry_value = $policy.VerifiedAndReputablePolicyState }
} catch { }
$os = [Environment]::OSVersion.Version.ToString()
$report = [ordered]@{
    schema_version = 1
    generated_utc = [DateTime]::UtcNow.ToString('o')
    windows_version = $os
    powershell_version = $PSVersionTable.PSVersion.ToString()
    scope = 'read-only-code-integrity-diagnostics'
    smart_app_control = $sac
    files = @($files.ToArray())
    event_window_hours = $Hours; event_limit = $MaxEvents
    event_query_status = $eventStatus; event_query_error = $eventError
    events = @($events.ToArray())
}
[IO.Directory]::CreateDirectory((Split-Path -Parent $output)) | Out-Null
[IO.File]::WriteAllText($output, ($report | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
Write-Host "Diagnosi salvata: $output"
Write-Host 'Nessuna impostazione di sicurezza e stata modificata. Il rapporto non contiene dati delle analisi.'
