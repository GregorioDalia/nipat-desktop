# No named PowerShell parameters: preserve all CLI flags, including --data-dir/--runs-dir.
# Keep the caller's working directory so Python resolves relative CLI paths there.
$nipatCliArguments = @($args)
. (Join-Path $PSScriptRoot "common.ps1")
try {
    $project = Get-NipatProject
    Set-NipatEnvironment $project
    $python = Get-NipatPython $project
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Preparazione non completata: aprire prima 1_SETUP.cmd."
    }
    if ($nipatCliArguments.Count -eq 0) { $nipatCliArguments = @("--help") }
    & $python -m nipat @nipatCliArguments
    exit $LASTEXITCODE
} catch {
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
