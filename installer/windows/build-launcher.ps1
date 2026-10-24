param([string] $OutputPath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $project 'NIPAT.exe'
}
$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw 'La compilazione richiede il compilatore .NET Framework x64 di Windows.'
}
$metadata = Get-Content -LiteralPath (Join-Path $project 'pyproject.toml') -Raw -Encoding UTF8
$versionMatch = [regex]::Match($metadata, '(?m)^version\s*=\s*"(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)"\s*$')
if (-not $versionMatch.Success) { throw 'Versione NIPAT non riconosciuta in pyproject.toml.' }
$version = $versionMatch.Groups[1].Value
$numeric = [regex]::Match($version, '^\d+\.\d+\.\d+').Value + '.0'
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-launcher-build-' + [Guid]::NewGuid().ToString('N'))
try {
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    [IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
    $assemblyInfo = Join-Path $temporary 'AssemblyInfo.cs'
    @"
using System.Reflection;
[assembly: AssemblyTitle("NIPAT")]
[assembly: AssemblyProduct("NIPAT")]
[assembly: AssemblyDescription("NIPAT scientific workflows launcher")]
[assembly: AssemblyVersion("$numeric")]
[assembly: AssemblyFileVersion("$numeric")]
[assembly: AssemblyInformationalVersion("$version")]
"@ | Set-Content -LiteralPath $assemblyInfo -Encoding UTF8
    $source = Join-Path $PSScriptRoot 'NipatLauncher.cs'
    $manifest = Join-Path $PSScriptRoot 'NipatLauncher.manifest'
    $icon = Join-Path $project 'assets\branding\nipat-icon.ico'
    if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw 'Icona NIPAT mancante.' }
    & $compiler /nologo /target:exe /platform:x64 /optimize+ "/win32manifest:$manifest" "/win32icon:$icon" "/out:$target" $source $assemblyInfo
    if ($LASTEXITCODE -ne 0) { throw 'Compilazione di NIPAT.exe fallita.' }
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'NIPAT.exe non e stato prodotto.' }
    Write-Host "Launcher NIPAT $version compilato: $target"
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
