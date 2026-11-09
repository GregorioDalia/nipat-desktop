# Build-machine only. The destination PC never compiles application code.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NipatCSharpCompiler {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        throw 'La build richiede Visual Studio Build Tools con il compilatore C# Roslyn.'
    }
    $compilers = @(& $vswhere -latest -products '*' -requires Microsoft.Component.MSBuild `
        -find 'MSBuild\**\Bin\Roslyn\csc.exe')
    if ($LASTEXITCODE -ne 0 -or $compilers.Count -eq 0) {
        throw 'Compilatore C# Roslyn non trovato; nessuna compilazione non deterministica viene usata come ripiego.'
    }
    $compiler = [string]$compilers[0]
    if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'Percorso del compilatore C# non valido.' }
    return $compiler
}
