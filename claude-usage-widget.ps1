# Claude Usage Widget - 常時最前面の使用量モニター
# 起動: powershell -ExecutionPolicy Bypass -File claude-usage-widget.ps1
# 前提: Claude Code がログイン済み (%USERPROFILE%\.claude\.credentials.json が存在)

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase

$CredPath   = Join-Path $env:USERPROFILE ".claude\.credentials.json"
$ProjectsDir = Join-Path $env:USERPROFILE ".claude\projects"
$PollSec    = 120   # usage API のポーリング間隔 (429対策で短くしない)

# モデル別価格 (USD / MTok): input, output, cache_read, cache_write
$Prices = @{
  opus   = @(15.0, 75.0, 1.5, 18.75)
  sonnet = @(3.0, 15.0, 0.3, 3.75)
  haiku  = @(1.0, 5.0, 0.1, 1.25)
}

function Get-AccessToken {
  if (-not (Test-Path $CredPath)) { return $null }
  $cred = (Get-Content $CredPath -Raw | ConvertFrom-Json).claudeAiOauth
  if (-not $cred) { return $null }
  $expMs = [double]$cred.expiresAt
  $nowMs = [double][DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  if ($nowMs -lt ($expMs - 300000)) { return $cred.accessToken }
  # 期限切れ → リフレッシュ
  try {
    $body = @{ grant_type='refresh_token'; refresh_token=$cred.refreshToken;
               client_id='9d1c250a-e61b-44d9-88ed-5944d1962f5e' } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri 'https://console.anthropic.com/v1/oauth/token' `
          -Method Post -ContentType 'application/json' -Body $body
    $all = Get-Content $CredPath -Raw | ConvertFrom-Json
    $all.claudeAiOauth.accessToken  = $r.access_token
    $all.claudeAiOauth.refreshToken = $r.refresh_token
    $all.claudeAiOauth.expiresAt    = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() + ($r.expires_in * 1000)
    $all | ConvertTo-Json -Depth 10 | Set-Content $CredPath -Encoding UTF8
    return $r.access_token
  } catch { return $null }
}

function Get-PlanUsage {
  $tok = Get-AccessToken
  if (-not $tok) { return $null }
  try {
    return Invoke-RestMethod -Uri 'https://api.anthropic.com/api/oauth/usage' -Headers @{
      Authorization    = "Bearer $tok"
      'anthropic-beta' = 'oauth-2025-04-20'
      'User-Agent'     = 'claude-code/2.0.0'
    }
  } catch { return $null }
}

function Get-TodayLocalUsage {
  $sum = @{ in=0L; out=0L; cr=0L; cw=0L; cost=0.0 }
  if (-not (Test-Path $ProjectsDir)) { return $sum }
  $today = (Get-Date).Date
  $files = Get-ChildItem $ProjectsDir -Recurse -Filter *.jsonl -ErrorAction SilentlyContinue |
           Where-Object { $_.LastWriteTime -ge $today }
  foreach ($f in $files) {
    foreach ($line in [IO.File]::ReadLines($f.FullName)) {
      if ($line -notmatch '"usage"') { continue }
      try { $j = $line | ConvertFrom-Json } catch { continue }
      $u = $j.message.usage; if (-not $u) { continue }
      $ts = $null
      if ($j.timestamp) { try { $ts = ([DateTime]$j.timestamp).ToLocalTime() } catch {} }
      if ($ts -and $ts.Date -ne $today) { continue }
      $m = "$($j.message.model)"
      $p = if ($m -match 'opus') { $Prices.opus } elseif ($m -match 'haiku') { $Prices.haiku } else { $Prices.sonnet }
      $i  = [long]($u.input_tokens); $o = [long]($u.output_tokens)
      $cr = [long]($u.cache_read_input_tokens); $cw = [long]($u.cache_creation_input_tokens)
      $sum.in += $i; $sum.out += $o; $sum.cr += $cr; $sum.cw += $cw
      $sum.cost += ($i*$p[0] + $o*$p[1] + $cr*$p[2] + $cw*$p[3]) / 1e6
    }
  }
  return $sum
}

function Fmt-Reset($iso) {
  if (-not $iso) { return '' }
  try {
    $t = ([DateTime]$iso).ToLocalTime()
    return 'リセット ' + $t.ToString('M/d HH:mm')
  } catch { return '' }
}

# ---------- UI ----------
[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Claude Usage" Width="230" SizeToContent="Height"
        Topmost="True" WindowStyle="None" ResizeMode="NoResize"
        AllowsTransparency="True" Background="Transparent" ShowInTaskbar="True">
  <Border Background="#EE1F1E1D" CornerRadius="10" Padding="12">
    <StackPanel>
      <DockPanel>
        <TextBlock Text="Claude 使用量" Foreground="#D97757" FontWeight="Bold" FontSize="13"/>
        <TextBlock Name="BtnClose" Text="✕" Foreground="#888" HorizontalAlignment="Right"
                   DockPanel.Dock="Right" Cursor="Hand" Padding="6,0,0,0"/>
      </DockPanel>
      <TextBlock Name="T5h" Foreground="#EEE" FontSize="20" FontWeight="Bold" Margin="0,8,0,0" Text="--%"/>
      <ProgressBar Name="P5h" Height="6" Maximum="100" Foreground="#D97757" Background="#333" BorderThickness="0"/>
      <TextBlock Name="R5h" Foreground="#999" FontSize="10" Margin="0,2,0,6"/>
      <TextBlock Name="T7d" Foreground="#CCC" FontSize="12" Text="週間: --%"/>
      <ProgressBar Name="P7d" Height="4" Maximum="100" Foreground="#7A9E7E" Background="#333" BorderThickness="0"/>
      <TextBlock Name="R7d" Foreground="#999" FontSize="10" Margin="0,2,0,6"/>
      <Separator Background="#333"/>
      <TextBlock Name="TTok" Foreground="#CCC" FontSize="11" Margin="0,4,0,0" Text="本日: -"/>
      <TextBlock Name="TCost" Foreground="#CCC" FontSize="11" Text=""/>
      <TextBlock Name="TStat" Foreground="#666" FontSize="9" Margin="0,4,0,0"/>
    </StackPanel>
  </Border>
</Window>
"@

$win = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $xaml))
$ui = @{}
'T5h','P5h','R5h','T7d','P7d','R7d','TTok','TCost','TStat','BtnClose' | ForEach-Object { $ui[$_] = $win.FindName($_) }
$win.Add_MouseLeftButtonDown({ $win.DragMove() })
$ui.BtnClose.Add_MouseLeftButtonUp({ $win.Close() })
# 右下に初期配置
$wa = [System.Windows.SystemParameters]::WorkArea
$win.Left = $wa.Right - 250; $win.Top = $wa.Bottom - 260

function Refresh {
  $u = Get-PlanUsage
  if ($u) {
    $fh = $u.five_hour; $sd = $u.seven_day
    if ($fh) {
      $ui.T5h.Text = ('{0:N0}%' -f [double]$fh.utilization)
      $ui.P5h.Value = [math]::Min(100, [double]$fh.utilization)
      $ui.R5h.Text = '5時間枠 / ' + (Fmt-Reset $fh.resets_at)
    }
    if ($sd) {
      $ui.T7d.Text = ('週間: {0:N0}%' -f [double]$sd.utilization)
      $ui.P7d.Value = [math]::Min(100, [double]$sd.utilization)
      $ui.R7d.Text = Fmt-Reset $sd.resets_at
    }
    $ui.TStat.Text = '更新 ' + (Get-Date -Format 'HH:mm:ss')
  } else {
    $ui.TStat.Text = 'プラン使用率を取得できません (' + (Get-Date -Format 'HH:mm:ss') + ')'
  }
  $l = Get-TodayLocalUsage
  $tot = $l.in + $l.out + $l.cr + $l.cw
  $ui.TTok.Text  = '本日トークン: ' + ('{0:N1}M' -f ($tot/1e6))
  $ui.TCost.Text = '概算コスト: ${0:N2}' -f $l.cost
}

$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromSeconds($PollSec)
$timer.Add_Tick({ Refresh })
$timer.Start()
$win.Add_Loaded({ Refresh })
[void]$win.ShowDialog()
