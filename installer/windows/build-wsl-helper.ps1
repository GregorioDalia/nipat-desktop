param([Parameter(Mandatory = $true)][string] $OutputPath)

. (Join-Path $PSScriptRoot 'build-compiler.ps1')
$compiler = Get-NipatCSharpCompiler
$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
[IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
$source = Join-Path $PSScriptRoot 'EnableWsl.cs'
$manifest = Join-Path $PSScriptRoot 'EnableWsl.manifest'
& $compiler /nologo /deterministic+ /debug- /target:exe /platform:x64 "/win32manifest:$manifest" "/out:$target" $source
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw 'Compilazione del componente prerequisiti WSL fallita.'
}
Write-Host "Componente prerequisiti WSL compilato: $target"
