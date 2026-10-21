. (Join-Path $PSScriptRoot "common.ps1")
$project = Get-NipatProject
# Only a staged installer contains this trusted manifest. Source/portable setup is unchanged.
if (Test-Path -LiteralPath (Join-Path $project ".distribution\installer-manifest.json") -PathType Leaf) {
    & (Join-Path $project "installer\windows\bootstrap.ps1")
    exit $LASTEXITCODE
}
$transcriptStarted = $false
$result = 1
try {
    Set-NipatEnvironment $project
    Initialize-NipatWritableDirectory (Join-Path $project ".runtime") "del runtime locale"
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
    Assert-NipatDocker
    $python = Install-NipatPython $project
    Install-NipatRuntime $project
    & $python -m nipat doctor --runtime
    if ($LASTEXITCODE -ne 0) { throw "Controllo ambiente fallito." }
    & $python -m nipat self-test
    if ($LASTEXITCODE -ne 0) { throw "Test di riferimento falliti. Consultare i risultati in $env:NIPAT_RUNS_DIR e .runtime\setup.log." }
    $launcher = if (Test-Path -LiteralPath (Join-Path $project "NIPAT.exe") -PathType Leaf) {
        "NIPAT.exe"
    } else {
        "2_AVVIA.cmd"
    }
    Write-Host "Preparazione completata. Aprire $launcher per scegliere un'analisi."
    $result = 0
} catch {
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
exit $result
