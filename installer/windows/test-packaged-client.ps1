param(
    [Parameter(Mandatory = $true)][string]$StageDirectory,
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$WorkDirectory,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$stage = (Resolve-Path -LiteralPath $StageDirectory).Path
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$work = [IO.Path]::GetFullPath($WorkDirectory)
$output = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $work) {
    throw "La cartella di verifica deve essere nuova: $work"
}
$sourceApp = Join-Path $stage 'app'
$pythonArchive = Join-Path $sourceApp '.distribution\python-3.12.10-embed-amd64.zip'
if (-not (Test-Path -LiteralPath $pythonArchive -PathType Leaf)) {
    throw 'Python incorporato assente: la verifica non scarica componenti sostitutivi.'
}
if (Test-Path -LiteralPath $output) {
    throw "Il resoconto esiste gia: $output"
}

# Use exactly the app inventoried before/after Inno compilation. Never modify
# that stage: only this relocated copy receives an extracted embedded Python.
New-Item -ItemType Directory -Path $work | Out-Null
$app = Join-Path $work 'app'
Copy-Item -LiteralPath $sourceApp -Destination $app -Recurse
. (Join-Path $app 'scripts\windows\common.ps1')
$python = Install-NipatPython $app
& $python -B -X utf8 (Join-Path $app 'scripts\verify_windows_payload.py') `
    --app-dir $app --work-dir $work --installer $installer --output $output
if ($LASTEXITCODE -ne 0) {
    throw "Verifica del client incorporato fallita (codice $LASTEXITCODE). Diagnosi: $work"
}
if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
    throw 'La verifica non ha prodotto il resoconto atteso.'
}
Write-Host 'Client Windows incorporato verificato: catalogo, menu e pianificazione dei workflow.'
Write-Host 'Questa prova non esegue Inno Setup, WSL, Docker o i calcoli scientifici.'
