param(
    [Parameter(Mandatory = $true)][string] $CompilerPath
)

# Compile the actual installer definition using a tiny payload. Never execute the generated setup.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $CompilerPath -PathType Leaf)) {
    throw 'Il compilatore Inno Setup verificato non e disponibile.'
}
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$temporary = Join-Path ([IO.Path]::GetTempPath()) (
    'nipat installer & ' + [char]0x00e8 + [char]0x03a9 + '-' + [Guid]::NewGuid().ToString('N'))
$stage = Join-Path $temporary 'stage with spaces'
$app = Join-Path $stage 'app'
$assets = Join-Path $temporary 'runtime archives'
$output = Join-Path $temporary 'compiled setup'
try {
    foreach ($directory in @($stage, $app, $assets, $output,
        (Join-Path $app 'installer\windows'), (Join-Path $app 'assets\branding'),
        (Join-Path $app '.distribution'))) {
        [IO.Directory]::CreateDirectory($directory) | Out-Null
    }
    Copy-Item -LiteralPath (Join-Path $project 'LICENSE') -Destination (Join-Path $app 'LICENSE')
    Copy-Item -LiteralPath (Join-Path $project 'assets\branding\nipat-icon.ico') `
        -Destination (Join-Path $app 'assets\branding\nipat-icon.ico')
    foreach ($name in @('install-profile.ps1', 'install-profile.json', 'install-layout.ps1',
        'validate-install-layout.ps1', 'repair-installation.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) `
            -Destination (Join-Path (Join-Path $app 'installer\windows') $name)
    }
    $applicationFiles = @(
        Get-ChildItem -LiteralPath $app -Recurse -File | Sort-Object FullName | ForEach-Object {
            [ordered]@{
                path = $_.FullName.Substring($app.Length + 1).Replace('\', '/')
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    )
    $inventory = [ordered]@{
        schema_version = 1
        installation_channel = 'desktop'
        source_commit = ('0' * 40)
        files = $applicationFiles
    }
    [IO.File]::WriteAllText((Join-Path $app '.distribution\application-files.json'),
        ($inventory | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
    $profile = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'install-profile.json') -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $definitions = [ordered]@{
        NipatVersion = '0.6.0'
        NipatAppId = ('{{' + $profile.app_id + '}')
        NipatDisplayName = $profile.display_name
        NipatAppDirectory = $profile.app_dir_name
        NipatDataDirectory = $profile.data_dir_name
        NipatResumeKey = $profile.resume_key
    }
    $profileLines = @('; Compile-only fixture; not an installable NIPAT package.')
    foreach ($name in $definitions.Keys) {
        $profileLines += ('#define ' + $name + ' "' + $definitions[$name] + '"')
    }
    [IO.File]::WriteAllLines((Join-Path $stage 'install-profile.iss'), [string[]] $profileLines,
        (New-Object Text.UTF8Encoding($false)))
    $assetLines = @('; Compile-only archives are never installed or executed.')
    foreach ($name in @('rootfs-compile-only.tar.gz', 'scientific-compile-only.tar.gz')) {
        $asset = Join-Path $assets $name
        [IO.File]::WriteAllBytes($asset, [Text.Encoding]::ASCII.GetBytes('NIPAT compiler fixture: ' + $name))
        $digest = (Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash.ToLowerInvariant()
        $assetLines += ('Source: "{#RuntimeAssetsDir}\' + $name + '"; ' +
            'DestDir: "{code:GetNipatCacheDir}"; DestName: "' + $digest + '-' + $name + '"; ' +
            'Hash: "' + $digest + '"; Flags: ignoreversion uninsneveruninstall nocompression solidbreak')
    }
    [IO.File]::WriteAllLines((Join-Path $stage 'runtime-assets.iss'), [string[]] $assetLines,
        (New-Object Text.UTF8Encoding($false)))
    & $CompilerPath '/Qp' "/DStageDir=$stage" "/DRuntimeAssetsDir=$assets" "/DOutputDir=$output" `
        (Join-Path $PSScriptRoot 'NIPAT.iss')
    if ($LASTEXITCODE -ne 0) { throw 'La compilazione della definizione installer e fallita.' }
    $setup = Join-Path $output 'NIPAT-Setup.exe'
    if (-not (Test-Path -LiteralPath $setup -PathType Leaf) -or
        (Get-Item -LiteralPath $setup).Length -le 0) {
        throw 'Il compilatore non ha prodotto il file setup atteso.'
    }
    Write-Host 'PASS: real installer definition compiled with spaces and Unicode paths; fixture EXE not executed.'
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
