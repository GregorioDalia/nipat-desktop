# Integration gate: load the ACTUAL exported asset in a fresh dedicated engine.
# Linux + Docker + PowerShell only. Does not simulate Windows/WSL/UAC installation.
param(
    [Parameter(Mandatory = $true)][string] $ManifestPath,
    [Parameter(Mandatory = $true)][string] $AssetDirectory,
    [Parameter(Mandatory = $true)][string] $RootfsImage
)
. (Join-Path $PSScriptRoot 'bootstrap-common.ps1')
$manifest = Read-NipatInstallerManifest $ManifestPath
$script:NipatWsl = (Get-Command docker -ErrorAction Stop).Source
$script:NativeInvoke = ${function:Invoke-NipatWsl}
$script:TestContainer = 'nipat-image-test-' + [Guid]::NewGuid().ToString('N')
$script:TestCache = Join-Path ([IO.Path]::GetTempPath()) $script:TestContainer
[IO.Directory]::CreateDirectory($script:TestCache) | Out-Null
$created = $false

# Adapt only the WSL process boundary to docker exec in the disposable Linux
# rootfs container. Asset verification and image resolution are production code.
function Invoke-NipatWsl([string[]] $Arguments, [switch] $AllowFailure, [int] $TimeoutSeconds = 1800) {
    if (($Arguments[0..4] -join '|') -cne '--distribution|NIPAT-Test|--user|root|--exec') {
        throw 'Unexpected integration-test target.'
    }
    if ($Arguments[5] -ceq 'wslpath') {
        $path = [IO.Path]::GetFullPath($Arguments[-1])
        if ([IO.Path]::GetDirectoryName($path) -cne $script:TestCache) {
            throw 'Archive is outside the verified test cache.'
        }
        return [pscustomobject]@{
            ExitCode = 0; Text = ('/nipat-cache/' + [IO.Path]::GetFileName($path)); ErrorText = ''
        }
    }
    return (& $script:NativeInvoke (@('exec', $script:TestContainer) + $Arguments[5..($Arguments.Length - 1)]) -TimeoutSeconds $TimeoutSeconds)
}
try {
    $created = $true
    # A nested engine cannot unpack overlayfs whiteouts into the outer
    # container's writable layer. Give both data stores fresh host-backed
    # anonymous volumes, as for Docker-in-Docker, and remove only these on exit.
    & $script:NativeInvoke @('run', '--detach', '--name', $script:TestContainer,
        '--privileged', '--cgroupns=host',
        '--mount', 'type=volume,target=/var/lib/docker',
        '--mount', 'type=volume,target=/var/lib/containerd', '--mount',
        ('type=bind,source=' + $script:TestCache + ',target=/nipat-cache,readonly'),
        '--entrypoint', '/bin/sleep', $RootfsImage, 'infinity') -TimeoutSeconds 120 | Out-Null
    $storage = & $script:NativeInvoke @('exec', $script:TestContainer,
        'stat', '-f', '-c', '%T %n', '/var/lib/docker', '/var/lib/containerd')
    Write-Host $storage.Text
    & $script:NativeInvoke @('exec', $script:TestContainer, '/usr/local/bin/nipat-engine', 'ensure') -TimeoutSeconds 240 | Out-Null
    $info = Invoke-NipatRuntimeDocker 'NIPAT-Test' @('info', '--format', '{{.ServerVersion}} {{.Driver}} {{json .DriverStatus}}')
    Write-Host $info.Text
    $imageId = Install-NipatScientificImage $manifest $script:TestCache $AssetDirectory 'NIPAT-Test'
    $probe = Invoke-NipatRuntimeDocker 'NIPAT-Test' @('run', '--rm', '--pull=never',
        $imageId, 'sh', '-ec', 'Rscript -e ''stopifnot(requireNamespace("argparse", quietly=TRUE)); cat(R.version.string, "\n")''; samtools --version') -TimeoutSeconds 240
    Write-Host $probe.Text
    $again = Install-NipatScientificImage $manifest $script:TestCache $AssetDirectory 'NIPAT-Test'
    if ($again -cne $imageId) { throw 'Setup resume resolved a different image.' }
    Write-Host "PASS: exported scientific asset loaded, executed and reloaded in the shipped engine: $imageId"
} finally {
    if ($created) {
        & $script:NativeInvoke @('container', 'rm', '--force', '--volumes', $script:TestContainer) -AllowFailure -TimeoutSeconds 60 | Out-Null
    }
    if (Test-Path -LiteralPath $script:TestCache) { Remove-Item -LiteralPath $script:TestCache -Recurse -Force }
}
