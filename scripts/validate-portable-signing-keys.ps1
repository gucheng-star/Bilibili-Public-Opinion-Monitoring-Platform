[CmdletBinding()]
param(
    [string]$PublicKeyBase64 = $env:BILI_PORTABLE_UPDATE_PUBLIC_KEY,
    [string]$PrivateKeyPemBase64 = $env:PORTABLE_UPDATE_PRIVATE_KEY_PEM_B64,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$OpenSslPath = "openssl"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)

if ([string]::IsNullOrWhiteSpace($PublicKeyBase64)) {
    throw "Missing PORTABLE_UPDATE_PUBLIC_KEY_B64"
}
if ([string]::IsNullOrWhiteSpace($PrivateKeyPemBase64)) {
    throw "Missing PORTABLE_UPDATE_PRIVATE_KEY_PEM_B64"
}

try {
    $configuredPublicKey = [Convert]::FromBase64String($PublicKeyBase64)
}
catch {
    throw "PORTABLE_UPDATE_PUBLIC_KEY_B64 is not valid Base64"
}
if ($configuredPublicKey.Length -ne 32) {
    throw "PORTABLE_UPDATE_PUBLIC_KEY_B64 must decode to exactly 32 bytes"
}

try {
    $privateKeyBytes = [Convert]::FromBase64String($PrivateKeyPemBase64)
}
catch {
    throw "PORTABLE_UPDATE_PRIVATE_KEY_PEM_B64 is not valid Base64"
}

$resolvedOutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedOutputDirectory -Force | Out-Null
$privateKey = Join-Path $resolvedOutputDirectory "portable-update-private.pem"
$derivedPublicKeyDer = Join-Path $resolvedOutputDirectory "portable-update-public.der"
$derivedPublicKeyPem = Join-Path $resolvedOutputDirectory "portable-update-public.pem"
[IO.File]::WriteAllBytes($privateKey, $privateKeyBytes)

& $OpenSslPath pkey -in $privateKey -pubout -outform DER -out $derivedPublicKeyDer
if ($LASTEXITCODE -ne 0) {
    throw "Unable to derive a public key from PORTABLE_UPDATE_PRIVATE_KEY_PEM_B64"
}
& $OpenSslPath pkey -in $privateKey -pubout -out $derivedPublicKeyPem
if ($LASTEXITCODE -ne 0) {
    throw "Unable to export the portable update public key"
}

$derivedDer = [IO.File]::ReadAllBytes($derivedPublicKeyDer)
[byte[]]$ed25519SpkiPrefix = 0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00
if ($derivedDer.Length -ne 44) {
    throw "PORTABLE_UPDATE_PRIVATE_KEY_PEM_B64 is not an Ed25519 private key"
}
for ($index = 0; $index -lt $ed25519SpkiPrefix.Length; $index++) {
    if ($derivedDer[$index] -ne $ed25519SpkiPrefix[$index]) {
        throw "PORTABLE_UPDATE_PRIVATE_KEY_PEM_B64 is not an Ed25519 private key"
    }
}

[byte[]]$derivedRawPublicKey = [byte[]]::new(32)
[Array]::Copy($derivedDer, $ed25519SpkiPrefix.Length, $derivedRawPublicKey, 0, 32)
if ([Convert]::ToHexString($configuredPublicKey) -cne [Convert]::ToHexString($derivedRawPublicKey)) {
    throw "Portable update public and private keys do not match"
}

Write-Output "Portable update signing keys validated."
