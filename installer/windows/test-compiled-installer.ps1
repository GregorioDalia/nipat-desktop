param(
    [Parameter(Mandatory = $true)][string] $CompilerPath,
    [Parameter(Mandatory = $true)][string] $StageDirectory,
    [Parameter(Mandatory = $true)][string] $AssetDirectory,
    [Parameter(Mandatory = $true)][string] $WorkDirectory,
    [string] $ReportDirectory = 'build/windows-installer-fixture'
)

# CI-only executable fixture. The production setup has no test/OS/runtime bypass.
# Server 2022 cannot run the supported Windows 10/11 installer. Only the fixture's
# OS/elevation gates and runtime bootstrap are replaced; installation, validation,
# repair, backups, locking, shortcuts and silent removal use the production code.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'The compiled installer fixture may run only on an isolated Windows Actions runner.'
}
$registry = 'HKCU:\Software\NIPAT\desktop'
if (Test-Path -LiteralPath $registry) { throw 'The fixture refuses an existing NIPAT Desktop registration.' }
$reportRoot = [IO.Path]::GetFullPath($ReportDirectory)
[IO.Directory]::CreateDirectory($reportRoot) | Out-Null
$work = [IO.Path]::GetFullPath($WorkDirectory)
if (Test-Path -LiteralPath $work) { throw 'The fixture work directory must not exist.' }
[IO.Directory]::CreateDirectory($work) | Out-Null
$app = Join-Path $StageDirectory 'app'
$installed = Join-Path $work 'installed application'
$definition = Join-Path $PSScriptRoot 'NIPAT.iss'
$original = [IO.File]::ReadAllText($definition)
$fixture = Join-Path $work 'fixture.iss'
$checks = [ordered]@{}
$report = [ordered]@{
    schema_version = 1; scenario = 'compiled-installer-fixture-on-server-2022'
    source_commit = (& git -C (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) rev-parse HEAD).Trim()
    production_setup_executed = $false; wsl_execution = $false
    smart_app_control = 'not-performed'; status = 'failed'
    source_definition_sha256 = (Get-FileHash -LiteralPath $definition -Algorithm SHA256).Hash.ToLowerInvariant()
    substitutions = @('Windows workstation/elevation setup gate', 'uninstaller elevation gate', 'synthetic runtime bootstrap and payload')
    checks = $checks
}
if ($LASTEXITCODE -ne 0 -or $report.source_commit -cnotmatch '^[a-f0-9]{40}$') { throw 'Fixture source commit unavailable.' }
$setupPattern = '(?s)function InitializeSetup\(\): Boolean;.*?(?=function NipatPathHasReparsePoint)'
if ([regex]::Matches($original, $setupPattern).Count -ne 1) { throw 'The setup gate fixture anchor changed.' }
$fixtureSource = [regex]::Replace($original, $setupPattern,
    "function InitializeSetup(): Boolean;`nbegin`n  Result := True;`nend;`n`n")
