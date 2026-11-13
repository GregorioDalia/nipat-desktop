param(
    [string] $AppDirectory = '',
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{40}$')][string] $HotfixSourceCommit
)

# Local, documented repair of the 0.8.50 CPIN verifier import. No release metadata changes.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$baseCommit = 'b54ef493ba7f0539a8786b97874fe946b2d26393'
$oldHashes = @('e66854186e85f75d9ee7843e90a7b513556b1249f1dada78f687601db598529a',
    'd22ced95004966eaaa627c4a80e5795514b42bf00d76471b1d5404143c6d10d1')
$newHashes = @('22d68e6a0851d1ee1fb00799dc9447bdbffbc17645061ff03deaf7875dab6cbf',
    '5254037927ea4f494c93297555927c40aca902133a70f4b7d77e484892d3682a')
$lease = $null; $temporary = $null; $receipt = $null; $receiptPath = $null
$result = 1

function Invoke-HotfixCheck([string] $Executable, [string[]] $Arguments, [string] $Name) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $Executable
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-NipatNativeArgument $_ }) -join ' ')
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    $stdoutFile = $null; $stderrFile = $null
    Write-Host ("NIPAT: $Name in corso. Log: $logDirectory")
    try {
        $stdoutFile = [IO.File]::Open((Join-Path $logDirectory "$Name.stdout.log"), 'Create', 'Write', 'Read')
        $stderrFile = [IO.File]::Open((Join-Path $logDirectory "$Name.stderr.log"), 'Create', 'Write', 'Read')
        if (-not $process.Start()) { throw "Impossibile avviare $Name." }
        $stdout = $process.StandardOutput.BaseStream.CopyToAsync($stdoutFile)
        $stderr = $process.StandardError.BaseStream.CopyToAsync($stderrFile)
        $process.WaitForExit()
        [void]$stdout.GetAwaiter().GetResult(); [void]$stderr.GetAwaiter().GetResult()
        return $process.ExitCode
    } finally {
        if ($null -ne $stdoutFile) { $stdoutFile.Dispose() }
        if ($null -ne $stderrFile) { $stderrFile.Dispose() }
        $process.Dispose()
    }
}

