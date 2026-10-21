param([switch] $FromLauncher)
. (Join-Path $PSScriptRoot "common.ps1")
$project = Get-NipatProject
# Only a staged installer contains this trusted manifest. Source/portable setup is unchanged.
if (Test-Path -LiteralPath (Join-Path $project ".distribution\installer-manifest.json") -PathType Leaf) {
    & (Join-Path $project "installer\windows\bootstrap.ps1")
    exit $LASTEXITCODE
}
. (Join-Path $PSScriptRoot 'portable-bootstrap.ps1')
$transcriptStarted = $false
$preparationLock = $null
$result = 1
try {
    Set-NipatEnvironment $project -Preparing
    Initialize-NipatWritableDirectory (Join-Path $project ".runtime") "del runtime locale"
    $preparationLock = Enter-NipatPortableSetupLock $project
    $package = Get-NipatPortablePackage $project
    if ($FromLauncher -and $null -ne $package -and (Test-NipatPortableSetupReady $project $package)) {
        $result = 0
    } else {
        # Invalidate a previous success before changing any preparation component.
        $readyPath = Join-Path $project '.runtime\portable-setup.json'
        if (Test-Path -LiteralPath $readyPath -PathType Leaf) { Remove-Item -LiteralPath $readyPath -Force }
        Start-Transcript -Path (Join-Path $project ".runtime\setup.log") -Append | Out-Null
        $transcriptStarted = $true
        Write-Host "NIPAT CLI - preparazione per la validazione"
        # Existing input collections may be read-only; no fixed subfolders are required.
        if (-not (Test-Path -LiteralPath $env:NIPAT_DATA_DIR -PathType Container)) {
            [IO.Directory]::CreateDirectory($env:NIPAT_DATA_DIR) | Out-Null
        }
        Initialize-NipatWritableDirectory $env:NIPAT_RUNS_DIR "dei risultati"
        Write-Host "Directory dati: $env:NIPAT_DATA_DIR"
        Write-Host "Directory risultati: $env:NIPAT_RUNS_DIR"
        Write-Host 'Controllo di Docker Desktop...'
        Assert-NipatDocker | Out-Null
        Write-Host 'Preparazione dei componenti inclusi...'
        $python = Install-NipatPython $project
        Install-NipatRuntime $project
        $checksLog = Join-Path $project '.runtime\setup-checks.log'
        [IO.File]::WriteAllText($checksLog, '', (New-Object Text.UTF8Encoding($false)))
        Write-Host 'Verifica degli strumenti di analisi...'
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $global:LASTEXITCODE = -1
            & $python -m nipat doctor --runtime *>&1 | Out-File -LiteralPath $checksLog -Append -Encoding UTF8
            $checkCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $previousPreference }
        if ($checkCode -ne 0) { throw "Controllo ambiente fallito. Dettagli: $checksLog" }
        Write-Host 'Esecuzione degli autotest scientifici...'
        try {
            $ErrorActionPreference = 'Continue'
            $global:LASTEXITCODE = -1
            & $python -m nipat self-test *>&1 | Out-File -LiteralPath $checksLog -Append -Encoding UTF8
            $checkCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $previousPreference }
        if ($checkCode -ne 0) { throw "Test di riferimento falliti. Dettagli: $checksLog" }
        Complete-NipatPortableSetup $project $package
        $launcher = if (Test-Path -LiteralPath (Join-Path $project "NIPAT.exe") -PathType Leaf) {
            "NIPAT.exe"
        } else {
            "2_AVVIA.cmd"
        }
        if ($FromLauncher) { Write-Host 'Preparazione completata. Apertura del menu...' }
        else { Write-Host "Preparazione completata. Aprire $launcher per scegliere un'analisi." }
        $result = 0
    }
} catch {
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    if ($null -ne $preparationLock) { $preparationLock.Dispose() }
}
exit $result
