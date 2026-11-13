#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{40}$')][string] $SourceCommit,
    [string] $AppDirectory = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ExpectedManifestSha256 = '21ddf301c9e6faa1c663f24427585e285ee24b8c841520e5c690ea3b8755a61a'
$installationCommit = 'b54ef493ba7f0539a8786b97874fe946b2d26393'
$filenames = @('installed_suite.py', 'installed_models.py', 'installed_workflows.py', 'fixtures.json')
$utf8 = New-Object Text.UTF8Encoding($false)
$session = $null; $failure = $null; $result = 1; $started = [DateTime]::UtcNow.ToString('o')
$consoleEncoding = [Console]::OutputEncoding

function Write-AuditJson([string] $Path, $Value) {
    [IO.File]::WriteAllText($Path, (($Value | ConvertTo-Json -Depth 12) + "`n"), $utf8)
}
function Get-VerifiedHarnessFile([string] $Name, [string] $ExpectedHash) {
    if ($ExpectedHash -cnotmatch '^[a-f0-9]{64}$') { throw "Checksum del collaudo non configurato: $Name" }
    $destination = Join-Path $harness $Name
    $url = 'https://raw.githubusercontent.com/GregorioDalia/nipat-desktop/' + $SourceCommit + '/scripts/acceptance/' + $Name
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $destination -TimeoutSec 60
    if ((Get-Item -LiteralPath $destination).Length -gt (16 * 1024 * 1024) -or
        (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedHash) {
        throw "Il file del collaudo non corrisponde al contenuto verificato: $Name"
    }
    return $destination
}

try {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA non disponibile.' }
    $root = Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop\collaudi'
    $session = Join-Path $root ('0850-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    if (-not $AppDirectory) { $AppDirectory = (Get-ItemProperty -LiteralPath 'HKCU:\Software\NIPAT\desktop' -Name app_dir).app_dir }
    $AppDirectory = [IO.Path]::GetFullPath($AppDirectory).TrimEnd('\')
    . (Join-Path $AppDirectory 'installer\windows\bootstrap-common.ps1')
    Assert-NipatWindowsUser
    Assert-NipatInstallationLocation $AppDirectory
    Assert-NipatInstallPathWithoutLinks $root
    [IO.Directory]::CreateDirectory($session) | Out-Null
    Write-Host ("Cartella del collaudo: $session") -ForegroundColor Cyan
    $manifest = Read-NipatInstallerManifest (Join-Path $AppDirectory '.distribution\installer-manifest.json')
    $state = Get-Content -LiteralPath (Join-Path $AppDirectory '.runtime\installer\state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $backend = Get-Content -LiteralPath (Join-Path $AppDirectory '.runtime\backend.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.version -cne '0.8.50' -or $manifest.source_commit -cne $installationCommit -or
        $state.schema_version -ne 1 -or $state.phase -cne 'ready' -or $state.source_commit -cne $installationCommit -or
        $backend.schema_version -ne 1 -or $backend.backend -cne 'wsl') {
        throw 'Il collaudo richiede NIPAT Desktop 0.8.50 ufficiale con preparazione completata.'
    }
    Assert-NipatRuntimeBinding $manifest $state $backend
    $python = Join-Path $AppDirectory '.runtime\python\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python incluso in NIPAT non disponibile.' }
    $harness = Join-Path $session 'harness'
    [IO.Directory]::CreateDirectory($harness) | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $bundlePath = Get-VerifiedHarnessFile 'bundle-manifest.json' $ExpectedManifestSha256
    $bundle = Get-Content -LiteralPath $bundlePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $entries = @($bundle.files.PSObject.Properties)
    if ($bundle.schema_version -ne 1 -or $bundle.files -isnot [pscustomobject] -or $entries.Count -ne $filenames.Count -or
        @($entries | Where-Object { $filenames -cnotcontains $_.Name -or $_.Value -isnot [string] -or $_.Value -cnotmatch '^[a-f0-9]{64}$' }).Count) {
        throw 'Manifest del collaudo non valido: sono ammessi soltanto i quattro file previsti.'
    }
    foreach ($name in $filenames) { Get-VerifiedHarnessFile $name $bundle.files.$name | Out-Null }
    Write-AuditJson (Join-Path $session 'wrapper.json') @{
        schema_version = 1; started_utc = $started; status = 'running'; app_dir = $AppDirectory
        installation_source_commit = $installationCommit; harness_source_commit = $SourceCommit
        harness_manifest_sha256 = $ExpectedManifestSha256; files = $bundle.files
    }
    Write-Host 'Avvio dei test sintetici. I risultati e i log vengono salvati nella cartella del collaudo.'
    $driver = Join-Path $harness 'installed_suite.py'
    $stderrPath = Join-Path $session 'wrapper-driver.stderr.log'
    [Console]::OutputEncoding = $utf8
    $previousErrorAction = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 wraps native stderr in error records. The native
        # exit code determines failure; stderr must not interrupt the driver.
        $ErrorActionPreference = 'Continue'
        $LASTEXITCODE = $null
        & $python -X utf8 -u -B $driver --app-dir $AppDirectory --session $session --harness-source-commit $SourceCommit 2> $stderrPath | Out-Host
        $nativeCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousErrorAction }
    if ($null -eq $nativeCode) { throw 'Il processo di collaudo non e stato avviato.' }
    $result = [int]$nativeCode
    if ($result -ne 0) { throw "Collaudo terminato con codice $result. Consultare il report e wrapper-driver.stderr.log." }
    foreach ($name in @('report.json', 'report.html', 'report.zip')) {
        if (-not (Test-Path -LiteralPath (Join-Path $session $name) -PathType Leaf)) { throw "Risultato del collaudo mancante: $name" }
    }
} catch {
    $failure = $_.Exception.Message
    if ($result -eq 0) { $result = 1 }
    Write-Host ('ERRORE: ' + $failure) -ForegroundColor Red
} finally {
    [Console]::OutputEncoding = $consoleEncoding
    if ($session -and (Test-Path -LiteralPath $session -PathType Container)) {
        $summary = @{
            schema_version = 1; started_utc = $started; finished_utc = [DateTime]::UtcNow.ToString('o')
            status = $(if ($result -eq 0) { 'completed' } else { 'failed' }); exit_code = $result; error = $failure
            app_dir = $AppDirectory; installation_source_commit = $installationCommit
            harness_source_commit = $SourceCommit; harness_manifest_sha256 = $ExpectedManifestSha256
        }
        Write-AuditJson (Join-Path $session 'wrapper-result.json') $summary
        $html = Join-Path $session 'report.html'; $json = Join-Path $session 'report.json'; $zip = Join-Path $session 'report.zip'
        if (-not (Test-Path -LiteralPath $json)) { Write-AuditJson $json $summary }
        if (-not (Test-Path -LiteralPath $html)) {
            $message = [Security.SecurityElement]::Escape([string]$failure)
            [IO.File]::WriteAllText($html, ('<!doctype html><html lang="it"><meta charset="utf-8"><title>Collaudo NIPAT non completato</title><h1>Collaudo non completato</h1><p>' + $message + '</p><p>Consultare wrapper-result.json e i log nella stessa cartella.</p></html>'), $utf8)
        }
        if (-not (Test-Path -LiteralPath $zip)) {
            Add-Type -AssemblyName System.IO.Compression
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $archive = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Create)
            try {
                foreach ($name in @('report.json', 'report.html', 'wrapper.json', 'wrapper-result.json', 'wrapper-driver.stderr.log')) {
                    $path = Join-Path $session $name
                    if (Test-Path -LiteralPath $path -PathType Leaf) { [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $path, $name) }
                }
            } finally { $archive.Dispose() }
        }
        Write-Host ("Report: $html") -ForegroundColor Cyan
        Write-Host ("ZIP da allegare: $zip") -ForegroundColor Cyan
        try { Invoke-Item -LiteralPath $html } catch { Write-Host 'Aprire manualmente il report dal percorso indicato.' }
    }
}
exit $result
