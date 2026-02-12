param(
  [ValidateSet("up", "down", "logs", "secret")]
  [string]$Cmd = "up"
)

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$settings = Join-Path $here "searxng/settings.yml"

function New-HexSecret([int]$bytes = 32) {
  $randomBytes = New-Object byte[] $bytes
  (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes)
  return -join ($randomBytes | ForEach-Object { "{0:x2}" -f $_ })
}

function Ensure-Secret() {
  if (!(Test-Path $settings)) {
    throw "Missing settings.yml at $settings"
  }
  $content = Get-Content $settings -Raw
  if ($content -match "ultrasecretkey") {
    $secret = New-HexSecret 32
    $content = $content -replace "ultrasecretkey", $secret
    Set-Content -Path $settings -Value $content -Encoding utf8
    Write-Host "Generated secret_key in $settings"
  } else {
    Write-Host "Secret already set in $settings"
  }
}

Push-Location $here
try {
  switch ($Cmd) {
    "secret" { Ensure-Secret; exit 0 }
    "up" {
      Ensure-Secret
      docker compose up -d
      Write-Host "SearXNG: http://127.0.0.1:8088"
      exit 0
    }
    "down" { docker compose down; exit 0 }
    "logs" { docker compose logs -f; exit 0 }
  }
} finally {
  Pop-Location
}

