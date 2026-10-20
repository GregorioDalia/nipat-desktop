. (Join-Path $PSScriptRoot "common.ps1")
$project = Get-NipatProject
$transcriptStarted = $false
$result = 1
try {
    Set-NipatEnvironment $project
    New-Item -ItemType Directory -Path (Join-Path $project ".runtime") -Force | Out-Null
    Start-Transcript -Path (Join-Path $project ".runtime\setup.log") -Append | Out-Null
    $transcriptStarted = $true
    Write-Host "NIPAT CLI - preparazione per la validazione"
    foreach ($relative in @("samples", "reference", "panels", "test-cases")) {
        New-Item -ItemType Directory -Path (Join-Path $env:NIPAT_DATA_DIR $relative) -Force | Out-Null
    }
    New-Item -ItemType Directory -Path $env:NIPAT_RUNS_DIR -Force | Out-Null
    Assert-NipatDocker
    $python = Install-NipatPython $project
    Install-NipatRuntime $project
    & $python -m nipat doctor --runtime
    if ($LASTEXITCODE -ne 0) { throw "Controllo ambiente fallito." }
    & $python -m nipat self-test
    if ($LASTEXITCODE -ne 0) { throw "Test di riferimento falliti. Consultare i risultati in runs e .runtime\setup.log." }
    Write-Host "Preparazione completata. Aprire 2_AVVIA.cmd per scegliere un'analisi."
    $result = 0
} catch {
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
exit $result
