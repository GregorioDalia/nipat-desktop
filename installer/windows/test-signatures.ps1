Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'verify-signatures.ps1')

$checks = 0
function Assert-Test([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw "Signature check failed: $Message" }
    $script:checks++
}
function Assert-Rejected([scriptblock] $Operation, [string] $Pattern) {
    $caught = $null
    try { & $Operation | Out-Null } catch { $caught = $_.Exception.Message }
    Assert-Test ($null -ne $caught -and $caught -match $Pattern) "expected failure /$Pattern/, received: $caught"
}
function New-TestCertificate([string] $Subject, [string] $Eku) {
    return [pscustomobject]@{
        Subject = $Subject
        RawData = [Text.Encoding]::UTF8.GetBytes($Subject + ':' + $Eku)
        Extensions = @([pscustomobject]@{
            Oid = [pscustomobject]@{ Value = '2.5.29.37' }
            EnhancedKeyUsages = @([pscustomobject]@{ Value = $Eku })
        })
    }
}
function Reset-TestSignature {
    $script:signature = [pscustomobject]@{
        Status = 'Valid'
        SignatureType = 'Authenticode'
        SignerCertificate = New-TestCertificate 'CN=NIPAT Test Publisher, O=Test' '1.3.6.1.5.5.7.3.3'
        TimeStamperCertificate = New-TestCertificate 'CN=Timestamp Test' '1.3.6.1.5.5.7.3.8'
    }
    $script:toolFailure = $false
    $script:mutateBinary = $false
    $script:verifiedPaths = @()
}

# Trust evaluation is mocked, never achieved by importing a test root into Windows.
# These fixtures exercise rejection/coverage; they are not cryptographic evidence.
function Get-NipatAuthenticodeSignature([string] $Path) { return $script:signature }
function Invoke-NipatSignToolVerification([string] $Tool, [string] $Path) {
    if ($script:toolFailure) { throw 'SignTool verification failed (2): timestamp warning' }
    if ($script:mutateBinary) { [IO.File]::AppendAllText($Path, 'changed') }
    $script:verifiedPaths += $Path
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('nipat-signature-test-' + [Guid]::NewGuid().ToString('N'))
try {
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    foreach ($name in @('NIPAT-Setup.exe', 'NIPAT.exe', 'EnableWsl.exe', 'unins000.exe', 'signtool.exe')) {
        [IO.File]::WriteAllText((Join-Path $temporary $name), 'unsigned fixture: ' + $name)
    }
    $arguments = @{
        SetupPath = Join-Path $temporary 'NIPAT-Setup.exe'
        LauncherPath = Join-Path $temporary 'NIPAT.exe'
        WslHelperPath = Join-Path $temporary 'EnableWsl.exe'
        UninstallerPath = Join-Path $temporary 'unins000.exe'
        SignToolPath = Join-Path $temporary 'signtool.exe'
        ExpectedPublisherSubject = 'CN=NIPAT Test Publisher, O=Test'
    }
    Reset-TestSignature
    $report = Invoke-NipatSignatureVerification @arguments
    Assert-Test ($report.files.Count -eq 4 -and $script:verifiedPaths.Count -eq 4) 'all four binary roles verified'
    foreach ($role in @('setup', 'launcher', 'wsl_helper', 'uninstaller')) {
        Assert-Test ($report.files[$role].sha256 -cmatch '^[0-9a-f]{64}$') "SHA-256 evidence for $role"
        Assert-Test ($report.files[$role].publisher_subject -ceq $arguments.ExpectedPublisherSubject) "publisher for $role"
    }
    $reportPath = Join-Path $temporary 'verified.json'
    Invoke-NipatSignatureVerification @arguments -OutputPath $reportPath | Out-Null
    $saved = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Test ($saved.files.uninstaller.file -ceq 'unins000.exe') 'evidence records uninstaller coverage'
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments -OutputPath $reportPath } 'already exists'

    $noPublisher = $arguments.Clone()
    $noPublisher.ExpectedPublisherSubject = ''
    Assert-Rejected { Invoke-NipatSignatureVerification @noPublisher } 'exact, reviewed publisher'
    foreach ($status in @('NotSigned', 'NotTrusted', 'HashMismatch', 'UnknownError')) {
        Reset-TestSignature
        $script:signature.Status = $status
        Assert-Rejected { Invoke-NipatSignatureVerification @arguments } 'valid trusted Authenticode'
    }
    Reset-TestSignature
    $script:signature.SignatureType = 'Catalog'
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments } 'valid trusted Authenticode'
    Reset-TestSignature
    $script:signature.SignerCertificate.Subject = 'CN=Different Publisher'
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments } 'Unexpected publisher'
    Reset-TestSignature
    $script:signature.SignerCertificate.Extensions = @()
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments } 'code-signing EKU'
    Reset-TestSignature
    $script:signature.TimeStamperCertificate = $null
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments } 'requires a timestamp'
    Reset-TestSignature
    $script:signature.TimeStamperCertificate.Extensions = @()
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments } 'requires a timestamp'
    Reset-TestSignature
    $script:toolFailure = $true
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments } 'SignTool verification failed'
    Reset-TestSignature
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments -AllowedSignerCertificateSha256 @('a' * 64) } 'certificate pins'
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments -AllowedSignerCertificateSha256 @('invalid') } 'lowercase SHA-256'
    $pin = Get-NipatCertificateSha256 $script:signature.SignerCertificate
    Invoke-NipatSignatureVerification @arguments -AllowedSignerCertificateSha256 @(('a' * 64), $pin) | Out-Null
    Assert-Test ($script:verifiedPaths.Count -eq 4) 'certificate rotation allowlist accepts the matching pin'

    $missing = $arguments.Clone()
    $missing.UninstallerPath = ''
    Assert-Rejected { Invoke-NipatSignatureVerification @missing } 'Missing uninstaller'
    $missing.UninstallerPath = Join-Path $temporary 'absent.exe'
    Assert-Rejected { Invoke-NipatSignatureVerification @missing } 'does not exist|Cannot find path'
    $duplicate = $arguments.Clone()
    $duplicate.UninstallerPath = $arguments.SetupPath
    Assert-Rejected { Invoke-NipatSignatureVerification @duplicate } 'separate file'
    Reset-TestSignature
    $script:mutateBinary = $true
    $failedReport = Join-Path $temporary 'must-not-exist.json'
    Assert-Rejected { Invoke-NipatSignatureVerification @arguments -OutputPath $failedReport } 'changed during signature verification'
    Assert-Test (-not (Test-Path -LiteralPath $failedReport)) 'failed checks never emit successful evidence'
    Write-Output "PASS: $checks signature-policy checks (mocked Windows trust evaluation)."
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