try {
    if (-not $AppDirectory) {
        $AppDirectory = (Get-ItemProperty -LiteralPath 'HKCU:\Software\NIPAT\desktop' -Name app_dir).app_dir
    }
    $AppDirectory = [IO.Path]::GetFullPath($AppDirectory).TrimEnd('\')
    . (Join-Path $AppDirectory 'installer\windows\bootstrap-common.ps1')
    . (Join-Path $AppDirectory 'installer\windows\activity-lock.ps1')
    Assert-NipatWindowsUser
    Assert-NipatInstallationLocation $AppDirectory
    $lease = Enter-NipatInstallationActivity
    $manifest = Read-NipatInstallerManifest (Join-Path $AppDirectory '.distribution\installer-manifest.json')
    $statePath = Join-Path $AppDirectory '.runtime\installer\state.json'
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-NipatInstallationChannel $state 'Lo stato di preparazione'
    if ($manifest.source_commit -cne $baseCommit -or $manifest.version -cne '0.8.50' -or
        $state.source_commit -cne $baseCommit -or $state.version -cne '0.8.50' -or $state.schema_version -ne 1 -or
        [IO.Path]::GetFullPath($state.app_dir).TrimEnd('\') -ine $AppDirectory) {
        throw 'Questo hotfix richiede il pacchetto ufficiale NIPAT Desktop 0.8.50 e il relativo stato di preparazione.'
    }
    $target = Join-Path $AppDirectory 'scripts\verify_cpin_update.py'
    $python = Join-Path $AppDirectory '.runtime\python\python.exe'
    foreach ($path in @($target, $python, (Split-Path -Parent $statePath))) { Assert-NipatActivityPathWithoutLinks $path }
    $before = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if (($oldHashes + $newHashes) -notcontains $before) { throw 'Il verificatore CPIN e diverso dai file attesi; nessuna modifica applicata.' }
    $logDirectory = Join-Path (Split-Path -Parent $statePath) ('hotfix-cpin-import-0850\' + [Guid]::NewGuid().ToString('N'))
    Assert-NipatActivityPathWithoutLinks $logDirectory
    [IO.Directory]::CreateDirectory($logDirectory) | Out-Null
    $receiptPath = Join-Path $logDirectory 'receipt.json'
    $receipt = [ordered]@{
        schema_version = 1; hotfix_id = 'cpin-import-0850'; app_dir = $AppDirectory
        installation_source_commit = $baseCommit; hotfix_source_commit = $HotfixSourceCommit
        file = 'scripts/verify_cpin_update.py'; sha256_before = $before; sha256_after = $null
        backup = $null; created_utc = [DateTime]::UtcNow.ToString('o'); status = 'checking'
        help_before_exit = $null; help_after_exit = $null; bootstrap_exit = $null; final_phase = $null; error = $null
    }
    Write-NipatJsonAtomic $receiptPath $receipt
    $receipt.help_before_exit = Invoke-HotfixCheck $python @('-X', 'utf8', '-u', $target, '--help') 'help-before'
    if ($oldHashes -contains $before) {
        $content = [IO.File]::ReadAllText($target, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
        $insertion = "# Embedded Python excludes the script directory from its default search path.`nsys.path.insert(0, str(Path(__file__).resolve().parent))`n`n"
        $content = $content.Replace("import sys`n`n", "import sys`n`n" + $insertion)
        $temporary = Join-Path (Split-Path -Parent $target) ('.cpin-hotfix-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        [IO.File]::WriteAllText($temporary, $content, (New-Object Text.UTF8Encoding($false)))
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -cne $newHashes[0] -or
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $before) {
            throw 'La verifica della correzione non e riuscita; il file originale viene conservato.'
        }
        $receipt.backup = Join-Path $logDirectory 'verify_cpin_update.py.original'
        [IO.File]::Replace($temporary, $target, $receipt.backup)
        $temporary = $null
    }
    $receipt.sha256_after = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($newHashes -notcontains $receipt.sha256_after) { throw 'Checksum del verificatore corretto inatteso.' }
    $receipt.status = 'patched'
    Write-NipatJsonAtomic $receiptPath $receipt
    $receipt.help_after_exit = Invoke-HotfixCheck $python @('-X', 'utf8', '-u', $target, '--help') 'help-after'
    if ($receipt.help_after_exit -ne 0) { throw 'Il verificatore corretto non si avvia; consultare help-after.stderr.log.' }
    Write-NipatJsonAtomic $receiptPath $receipt
    Exit-NipatInstallationActivity $lease
    $lease = $null
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $bootstrap = Join-Path $AppDirectory 'installer\windows\bootstrap.ps1'
    $receipt.bootstrap_exit = Invoke-HotfixCheck $powershell @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $bootstrap, '-Resume') 'bootstrap'
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $receipt.final_phase = $state.phase
    if ($receipt.bootstrap_exit -ne 0 -or $state.phase -cne 'ready' -or
        $state.source_commit -cne $baseCommit -or $state.installation_channel -cne 'desktop') {
        throw 'Preparazione non completata. Conservare la ricevuta e i log bootstrap per la diagnosi.'
    }
    $receipt.status = 'ready'
    $result = 0
    Write-Host 'NIPAT 0.8.50 con hotfix locale: preparazione e autotest completati.'
} catch {
    if ($null -ne $receipt) { $receipt.status = 'failed'; $receipt.error = $_.Exception.Message }
    Write-Host ('ERRORE: ' + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($null -ne $lease) { Exit-NipatInstallationActivity $lease }
    if ($temporary -and [IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    if ($null -ne $receipt) { Write-NipatJsonAtomic $receiptPath $receipt; Write-Host ("Ricevuta e log: $logDirectory") }
}
exit $result
