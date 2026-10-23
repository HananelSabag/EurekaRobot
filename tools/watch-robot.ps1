# Logs every 30s whether the robot (Midea MAC 80:76:C2:00:00:01) is on the LAN, its IP, and whether port 6444 answers.
param([int]$Minutes = 300, [string]$Log = "$PSScriptRoot\..\data\presence.log")
$mac = '80-76-C2-00-00-01'
$end = (Get-Date).AddMinutes($Minutes)
$last = ''
while ((Get-Date) -lt $end) {
  $jobs = 2..254 | ForEach-Object { [System.Net.NetworkInformation.Ping]::new().SendPingAsync("192.168.1.$_", 1500) }
  try { [System.Threading.Tasks.Task]::WaitAll($jobs) } catch {}
  $n = Get-NetNeighbor -AddressFamily IPv4 -IPAddress 192.168.1.* -ErrorAction SilentlyContinue |
    Where-Object { $_.LinkLayerAddress -eq $mac -and $_.State -in 'Reachable', 'Stale', 'Delay', 'Probe' } | Select-Object -First 1
  $state = 'offline'
  if ($n) {
    $c = New-Object System.Net.Sockets.TcpClient
    $ok = $c.ConnectAsync($n.IPAddress, 6444).Wait(1500) -and $c.Connected
    $c.Close()
    $state = "online $($n.IPAddress) 6444=$(if ($ok) { 'open' } else { 'closed' })"
  }
  if ($state -ne $last) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $state" | Add-Content -Path $Log -Encoding utf8; $last = $state }
  Start-Sleep -Seconds 30
}
