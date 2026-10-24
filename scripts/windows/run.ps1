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
            throw 'Installazione da completare: aprire NIPAT 0.5 Preview - completa preparazione dal menu Start.'
        }
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifest = Read-NipatInstallerManifest (Join-Path $project '.distribution\installer-manifest.json')
        if ($state.schema_version -ne 1 -or $state.phase -ne 'ready' -or
            $state.source_commit -ne $manifest.source_commit -or $state.runtime_image -ne $manifest.runtime_image) {
            throw 'Installazione non verificata per questa versione: aprire NIPAT 0.5 Preview - completa preparazione dal menu Start.'
        }
        $configuration = Get-Content -LiteralPath (Join-Path $project '.runtime\backend.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-NipatRuntimeBinding $manifest $state $configuration
    }
    Set-NipatEnvironment $project
    $python = Get-NipatPython $project
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python NIPAT non disponibile. Per l'applicazione installata riaprire NIPAT 0.5 Preview - completa preparazione dal menu Start; per il sorgente configurare WSL e avviare 1_SETUP.cmd."
    }
    if ($nipatCliArguments.Count -eq 0) { $nipatCliArguments = @("--help") }
    & $python -m nipat @nipatCliArguments
    exit $LASTEXITCODE
} catch {
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
