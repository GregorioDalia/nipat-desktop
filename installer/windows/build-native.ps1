param([string] $OutputPath = (Join-Path $PSScriptRoot 'NipatActivityNative.dll'))

. (Join-Path $PSScriptRoot 'build-compiler.ps1')
$compiler = Get-NipatCSharpCompiler
$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
[IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
$source = Join-Path $PSScriptRoot 'ActivityNative.cs'
& $compiler /nologo /target:library /platform:x64 /optimize+ /deterministic+ /debug- "/out:$target" $source
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw 'Compilazione del componente di coordinamento NIPAT fallita.'
}
Write-Host "Componente di coordinamento compilato: $target"
