# No named PowerShell parameters: preserve all CLI flags, including --data-dir/--runs-dir.
# Keep the caller's working directory so Python resolves relative CLI paths there.
$nipatCliArguments = @($args)
. (Join-Path $PSScriptRoot "common.ps1")
try {
    $project = Get-NipatProject
    if (Test-Path -LiteralPath (Join-Path $project '.distribution\installer-manifest.json') -PathType Leaf) {
        . (Join-Path $project 'installer\windows\bootstrap-common.ps1')
        $statePath = Join-Path $project '.runtime\installer\state.json'
        if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
            throw 'Installazione da completare: aprire NIPAT - completa preparazione dal menu Start.'
        }
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifest = Get-Content -LiteralPath (Join-Path $project '.distribution\installer-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.schema_version -ne 1 -or $state.phase -ne 'ready' -or
            $state.source_commit -ne $manifest.source_commit -or $state.runtime_image -ne $manifest.runtime_image) {
            throw 'Installazione non verificata per questa versione: aprire NIPAT - completa preparazione dal menu Start.'
        }
        $configuration = Get-Content -LiteralPath (Join-Path $project '.runtime\backend.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-NipatRuntimeBinding $manifest $state $configuration
    }
    . (Join-Path $PSScriptRoot 'portable-bootstrap.ps1')
    $preparationCode = Initialize-NipatPortableLaunch $project $nipatCliArguments
    if ($preparationCode -ne 0) { exit $preparationCode }
    # The child setup can select a newly imported immutable Docker image ID.
    Set-NipatEnvironment $project
    $python = Get-NipatPython $project
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        if (Test-Path -LiteralPath (Join-Path $project '.distribution\docker-desktop.json') -PathType Leaf) {
            throw "Preparazione non completata: aprire NIPAT.exe senza argomenti per completarla automaticamente."
        }
        throw "Preparazione non completata: aprire prima 1_SETUP.cmd."
    }
    if ($nipatCliArguments.Count -eq 0) { $nipatCliArguments = @("--help") }
    & $python -m nipat @nipatCliArguments
    exit $LASTEXITCODE
} catch {
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
