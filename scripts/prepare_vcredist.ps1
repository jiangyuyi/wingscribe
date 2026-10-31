param([ValidateSet('cpu','gpu')][string]$Mode = 'cpu')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$expected = '843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c'
$cache = Join-Path $root 'installer/runtime-cache/vc_redist-14.51.36247.x64.exe'
if (-not (Test-Path -LiteralPath $cache)) {
    New-Item -ItemType Directory -Path (Split-Path $cache) -Force | Out-Null
    # No verified same-version domestic mirror is currently known. This URL
    # may advance; the pinned digest rejects a different version, never upgrades.
    Write-Host 'Fetching Microsoft VC++ runtime from official source (no verified domestic mirror).'
    Invoke-WebRequest 'https://aka.ms/vc14/vc_redist.x64.exe' -OutFile "$cache.part" -UseBasicParsing
    if ((Get-FileHash -LiteralPath "$cache.part" -Algorithm SHA256).Hash -ne $expected) {
        throw 'VC++ download differs from pinned 14.51.36247; partial file retained for inspection'
    }
    Move-Item -LiteralPath "$cache.part" -Destination $cache
}
if ((Get-FileHash -LiteralPath $cache -Algorithm SHA256).Hash -ne $expected) { throw 'VC++ cache hash mismatch' }
$signature = Get-AuthenticodeSignature -LiteralPath $cache
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'VC++ Microsoft Authenticode validation failed'
}
$destination = Join-Path $root "installer/build-$Mode/prerequisites"
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -LiteralPath $cache -Destination (Join-Path $destination 'vc_redist.x64.exe') -Force
Write-Host 'Pinned Microsoft VC++ x64 runtime verified and staged.'
