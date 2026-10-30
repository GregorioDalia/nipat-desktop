# No Pester, elevation, WSL, Docker or network access required.
# Runs on Windows PowerShell 5.1 and PowerShell 7.
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-bootstrap-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary) | Out-Null
$assertions = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:assertions += 1
}
function Assert-Rejected([scriptblock] $Action, [string] $Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-Test $rejected $Message
}
function New-TestManifest {
    $assets = [ordered]@{}
    foreach ($name in @('rootfs', 'scientific_image')) {
        $file = $name + '-0.8.0a1.tar.gz'
        $assets[$name] = [ordered]@{
            file = $file; sha256 = ('b' * 64); size = 123
            url = ('https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.0a1/' + $file)
        }
    }
    return [ordered]@{
        schema_version = 1; version = '0.8.0a1'; release_tag = 'v0.8.0a1'
        installation_profile = (Get-NipatInstallationProfile)
        source_commit = ('a' * 40); runtime_image = ('sha256:' + ('c' * 64)); assets = $assets
    }
}
try {
    $manifestPath = Join-Path $temporary 'installer-manifest.json'
    $manifest = New-TestManifest
    Write-NipatJsonAtomic $manifestPath $manifest
    $parsed = Read-NipatInstallerManifest $manifestPath
    Assert-Test ($parsed.release_tag -eq 'v0.8.0a1') 'accept valid release manifest'
    $profile = Get-NipatInstallationProfile
    Assert-Test ($profile.channel -ceq 'experimental08' -and $profile.app_dir_name -cne 'NIPAT-Desktop' -and
        $profile.data_dir_name -cne 'NIPAT-Desktop' -and $profile.distro_prefix -cne 'NIPAT-Desktop-' -and
        $profile.app_id -cne '6B1702B6-F75C-4F8C-956F-86626C60AF45') 'experimental identities are separate from the supported Desktop installation'
    Assert-Test ($profile.app_dir_name -cne 'NIPAT' -and $profile.data_dir_name -cne 'NIPAT' -and
        $profile.resume_key -cne 'NIPAT-ResumeSetup' -and $profile.distro_prefix -cne 'NIPAT-Runtime-') 'candidate identities differ from stable'
    Assert-Test ($profile.app_dir_name -cne 'NIPAT-0.5-Preview' -and $profile.data_dir_name -cne 'NIPAT-0.5-Preview' -and
        $profile.resume_key -cne 'NIPAT-05-Preview-ResumeSetup' -and $profile.distro_prefix -cne 'NIPAT-05-Preview-' -and
        $profile.app_id -cne '9E27D451-67B5-4D28-B388-A41CFE2F7D05') 'Desktop identities differ from the retained 0.5 Preview'
    foreach ($field in @('channel', 'app_dir_name', 'data_dir_name', 'distro_prefix', 'resume_key', 'mutex_prefix', 'app_id')) {
        $manifest = New-TestManifest
        $manifest.installation_profile.$field = 'stable'
        Write-NipatJsonAtomic $manifestPath $manifest
        Assert-Rejected { Read-NipatInstallerManifest $manifestPath } "reject foreign installation profile $field"
    }
    foreach ($badSchema in @('1', $true)) {
        $manifest = New-TestManifest
        $manifest.installation_profile.schema_version = $badSchema
        Write-NipatJsonAtomic $manifestPath $manifest
        Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject coerced profile schema version'
    }
    $manifest = New-TestManifest
    $manifest.Remove('installation_profile')
    Write-NipatJsonAtomic $manifestPath $manifest
    Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject old manifest with no installation channel'

    # Only the registry boundary is simulated; command generation and the keys are production code.
    $resumeValues = @{
        'NIPAT-ResumeSetup' = 'stable resume sentinel'
        'NIPAT-05-Preview-ResumeSetup' = 'preview resume sentinel'
        'NIPAT-Desktop-ResumeSetup' = 'desktop resume sentinel'
    }
    $registryKey = New-Object PSObject
    $registryKey | Add-Member -MemberType ScriptMethod -Name SetValue -Value {
        param($Name, $Value, $Kind)
        $script:resumeValues[$Name] = $Value
    }
    $registryKey | Add-Member -MemberType ScriptMethod -Name DeleteValue -Value {
        param($Name, $ThrowOnMissing)
        $script:resumeValues.Remove($Name)
    }
    $registryKey | Add-Member -MemberType ScriptMethod -Name Dispose -Value {}
    $openRegistry = (Get-Command Open-NipatResumeRegistry).ScriptBlock
    function Open-NipatResumeRegistry([switch] $Create) { return $script:registryKey }
    $oldLocalAppData = $env:LOCALAPPDATA
    try {
        # A short nonexistent location keeps RunOnce below its Windows length limit. No files are written there.
        $env:LOCALAPPDATA = 'C:\NipatResumeTest'
        $candidateProject = Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') $profile.app_dir_name
        Assert-NipatInstallationLocation $candidateProject
        Assert-Rejected { Assert-NipatInstallationLocation (Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') 'NIPAT') } 'bootstrap rejects stable app folder before writes'
        Assert-Rejected { Assert-NipatInstallationLocation (Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') 'NIPAT-Desktop') } 'bootstrap rejects Desktop app folder before writes'
        Assert-Rejected { Assert-NipatInstallationLocation (Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') 'NIPAT-0.5-Preview') } 'bootstrap rejects the Preview app folder before writes'
        Assert-Test (Register-NipatResume $candidateProject) 'candidate resume registration succeeds'
        Assert-Test ($resumeValues[$profile.resume_key].Contains($candidateProject)) 'candidate resume points to candidate app'
        Assert-Test ($resumeValues['NIPAT-ResumeSetup'] -ceq 'stable resume sentinel') 'register preserves stable pending resume'
        Assert-Test ($resumeValues['NIPAT-05-Preview-ResumeSetup'] -ceq 'preview resume sentinel') 'register preserves Preview pending resume'
        Assert-Test ($resumeValues['NIPAT-Desktop-ResumeSetup'] -ceq 'desktop resume sentinel') 'register preserves Desktop pending resume'
        Unregister-NipatResume
        Assert-Test ($resumeValues['NIPAT-Desktop-ResumeSetup'] -ceq 'desktop resume sentinel') 'unregister preserves Desktop pending resume'
        Assert-Test (-not $resumeValues.ContainsKey($profile.resume_key) -and
            $resumeValues['NIPAT-ResumeSetup'] -ceq 'stable resume sentinel' -and
            $resumeValues['NIPAT-05-Preview-ResumeSetup'] -ceq 'preview resume sentinel') 'unregister removes only candidate pending resume'
    } finally {
        $env:LOCALAPPDATA = $oldLocalAppData
        Set-Item -Path Function:Open-NipatResumeRegistry -Value $openRegistry
    }
    foreach ($unsupportedVersion in @('0.3.0a1', '0.5.0a1', '0.6.0', '0.6.1', '0.7.0', '0.7.0a1', '0.7.0a2', '0.7.1', '0.7.2', '0.7.3')) {
        $manifest = New-TestManifest
        $manifest.version = $unsupportedVersion
        $manifest.release_tag = 'v' + $unsupportedVersion
        foreach ($name in @('rootfs', 'scientific_image')) {
            $manifest.assets[$name].file = $manifest.assets[$name].file.Replace('0.8.0a1', $unsupportedVersion)
            $manifest.assets[$name].url = $manifest.assets[$name].url.Replace('0.8.0a1', $unsupportedVersion)
        }
        Write-NipatJsonAtomic $manifestPath $manifest
        Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject unsupported version even with consistent tag and asset URLs'
    }
    foreach ($url in @('https://example.org/rootfs.tar.gz',
        'https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.0a1/rootfs-0.8.0a1.tar.gz?redirect=1',
        'https://github.com/other/repo/releases/download/v0.8.0a1/rootfs-0.8.0a1.tar.gz')) {
        $manifest = New-TestManifest
        $manifest.assets.rootfs.url = $url
        Write-NipatJsonAtomic $manifestPath $manifest
        Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject foreign/query/repo URL'
    }
    foreach ($file in @('../rootfs.tar.gz', 'C:\rootfs.tar.gz', 'folder/rootfs.tar.gz', '..\rootfs.tar.gz')) {
        $manifest = New-TestManifest
        $manifest.assets.rootfs.file = $file
        Write-NipatJsonAtomic $manifestPath $manifest
        Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject path traversal/absolute asset file'
    }
    $manifest = New-TestManifest
    $manifest.assets.rootfs.size = -1
    Write-NipatJsonAtomic $manifestPath $manifest
    Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject negative asset size'
    $manifest = New-TestManifest
    $manifest.runtime_image = 'latest'
    Write-NipatJsonAtomic $manifestPath $manifest
    Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject mutable runtime image tag'
    $manifest = New-TestManifest
    $manifest.assets.rootfs.sha256 = 'bad'
    Write-NipatJsonAtomic $manifestPath $manifest
    Assert-Rejected { Read-NipatInstallerManifest $manifestPath } 'reject invalid asset checksum'

    $assetPath = Join-Path $temporary 'asset.tar.gz'
    [IO.File]::WriteAllBytes($assetPath, [byte[]]@(1, 2, 3, 4))
    $asset = [pscustomobject]@{ file = 'asset.tar.gz'; size = 4; sha256 = (Get-FileHash $assetPath -Algorithm SHA256).Hash.ToLowerInvariant() }
    Assert-Test (Test-NipatAsset $assetPath $asset) 'accept verified asset'
    [IO.File]::WriteAllBytes($assetPath, [byte[]]@(4, 3, 2, 1))
    Assert-Test (-not (Test-NipatAsset $assetPath $asset)) 'reject altered asset with same size'
    [IO.File]::WriteAllBytes($assetPath, [byte[]]@(1, 2, 3))
    Assert-Test (-not (Test-NipatAsset $assetPath $asset)) 'reject wrong asset size'
    Assert-Test (-not (Test-NipatAsset (Join-Path $temporary 'missing') $asset)) 'reject missing asset'
    $assetDirectory = Join-Path $temporary 'offline'
    $cacheDirectory = Join-Path $temporary 'cache'
    [IO.Directory]::CreateDirectory($assetDirectory) | Out-Null
    [IO.Directory]::CreateDirectory($cacheDirectory) | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $assetDirectory $asset.file), [byte[]]@(1, 2, 3, 4))
    $cached = Get-NipatAsset $asset $cacheDirectory $assetDirectory
    Assert-Test (Test-NipatAsset $cached $asset) 'offline asset copied and reverified in cache'
    # Inno installs directly to this same hash-addressed cache before bootstrap starts.
    # No original extraction medium, URL or download is needed after installation/reboot.
    Remove-Item -LiteralPath $assetDirectory -Recurse -Force
    function Invoke-WebRequest { throw 'Unexpected download while embedded cache is valid.' }
    try {
        $cacheOnly = Get-NipatAsset $asset $cacheDirectory ''
        Assert-Test ($cacheOnly -ceq $cached) 'embedded cache works with no asset directory or download'
        $afterRemoval = Get-NipatAsset $asset $cacheDirectory $assetDirectory
        Assert-Test ($afterRemoval -ceq $cached) 'cached archive remains usable after installer media is removed'
        Assert-Test (@(Get-ChildItem -LiteralPath $cacheDirectory -File).Count -eq 1) 'cache retrieval never creates a second permanent archive'
    } finally {
        Remove-Item Function:Invoke-WebRequest
    }
    [IO.Directory]::CreateDirectory($assetDirectory) | Out-Null
    [IO.File]::WriteAllBytes($cached, [byte[]]@(0, 0, 0, 0))
    [IO.File]::WriteAllBytes((Join-Path $assetDirectory $asset.file), [byte[]]@(9, 9, 9, 9))
    Assert-Rejected { Get-NipatAsset $asset $cacheDirectory $assetDirectory } 'reject altered cache and offline file without execution'

    $statePath = Join-Path $temporary 'state.json'
    Write-NipatJsonAtomic $statePath ([ordered]@{ schema_version = 1; phase = 'starting' })
    $unicodePath = 'C:\Users\Jos' + [char]0x00E9 + '\Dati ' + [char]0x6D4B + [char]0x8BD5
    Write-NipatJsonAtomic $statePath ([ordered]@{ schema_version = 1; phase = 'ready'; data_dir = $unicodePath })
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($state.phase -eq 'ready') 'atomic state replacement retains complete JSON'
    Assert-Test ($state.data_dir -ceq $unicodePath) 'UTF-8 state preserves Unicode user paths on Windows PowerShell 5.1'
    Assert-Test (@(Get-ChildItem -LiteralPath $temporary -Filter '.write-*').Count -eq 0) 'atomic state leaves no temporary files'

    Assert-Test ((ConvertTo-NipatNativeArgument 'plain') -ceq 'plain') 'native plain argument'
    Assert-Test ((ConvertTo-NipatNativeArgument '') -ceq '""') 'native empty argument'
    Assert-Test ((ConvertTo-NipatNativeArgument 'C:\a b\') -ceq '"C:\a b\\"') 'native path space and trailing slash'
    Assert-Test ((ConvertTo-NipatNativeArgument 'a"b') -ceq '"a\"b"') 'native embedded quote'
    $script:NipatWsl = (Get-Process -Id $PID).Path
    $probe = Invoke-NipatWsl @('-NoLogo', '-NoProfile', '-Command', "[Console]::Error.WriteLine('warning'); [Console]::WriteLine('marker'); exit 0") -TimeoutSeconds 20
    Assert-Test ($probe.Text -ceq 'marker' -and $probe.ErrorText -ceq 'warning') 'native stderr warning does not corrupt marker output'
    $failure = Invoke-NipatWsl @('-NoLogo', '-NoProfile', '-Command', 'exit 7') -AllowFailure -TimeoutSeconds 20
    Assert-Test ($failure.ExitCode -eq 7) 'native failure is inspectable'
    $inputEncodingBefore = [Console]::InputEncoding
    $inputEncodingSignature = $inputEncodingBefore.CodePage.ToString() + ':' + [Convert]::ToBase64String($inputEncodingBefore.GetPreamble())
    # Read raw bytes through EOF: Console.ReadLine may hide or reinterpret a BOM.
    $stdinProbe = '$bytes = New-Object IO.MemoryStream; [Console]::OpenStandardInput().CopyTo($bytes); [Console]::WriteLine($bytes.Length); $bytes.Dispose()'
    $stdin = Invoke-NipatWsl @('-NoLogo', '-NoProfile', '-Command', $stdinProbe) -TimeoutSeconds 20
    Assert-Test ($stdin.Text -ceq '0') ("native stdin reaches EOF with zero bytes; stdout=$($stdin.Text); stderr=$($stdin.ErrorText); exit=$($stdin.ExitCode)")
    $inputEncodingAfter = [Console]::InputEncoding
    $afterSignature = $inputEncodingAfter.CodePage.ToString() + ':' + [Convert]::ToBase64String($inputEncodingAfter.GetPreamble())
    Assert-Test ($afterSignature -ceq $inputEncodingSignature) 'native launch restores original console input encoding'
    Assert-Rejected { Invoke-NipatWsl @('-NoLogo', '-NoProfile', '-Command', 'Start-Sleep -Seconds 10') -TimeoutSeconds 1 } 'native probe timeout is bounded'
    Write-Host "PASS: $assertions installer assertions."
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