$uninstallPattern = '(?s)(function InitializeUninstall\(\): Boolean;.*?begin\s*)Result := not IsAdmin;'
if ([regex]::Matches($fixtureSource, $uninstallPattern).Count -ne 1) { throw 'The uninstall gate fixture anchor changed.' }
$fixtureSource = [regex]::Replace($fixtureSource, $uninstallPattern, '${1}Result := True;')
[IO.File]::WriteAllText($fixture, $fixtureSource, (New-Object Text.UTF8Encoding($false)))
$report.fixture_definition_sha256 = (Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash.ToLowerInvariant()
$bootstrap = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:NIPAT_SETUP_ACTIVITY_TOKEN -notmatch '^\d+:[a-f0-9]{32}$') { throw 'No live installer lease token.' }
$layout = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\.runtime\install-layout.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$lockPath = Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop\activity.lock'
$blocked = $false
try {
    $probe = [IO.File]::Open($lockPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    $probe.Dispose()
} catch [IO.IOException] { $blocked = $true }
if (-not $blocked) { throw 'Inno did not retain its exclusive installation lease during bootstrap.' }
[IO.File]::WriteAllText((Join-Path $layout.app_dir '.runtime\fixture-bootstrap.txt'), 'lease-held-runtime-not-executed')
if ($env:NIPAT_FIXTURE_BOOTSTRAP_REBOOT -eq '1') { exit 3010 }
exit 0
'@
[IO.File]::WriteAllText((Join-Path $app 'installer\windows\bootstrap.ps1'), $bootstrap,
    (New-Object Text.UTF8Encoding($false)))
$profilePath = Join-Path $StageDirectory 'install-profile.iss'
$profile = [IO.File]::ReadAllText($profilePath)
# A unique uninstall identity prevents the fixture from masquerading as a release.
$fixtureId = [Guid]::NewGuid().ToString().ToUpperInvariant()
$profile = [regex]::Replace($profile, '(?m)^#define NipatAppId .*$', '#define NipatAppId "{{' + $fixtureId + '}"')
$sentinels = @{}
$createdRegistry = $false

function Invoke-FixtureProcess([string] $Path, [string[]] $Arguments, [string] $Label, [int] $ExpectedCode = 0) {
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru
    try {
        $null = $process.Handle
        if (-not $process.WaitForExit(120000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "$Label timed out."
        }
        if ($null -eq $process.ExitCode -or $process.ExitCode -ne $ExpectedCode) {
            throw "$Label failed with exit code $($process.ExitCode)."
        }
    } finally {
        $process.Dispose()
    }
}

function Write-FixtureInventory {
    $entries = @(
        Get-ChildItem -LiteralPath $app -Recurse -File -Force |
            Where-Object { $_.FullName -ne (Join-Path $app '.distribution\application-files.json') } |
            Sort-Object FullName | ForEach-Object {
                [ordered]@{ path = $_.FullName.Substring($app.Length + 1).Replace('\', '/')
                    sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
            }
    )
    $inventory = [ordered]@{ schema_version = 1; installation_channel = 'desktop'; source_commit = ('0' * 40); files = $entries }
    [IO.File]::WriteAllText((Join-Path $app '.distribution\application-files.json'),
        ($inventory | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
}

function Assert-FixtureSentinels {
    foreach ($path in $sentinels.Keys) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $sentinels[$path]) {
            throw "Fixture data was removed or changed: $path"
        }
    }
}

try {
    New-Item -Path $registry -Force | Out-Null
    $createdRegistry = $true
    foreach ($role in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        $path = if ($role -eq 'app_dir') { $installed } else { Join-Path $work $role }
        New-ItemProperty -LiteralPath $registry -Name $role -Value $path -PropertyType String -Force | Out-Null
        if ($role -in @('data_dir', 'runs_dir')) {
            [IO.Directory]::CreateDirectory($path) | Out-Null
            $sentinel = Join-Path $path 'research-fixture.txt'
            [IO.File]::WriteAllText($sentinel, 'synthetic user data must survive')
            $sentinels[$sentinel] = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
        }
    }
    foreach ($version in @('0.0.1', '0.0.2')) {
        $output = Join-Path $work ('compiled-' + $version)
        [IO.Directory]::CreateDirectory($output) | Out-Null
        $versionProfile = [regex]::Replace($profile, '(?m)^#define NipatVersion .*$', '#define NipatVersion "' + $version + '"')
        [IO.File]::WriteAllText($profilePath, $versionProfile, (New-Object Text.UTF8Encoding($false)))
        [IO.File]::WriteAllText((Join-Path $app 'fixture-version.txt'), $version)
        Write-FixtureInventory
        & $CompilerPath '/Qp' "/DStageDir=$StageDirectory" "/DRuntimeAssetsDir=$AssetDirectory" "/DOutputDir=$output" $fixture
        if ($LASTEXITCODE -ne 0) { throw "Fixture compilation failed: $version" }
        $setup = Join-Path $output 'NIPAT-Setup.exe'
        $log = Join-Path $reportRoot ('install-' + $version + '.log')
        $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/SP-', '/NORESTART', "/DIR=`"$installed`"", "/LOG=`"$log`"")
        if ($version -eq '0.0.2') {
            $arguments += '/NIPATUPDATE=1' # Exercise the update invocation from 0.8.60.
            $env:NIPAT_FIXTURE_BOOTSTRAP_REBOOT = '1'
            try {
                Invoke-FixtureProcess $setup $arguments "Installation $version" 3010
                $checks.reboot_exit_code = $true
            } finally {
                Remove-Item Env:NIPAT_FIXTURE_BOOTSTRAP_REBOOT -ErrorAction SilentlyContinue
            }
        } else {
            Invoke-FixtureProcess $setup $arguments "Installation $version"
        }
        if ([IO.File]::ReadAllText((Join-Path $installed 'fixture-version.txt')) -cne $version -or
            [IO.File]::ReadAllText((Join-Path $installed '.runtime\fixture-bootstrap.txt')) -cne 'lease-held-runtime-not-executed') {
            throw 'Installed payload or bootstrap lease differs from the fixture.'
        }
        $inventory = Get-Content -LiteralPath (Join-Path $app '.distribution\application-files.json') -Raw | ConvertFrom-Json
        foreach ($entry in $inventory.files) {
            $target = Join-Path $installed $entry.path.Replace('/', '\')
            if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256) {
                throw "Installed fixture differs from compiler input: $($entry.path)"
            }
        }
        Assert-FixtureSentinels
        $checks[('installed_' + $version)] = $true
    }
    $history = Join-Path $env:LOCALAPPDATA 'NIPAT-Desktop\installations\backups'
    $oldVersions = @(Get-ChildItem -LiteralPath $history -Filter 'fixture-version.txt' -Recurse -File |
        Where-Object { [IO.File]::ReadAllText($_.FullName) -ceq '0.0.1' })
    if ($oldVersions.Count -lt 1) { throw 'Upgrade did not retain the previous managed file in the repair backup.' }
    $checks.upgrade_backup = $true
    $unknown = Join-Path $installed 'user-note.txt'
    [IO.File]::WriteAllText($unknown, 'unmanaged data')
    $sentinels[$unknown] = (Get-FileHash -LiteralPath $unknown -Algorithm SHA256).Hash
    $uninstaller = Join-Path $installed 'unins000.exe'
    $report.uninstaller_sha256 = (Get-FileHash -LiteralPath $uninstaller -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-FixtureProcess $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
        "/LOG=`"$(Join-Path $reportRoot 'uninstall.log')`"") 'Silent fixture removal'
    if (Test-Path -LiteralPath (Join-Path $installed 'fixture-version.txt')) { throw 'Managed payload survived removal.' }
    Assert-FixtureSentinels
    $checks.silent_removal_preserves_data = $true
    $report.status = 'passed'
    Write-Host 'PASS: compiled fixture installed, upgraded, backed up and uninstalled; user data preserved. WSL and SAC not tested.'
} catch {
    $report.error = $_.Exception.Message
    throw
} finally {
    [IO.File]::WriteAllText((Join-Path $reportRoot 'windows-installer-fixture-check.json'),
        ($report | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
    if ($createdRegistry) { Remove-Item -LiteralPath $registry -Recurse -Force }
    # Deliberately retain failure logs in ReportDirectory; WorkDirectory is owned
    # by the outer compile-fixture test and removed only by that caller.
}
