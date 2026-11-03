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
$originalLocalAppData = $env:LOCALAPPDATA
try {
    foreach ($directory in @($stage, $app, $assets, $output,
        (Join-Path $app 'installer\windows'), (Join-Path $app 'assets\branding'),
        (Join-Path $app '.distribution'))) {
        [IO.Directory]::CreateDirectory($directory) | Out-Null
    }
    # Exercise the native sharing contract used by Inno without running an installer.
    # A session holds shared read access; installation and removal require exclusive access.
    if (-not ('NipatInstallerActivityContract' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class NipatInstallerActivityContract {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern SafeFileHandle CreateFileW(string name, uint access, uint share,
        IntPtr attributes, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool GetHandleInformation(SafeFileHandle handle, out uint flags);
}
'@
    }
    $activityPath = Join-Path $temporary 'activity.lock'
    $activityHandles = New-Object 'System.Collections.Generic.List[System.IDisposable]'
    try {
        $session = [NipatInstallerActivityContract]::CreateFileW($activityPath, 2147483648, 3,
            [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
        $activityHandles.Add($session)
        if ($session.IsInvalid) { throw 'Il contratto attivita non apre la sessione condivisa.' }
        $otherSession = [NipatInstallerActivityContract]::CreateFileW($activityPath, 2147483648, 3,
            [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
        $activityHandles.Add($otherSession)
        if ($otherSession.IsInvalid) { throw 'Due sessioni devono poter coesistere.' }
        $blockedSetup = [NipatInstallerActivityContract]::CreateFileW($activityPath, 2147483648, 0,
            [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
        $blockedSetupError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        $activityHandles.Add($blockedSetup)
        if (-not $blockedSetup.IsInvalid -or $blockedSetupError -ne 32) {
            throw 'Un setup deve essere rifiutato mentre una sessione mantiene il lock.'
        }
        $session.Dispose(); $otherSession.Dispose()
        $setupLease = [NipatInstallerActivityContract]::CreateFileW($activityPath, 2147483648, 0,
            [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
        $activityHandles.Add($setupLease)
        if ($setupLease.IsInvalid) { throw 'Il setup deve ottenere il lock dopo la chiusura delle sessioni.' }
        [uint32] $handleFlags = 0
        if (-not [NipatInstallerActivityContract]::GetHandleInformation($setupLease, [ref] $handleFlags) -or
            ($handleFlags -band 1) -ne 0) { throw 'Il lock esclusivo non deve essere ereditabile.' }
        $blockedSession = [NipatInstallerActivityContract]::CreateFileW($activityPath, 2147483648, 3,
            [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
        $activityHandles.Add($blockedSession)
        if (-not $blockedSession.IsInvalid) { throw 'Una nuova sessione non deve entrare durante il setup.' }
        $setupLease.Dispose()
        $resumedSession = [NipatInstallerActivityContract]::CreateFileW($activityPath, 2147483648, 3,
            [IntPtr]::Zero, 4, 0x80, [IntPtr]::Zero)
        $activityHandles.Add($resumedSession)
        if ($resumedSession.IsInvalid) { throw 'La chiusura del setup deve liberare le nuove sessioni.' }
    } finally {
        foreach ($handle in $activityHandles) { $handle.Dispose() }
    }
    Write-Host 'PASS: native activity lease blocks setup/removal during sessions and sessions during setup; handles are not inherited.'

    # The actual validation wrapper supplies a fresh nonce, without persisting it as configuration.
    $env:LOCALAPPDATA = Join-Path $temporary 'isolated local app data'
    [IO.Directory]::CreateDirectory($env:LOCALAPPDATA) | Out-Null
    $selection = [ordered]@{ schema_version = 1; installation_channel = 'desktop' }
    foreach ($role in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        $selection[$role] = Join-Path $temporary ('nonce-' + $role)
    }
    $layoutFile = Join-Path $temporary 'nonce-selection.json'
    $infoFile = Join-Path $temporary 'nonce-info.ini'
    $errorFile = Join-Path $temporary 'nonce-error.txt'
    [IO.File]::WriteAllText($layoutFile, ($selection | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    $previousNonce = ''
    foreach ($attempt in 1..2) {
        & (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') `
            -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'validate-install-layout.ps1') `
            -LayoutFile $layoutFile -InfoFile $infoFile -ErrorFile $errorFile
        if ($LASTEXITCODE -ne 0) { throw 'Il wrapper reale non ha convalidato le cartelle del test nonce.' }
        $info = Get-Content -LiteralPath $infoFile -Encoding Unicode
        $nonceLine = @($info | Where-Object { $_ -cmatch '^setup_nonce=[a-f0-9]{32}$' })
        if ($nonceLine.Count -ne 1 -or $info -cnotcontains 'kind=empty') {
            throw 'Il wrapper non ha restituito il nonce e il tipo applicativo previsti.'
        }
        if ($nonceLine[0] -ceq $previousNonce) { throw 'Ogni convalida deve avere un nuovo nonce.' }
        $previousNonce = $nonceLine[0]
    }
    # Guided updates read the application's own validated layout, including custom storage.
    # Do not use the user's global registry preferences as the source of these defaults.
    $installedLayoutDirectory = Join-Path $selection.app_dir '.runtime'
    [IO.Directory]::CreateDirectory($installedLayoutDirectory) | Out-Null
    $installedLayoutFile = Join-Path $installedLayoutDirectory 'install-layout.json'
    [IO.File]::WriteAllText($installedLayoutFile, ($selection | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    $defaultsFile = Join-Path $temporary 'installed-defaults.ini'
    & (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') `
        -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'validate-install-layout.ps1') `
        -Project $selection.app_dir -DefaultsFile $defaultsFile -ErrorFile $errorFile
    if ($LASTEXITCODE -ne 0) { throw 'Impossibile leggere il layout effettivo per l aggiornamento guidato.' }
    $storedDefaults = Get-Content -LiteralPath $defaultsFile -Encoding Unicode
    foreach ($role in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
        if ($storedDefaults -cnotcontains "$role=$($selection[$role])") {
            throw "La destinazione $role non corrisponde al layout dell applicazione selezionata."
        }
    }
    $selection.installation_channel = 'other-channel'
    [IO.File]::WriteAllText($installedLayoutFile, ($selection | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    & (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') `
        -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'validate-install-layout.ps1') `
        -Project $selection.app_dir -DefaultsFile $defaultsFile -ErrorFile $errorFile
    if ($LASTEXITCODE -eq 0) { throw 'Un aggiornamento non deve adottare il layout di un altro canale.' }
    $selection.installation_channel = 'desktop'
    $originalAppDirectory = $selection.app_dir
    $selection.app_dir = Join-Path $temporary 'another-app'
    [IO.File]::WriteAllText($installedLayoutFile, ($selection | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    & (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') `
        -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'validate-install-layout.ps1') `
        -Project $originalAppDirectory -DefaultsFile $defaultsFile -ErrorFile $errorFile
    if ($LASTEXITCODE -eq 0) { throw 'Il layout di aggiornamento non deve reindirizzare a un altra cartella applicativa.' }
    $selection.app_dir = $originalAppDirectory
    [IO.File]::WriteAllText($installedLayoutFile, ($selection | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    $env:LOCALAPPDATA = $originalLocalAppData
    Write-Host 'PASS: validation returns a fresh setup nonce for each successful attempt.'
    Write-Host 'PASS: update defaults preserve the selected application layout and reject a foreign channel or redirected application.'
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
    $env:LOCALAPPDATA = $originalLocalAppData
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
