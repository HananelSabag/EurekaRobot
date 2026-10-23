# Briefly joins the robot's open AP (robot_b8_xxxx), runs ap_probe.py, then always returns to the home Wi-Fi.
# The PC is offline for about a minute while this runs.
param([string]$RobotSsid = 'robot_b8_xxxx')
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root '.venv\Scripts\python.exe'
$out = Join-Path $root 'data\ap-probe.json'
$log = Join-Path $root 'data\ap-hop.log'
function Log($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -FilePath $log -Append }

$homeProfile = ((netsh wlan show interfaces) | Select-String '^\s+Profile\s+:\s+(.+)$').Matches[0].Groups[1].Value.Trim()
Log "home profile: $homeProfile"
$xml = @"
<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>$RobotSsid</name>
  <SSIDConfig><SSID><name>$RobotSsid</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM><security><authEncryption><authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX></authEncryption></security></MSM>
</WLANProfile>
"@
$xmlPath = Join-Path $env:TEMP "$RobotSsid.xml"
$xml | Set-Content -Path $xmlPath -Encoding utf8
try {
  netsh wlan add profile filename="$xmlPath" | Out-Null
  Log "connecting to $RobotSsid"
  netsh wlan connect name="$RobotSsid" ssid="$RobotSsid" | Out-Null
  $gw = $null
  for ($i = 0; $i -lt 30 -and -not $gw; $i++) {
    Start-Sleep 1
    $cfg = Get-NetIPConfiguration -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue
    $ssidNow = ((netsh wlan show interfaces) | Select-String '^\s+SSID\s+:\s+(.+)$').Matches | Select-Object -First 1
    if ($ssidNow -and $ssidNow.Groups[1].Value.Trim() -eq $RobotSsid -and $cfg.IPv4DefaultGateway) { $gw = $cfg.IPv4DefaultGateway.NextHop; $me = $cfg.IPv4Address.IPAddress }
  }
  if ($gw) {
    Log "on robot AP: me=$me robot=$gw"
    & $py -X utf8 -I (Join-Path $PSScriptRoot 'ap_probe.py') $gw $out
  } else {
    Log "no IP/gateway from robot AP within 30s"
    $cfg = Get-NetIPConfiguration -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue
    Log ("ip now: " + ($cfg.IPv4Address.IPAddress -join ','))
  }
} finally {
  Log "returning to $homeProfile"
  netsh wlan connect name="$homeProfile" | Out-Null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep 1
    if (Test-Connection 192.168.1.1 -Count 1 -Quiet -ErrorAction SilentlyContinue) { break }
  }
  netsh wlan delete profile name="$RobotSsid" | Out-Null
  Remove-Item $xmlPath -ErrorAction SilentlyContinue
  Log ("back home: " + (Test-Connection 192.168.1.1 -Count 1 -Quiet))
}
