[CmdletBinding(DefaultParameterSetName = 'Validate')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Validate')][string] $LayoutFile,
    [Parameter(ParameterSetName = 'Validate')][string] $InfoFile,
    [Parameter(Mandatory = $true, ParameterSetName = 'Defaults')][string] $Project,
    [Parameter(Mandatory = $true, ParameterSetName = 'Defaults')][string] $DefaultsFile,
    [Parameter(Mandatory = $true)][string] $ErrorFile
)

# Used before copying files. Reading defaults and validating selections never imports a runtime.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'install-profile.ps1')
    . (Join-Path $PSScriptRoot 'install-layout.ps1')
    if ($PSCmdlet.ParameterSetName -ceq 'Defaults') {
        $layout = Read-NipatInstallLayout $Project -Historical
        $lines = @('[NIPAT]')
        foreach ($name in @('app_dir', 'runtime_dir', 'cache_dir', 'data_dir', 'runs_dir')) {
            $lines += "$name=$($layout.$name)"
        }
        # GetIniString uses the Unicode Windows INI API; preserve non-ASCII paths.
        [IO.File]::WriteAllLines($DefaultsFile, [string[]] $lines, [Text.Encoding]::Unicode)
    } else {
        if ($InfoFile -and (Test-Path -LiteralPath $InfoFile)) {
            Remove-Item -LiteralPath $InfoFile -Force
        }
        $layout = Get-Content -LiteralPath $LayoutFile -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-NipatInstallLayout $layout
        $kind = Get-NipatApplicationKind $layout.app_dir
        if ($InfoFile) {
            # A fresh, short-lived setup lease is created by Inno only after validation succeeds.
            $setupNonce = [Guid]::NewGuid().ToString('N')
            [IO.File]::WriteAllLines($InfoFile, [string[]] @('[NIPAT]', "kind=$kind", "setup_nonce=$setupNonce"),
                [Text.Encoding]::Unicode)
        }
        Assert-NipatInstallLayout $layout -CheckExisting
    }
    exit 0
} catch {
    try {
        [IO.File]::WriteAllText($ErrorFile, $_.Exception.Message, (New-Object Text.UTF8Encoding($false)))
    } catch { [Console]::Error.WriteLine('Impossibile registrare il motivo del rifiuto delle cartelle.') }
    exit 1
}
