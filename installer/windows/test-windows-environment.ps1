# Synthetic platform/readiness tests. These do not install WSL or prove a real
# Windows 10/11 installation. Suitable for the Windows Server CI runner as well.
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
Add-Type -Path (Join-Path $PSScriptRoot 'EnableWsl.cs')
$assertions = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:assertions += 1
}

# Both non-elevated and elevated gates must agree, including Server builds that
# are numerically newer than the supported client minimum.
foreach ($case in @(
    @($true, $true, 'AMD64', 19045, 1, 'Client', $true),
    @($true, $true, 'AMD64', 22000, 1, 'Client', $true),
    @($true, $true, 'AMD64', 26100, 1, 'Client', $true),
    @($true, $true, 'AMD64', 19044, 1, 'Client', $false),
    @($true, $true, 'AMD64', 19041, 1, 'Client', $false),
    @($true, $true, 'AMD64', 20348, 1, 'Client', $false),
    @($true, $true, 'AMD64', 20348, 3, 'Server', $false),
    @($true, $true, 'AMD64', 26100, 3, 'Server Core', $false),
    @($true, $true, 'AMD64', 26100, 2, 'Server', $false),
    @($true, $true, 'ARM64', 26100, 1, 'Client', $false),
    @($false, $false, 'x86', 19045, 1, 'Client', $false),
    @($true, $false, 'AMD64', 19045, 1, 'Client', $false)
)) {
    $accepted = $true
    try { Assert-NipatWindowsPlatform $case[0] $case[1] $case[2] $case[3] $case[4] } catch { $accepted = $false }
    Assert-Test ($accepted -eq $case[6]) "bootstrap platform: $($case -join ',')"
    $helper = [NipatWindowsPolicy]::Supports($case[0], $case[1], $case[2], $case[3], $case[5])
    Assert-Test ($helper -eq $case[6]) "elevated platform: $($case -join ',')"
}

# Only the WSL/system boundary is mocked. The production readiness parser and
# sequencing are executed; probes must not change distributions or install one.
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-platform-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$script:NipatWsl = Join-Path $temporary 'wsl-fixture.exe'
$probe = (Get-Command Invoke-NipatWsl).ScriptBlock
$script:probeCalls = @()
$script:versionText = ''
$script:versionExit = 0
$script:statusExit = 0
$script:servicePresent = $true
function Invoke-NipatWsl([string[]] $Arguments, [switch] $AllowFailure, [int] $TimeoutSeconds) {
    $script:probeCalls += ($Arguments -join ' ')
    switch ($Arguments -join ' ') {
        '--version' { return [pscustomobject]@{ ExitCode = $script:versionExit; Text = $script:versionText } }
        '--status' { return [pscustomobject]@{ ExitCode = $script:statusExit; Text = 'localized status' } }
        default { throw 'Unexpected WSL mutation or unsupported probe.' }
    }
}
function Get-Service([string] $Name, [string] $ErrorAction) {
    if ($Name -ne 'vmcompute') { throw 'Unexpected service probe.' }
    if ($script:servicePresent) { return [pscustomobject]@{ Name = 'vmcompute' } }
}
try {
    $missing = Get-NipatWslReadiness
    Assert-Test (-not $missing.Ready -and $missing.Kind -ceq 'missing' -and $probeCalls.Count -eq 0) 'missing WSL requires configuration without invoking an absent executable'
    [IO.File]::WriteAllText($script:NipatWsl, 'fixture')
    foreach ($case in @(
        @('WSL version: 2.6.1.0', 0, $true),
        @('Versione WSL: 1.0.0', 0, $true),
        @("`nVersion WSL : 2.4.13.0`nVersion du noyau : 5.15.0", 0, $true),
        @('WSL version: 0.67.6.0', 0, $false),
        @('WSL version: 2.6.1.0', 1, $false),
        @('', 0, $false),
        @("Uso: wsl.exe --help`nWindows: 10.0.26100", 0, $false)
    )) {
        $script:versionText = $case[0]; $script:versionExit = $case[1]; $script:probeCalls = @()
        $state = Get-NipatWslReadiness
        Assert-Test ($state.Ready -eq $case[2]) "localized WSL readiness: $($case[0])"
        Assert-Test ([NipatWindowsPolicy]::ModernWsl($case[1], $case[0]) -eq $case[2]) 'helper agrees on modern WSL'
        Assert-Test (($probeCalls -join ',') -ceq $(if ($case[2]) { '--version,--status' } else { '--version' })) 'only read-only probes run, status only after a valid package version'
    }
    $script:versionText = 'WSL version: 2.6.1.0'; $script:versionExit = 0
    $script:statusExit = 1
    $state = Get-NipatWslReadiness
    Assert-Test (-not $state.Ready -and $state.Kind -ceq 'configuration') 'package alone is insufficient with failed status'
    $script:statusExit = 0; $script:servicePresent = $false
    Assert-Test (-not (Get-NipatWslReadiness).Ready) 'package and status alone are insufficient without VM compute service'

    Assert-Test ([NipatWindowsPolicy]::Command($true, '--update --web-download') -ceq '--update --web-download') 'modern WSL update uses official web download when supported'
    Assert-Test ([NipatWindowsPolicy]::Command($false, '--update') -ceq '--update') 'legacy update does not receive unsupported flags'
    Assert-Test ([NipatWindowsPolicy]::Command($false, '--install --no-distribution --web-download') -ceq '--install --no-distribution --web-download') 'missing WSL installs without a default distro'
    Assert-Test ([NipatWindowsPolicy]::Command($false, '--install --no-distribution') -ceq '--install --no-distribution') 'older installer without web-download uses supported distribution-free install'
    Assert-Test ($null -eq [NipatWindowsPolicy]::Command($false, '--install')) 'never install Ubuntu as an accidental fallback'
    Assert-Test ($null -eq [NipatWindowsPolicy]::Command($true, '--install --no-distribution')) 'an existing package is not silently reinstalled when update is unavailable'
    Write-Host "PASS: $assertions Windows platform/WSL decision assertions (simulated, no OS installation)."
} finally {
    Set-Item Function:Invoke-NipatWsl $probe
    Remove-Item Function:Get-Service
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
