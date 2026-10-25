# Shared by fast CI and full installer builds. Every native exit code is checked.
param([string] $LauncherPath = 'build/launcher/NIPAT.exe')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-CheckedProcess {
    param([string] $Executable, [string[]] $Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed (exit $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

Write-Host '::group::Python unit and CI policy tests'
Invoke-CheckedProcess 'python' @('-m', 'unittest', 'discover', '-s', 'tests', '-v')
Invoke-CheckedProcess 'python' @('-m', 'unittest', 'discover', '-s', '.github/scripts', '-p', 'test_*.py', '-v')
Write-Host '::endgroup::'

Write-Host '::group::Windows PowerShell 5.1 syntax'
$files = Get-ChildItem scripts/windows,installer/windows,.github/scripts -Recurse -Filter '*.ps1' -File
foreach ($file in $files) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw ($errors | Out-String) }
}
Write-Host '::endgroup::'

$tests = @(
    'test-bootstrap.ps1', 'test-scientific-image.ps1', 'test-migration.ps1',
    'test-install-layout.ps1', 'test-uninstall.ps1', 'test-repair-installation.ps1',
    'test-update-handoff.ps1', 'test-activity-lock.ps1'
)
foreach ($test in $tests) {
    Write-Host "::group::$test"
    Invoke-CheckedProcess 'powershell' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "installer/windows/$test")
    Write-Host '::endgroup::'
}

Write-Host '::group::Real installer definition compilation'
$compiler = & "$PSScriptRoot/install_inno.ps1" -Destination (Join-Path $env:RUNNER_TEMP 'InnoSetup')
& ./installer/windows/test-installer-layout.ps1 -CompilerPath $compiler
Write-Host '::endgroup::'

Write-Host '::group::Compiled launcher and launcher behavior'
Invoke-CheckedProcess 'powershell' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
    'installer/windows/build-launcher.ps1', '-OutputPath', $LauncherPath)
Invoke-CheckedProcess 'powershell' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
    'installer/windows/test-launcher.ps1', '-LauncherPath', $LauncherPath)
Write-Host '::endgroup::'
