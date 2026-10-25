. (Join-Path $PSScriptRoot "common.ps1")
$project = Get-NipatProject
# Installed packages own their verified WSL bootstrap, recovery and ready state.
if (Test-Path -LiteralPath (Join-Path $project ".distribution\installer-manifest.json") -PathType Leaf) {
    & (Join-Path $project "installer\windows\bootstrap.ps1")
    exit $LASTEXITCODE
}
$transcriptStarted = $false
$preparationLock = $null
$result = 1
try {
    # A source checkout prepares only the Python client. Its WSL distribution and
    # scientific image must already be explicitly configured by the developer.
    Assert-NipatWslDevelopmentConfiguration
    Set-NipatEnvironment $project
    Initialize-NipatWritableDirectory (Join-Path $project ".runtime") "del client locale"
    try {
        $preparationLock = [IO.File]::Open((Join-Path $project '.runtime\source-setup.lock'),
            [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        throw 'Un altra preparazione del client e gia in corso. Attendere che termini.'
    }
    Start-Transcript -LiteralPath (Join-Path $project ".runtime\setup.log") -Append | Out-Null
    $transcriptStarted = $true
    Write-Host "NIPAT - preparazione del client da sorgente per WSL"
    if (-not (Test-Path -LiteralPath $env:NIPAT_DATA_DIR -PathType Container)) {
        [IO.Directory]::CreateDirectory($env:NIPAT_DATA_DIR) | Out-Null
    }
    Initialize-NipatWritableDirectory $env:NIPAT_RUNS_DIR "dei risultati"
    $python = Install-NipatPython $project
    & $python -m nipat doctor --runtime
    if ($LASTEXITCODE -ne 0) { throw 'Controllo runtime WSL non superato. Consultare .runtime\setup.log.' }
    & $python -m nipat self-test
    if ($LASTEXITCODE -ne 0) { throw 'Autotest non superati. Consultare .runtime\setup.log e la cartella risultati.' }
    Write-Host "Client pronto. Aprire 2_AVVIA.cmd per scegliere un'analisi."
    $result = 0
} catch {
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    if ($null -ne $preparationLock) { $preparationLock.Dispose() }
}
exit $result
