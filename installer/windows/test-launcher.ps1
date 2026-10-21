param([string] $LauncherPath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "Launcher check failed: $Message" }
    $script:checks++
}

function ConvertTo-WindowsArgument([AllowEmptyString()][string] $Value) {
    $result = New-Object Text.StringBuilder
    [void]$result.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes++
        } elseif ($character -eq '"') {
            [void]$result.Append([char]'\', $slashes * 2 + 1)
            [void]$result.Append($character)
            $slashes = 0
        } else {
            [void]$result.Append([char]'\', $slashes)
            [void]$result.Append($character)
            $slashes = 0
        }
    }
    [void]$result.Append([char]'\', $slashes * 2)
    [void]$result.Append('"')
    return $result.ToString()
}

function Invoke-TestLauncher([string] $Executable, [string[]] $Arguments = @(), [int] $ExitCode = 0) {
    if (Test-Path -LiteralPath $script:CapturePath) { Remove-Item -LiteralPath $script:CapturePath }
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $Executable
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' ')
    $start.WorkingDirectory = $script:CallerDirectory
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables['NIPAT_LAUNCH_TEST_CAPTURE'] = $script:CapturePath
    $start.EnvironmentVariables['NIPAT_LAUNCH_TEST_EXIT'] = [string]$ExitCode
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(20000)) {
            $process.Kill()
            throw 'Launcher did not return within 20 seconds; possible unwanted pause.'
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = $stdout.Result + $stderr.Result
        }
    } finally {
        $process.Dispose()
    }
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-launcher-test-' + [Guid]::NewGuid().ToString('N'))
try {
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    if ([string]::IsNullOrWhiteSpace($LauncherPath)) {
        $LauncherPath = Join-Path $temporary 'compiled\NIPAT.exe'
        & (Join-Path $PSScriptRoot 'build-launcher.ps1') -OutputPath $LauncherPath
    }
    $source = (Get-Item -LiteralPath $LauncherPath -ErrorAction Stop).FullName
    $app = Join-Path $temporary ('NIPAT app & [literal] ' + [char]0x00E8)
    $script:CallerDirectory = Join-Path $temporary 'caller working directory'
    $script:CapturePath = Join-Path $temporary 'received.json'
    [IO.Directory]::CreateDirectory($script:CallerDirectory) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $app 'installer\windows')) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $app 'scripts\windows')) | Out-Null
    $executable = Join-Path $app 'NIPAT.exe'
    Copy-Item -LiteralPath $source -Destination $executable
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launch.ps1') -Destination (Join-Path $app 'installer\windows\launch.ps1')
    $runner = Join-Path $app 'scripts\windows\run.ps1'
    @'
$record = [pscustomobject]@{
    arguments = @($args)
    working_directory = (Get-Location).Path
    script_path = $PSCommandPath
    bridge_arguments_removed = [string]::IsNullOrEmpty($env:NIPAT_LAUNCH_ARGUMENTS)
    bridge_count_removed = [string]::IsNullOrEmpty($env:NIPAT_LAUNCH_ARGUMENT_COUNT)
}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $env:NIPAT_LAUNCH_TEST_CAPTURE -Encoding UTF8
exit ([int]$env:NIPAT_LAUNCH_TEST_EXIT)
'@ | Set-Content -LiteralPath $runner -Encoding UTF8

    $result = Invoke-TestLauncher -Executable $executable
    Assert-Test ($result.ExitCode -eq 0) ('default launch exit code: ' + $result.Output)
    $record = Get-Content -LiteralPath $script:CapturePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($record.arguments.Count -eq 1 -and $record.arguments[0] -ceq 'wizard') 'double-click defaults to wizard'
    Assert-Test ($record.working_directory -ceq $script:CallerDirectory) 'caller working directory preserved'
    Assert-Test ($record.script_path -ceq $runner) 'runner is relative to the executable, not the current directory'
    Assert-Test ($record.bridge_arguments_removed -and $record.bridge_count_removed) 'temporary launch data removed before running NIPAT'

    $argumentList = @(
        '--runs-dir', 'C:\folder with spaces\', '--dry-run', 'wizard', '',
        'quoted "value"', 'ends-with-backslash\', 'two\\slashes',
        "apostrophe's & [brackets]", '$HOME; $(throw ''must not execute'')',
        ('unicode ' + [char]0x00E8 + [char]0x03B1), "line one`nline two"
    )
    $result = Invoke-TestLauncher -Executable $executable -Arguments $argumentList -ExitCode 23
    Assert-Test ($result.ExitCode -eq 23) ('runner exit code preserved: ' + $result.Output)
    $record = Get-Content -LiteralPath $script:CapturePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($record.arguments.Count -eq $argumentList.Count) 'all arguments including empty values preserved'
    for ($index = 0; $index -lt $argumentList.Count; $index++) {
        Assert-Test ($record.arguments[$index] -ceq $argumentList[$index]) "argument $index is literal data"
    }
    Assert-Test ($record.working_directory -ceq $script:CallerDirectory) 'explicit CLI arguments preserve caller directory'

    $result = Invoke-TestLauncher -Executable $executable -Arguments @('')
    Assert-Test ($result.ExitCode -eq 0) ('empty sole argument exit code: ' + $result.Output)
    $record = Get-Content -LiteralPath $script:CapturePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($record.arguments.Count -eq 1 -and $record.arguments[0] -ceq '') 'one empty argument does not become wizard'

    Remove-Item -LiteralPath $runner
    $result = Invoke-TestLauncher -Executable $executable
    Assert-Test ($result.ExitCode -eq 1) 'missing package files return a failure without hanging CI'
    Assert-Test ($result.Output -match 'Pacchetto NIPAT incompleto') 'incomplete package has an actionable error'
    Assert-Test (-not (Test-Path -LiteralPath $script:CapturePath)) 'missing runner is never invoked'
    Write-Host "PASS: $checks launcher assertions."
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
