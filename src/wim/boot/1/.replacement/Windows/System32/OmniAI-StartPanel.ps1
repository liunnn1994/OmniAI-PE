$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

$ownsPanel = $false
$instance = [Threading.Mutex]::new($true, 'Local\OmniAIPE.StartPanel', [ref]$ownsPanel)
if (-not $ownsPanel) {
    $instance.Dispose()
    return
}

$programs = 'Microsoft\Windows\Start Menu\Programs'
$roots = (Join-Path $env:APPDATA $programs), (Join-Path $env:ProgramData $programs)
$shortcuts = @{}
foreach ($root in $roots) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
    foreach ($link in Get-ChildItem -LiteralPath $root -Recurse -File) {
        if ($link.Extension -notin '.lnk', '.url') { continue }
        $relative = $link.FullName.Substring($root.Length + 1)
        if ($shortcuts.ContainsKey($relative)) { continue }
        $category = Split-Path -Parent $relative
        if (-not $category) { $category = '其他工具' }
        $shortcuts[$relative] = [pscustomobject]@{
            Name = $link.BaseName
            Category = $category
            Path = $link.FullName
        }
    }
}
$tools = @($shortcuts.Values | Sort-Object Name, Category)
$pinsPath = Join-Path $env:LOCALAPPDATA 'OmniAI PE\pinned-tools.txt'
$pins = @{}
if (Test-Path -LiteralPath $pinsPath) {
    foreach ($path in Get-Content -LiteralPath $pinsPath -Encoding UTF8) { $pins[$path] = $true }
}

$form = New-Object Windows.Forms.Form
$form.Text = 'OmniAI PE 工具'
$form.FormBorderStyle = 'None'
$form.ClientSize = New-Object Drawing.Size(664, 484)
$form.StartPosition = 'Manual'
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.KeyPreview = $true
$form.AutoScaleMode = 'Dpi'
$form.BackColor = [Drawing.Color]::FromArgb(243, 247, 251)
$form.ForeColor = [Drawing.Color]::FromArgb(25, 43, 65)
$form.Font = New-Object Drawing.Font('Microsoft YaHei UI', 10)

function Add-Control($type, $label, $x, $y, $width, $height) {
    $control = New-Object "Windows.Forms.$type"
    $control.Text = $label
    $control.SetBounds($x, $y, $width, $height)
    $form.Controls.Add($control)
    return $control
}

$title = Add-Control Label 'OmniAI PE 工具' 22 16 400 34
$title.Font = New-Object Drawing.Font('Microsoft YaHei UI', 17, [Drawing.FontStyle]::Bold)
$close = Add-Control Button '关闭' 566 16 76 34
$close.Add_Click({ $form.Close() })
$null = Add-Control Label '搜索工具' 22 61 80 25
$search = Add-Control TextBox '' 104 58 538 28
$search.AccessibleName = '搜索工具'

$categories = Add-Control ListBox '' 22 100 168 320
$categories.AccessibleName = '工具分类'
$categories.BorderStyle = 'None'
$categories.IntegralHeight = $false
$categories.ItemHeight = 26
$null = $categories.Items.Add('全部工具')
$null = $categories.Items.Add('常用工具')
foreach ($group in ($tools.Category | Where-Object { $_ } | Sort-Object -Unique)) {
    $null = $categories.Items.Add($group)
}

$results = Add-Control ListBox '' 202 100 440 320
$results.AccessibleName = '搜索结果'
$results.BorderStyle = 'None'
$results.IntegralHeight = $false
$results.DisplayMember = 'Name'
$results.HorizontalScrollbar = $true

$status = Add-Control Label '' 22 436 160 30
$status.TextAlign = 'MiddleLeft'
$pin = Add-Control Button '固定到常用' 190 434 102 34
$open = Add-Control Button '打开' 300 434 76 34
$files = Add-Control Button '文件管理器' 384 434 100 34
$run = Add-Control Button '运行' 492 434 68 34
$power = Add-Control Button '电源' 568 434 74 34
foreach ($button in $close, $pin, $open, $files, $run, $power) {
    $button.FlatStyle = 'Flat'
    $button.FlatAppearance.BorderSize = 0
    $button.BackColor = [Drawing.Color]::White
}
$open.BackColor = [Drawing.Color]::FromArgb(24, 87, 156)
$open.ForeColor = [Drawing.Color]::White
$form.AcceptButton = $open

$updateButtons = {
    $selected = $results.SelectedItem
    $open.Enabled = $pin.Enabled = ($null -ne $selected)
    $pin.Text = if ($selected -and $pins.ContainsKey($selected.Path)) { '取消固定' } else { '固定到常用' }
}

$refresh = {
    $query = $search.Text.Trim()
    $selected = $results.SelectedItem
    $results.BeginUpdate()
    try {
        $results.Items.Clear()
        foreach ($tool in $tools) {
            if ($query) {
                if (("$($tool.Name) $($tool.Category)").IndexOf($query, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
            } elseif ($categories.SelectedIndex -eq 1) {
                if (-not $pins.ContainsKey($tool.Path)) { continue }
            } elseif ($categories.SelectedIndex -gt 1 -and $tool.Category -ne $categories.SelectedItem) {
                continue
            }
            $i = $results.Items.Add($tool)
            if ($selected -and $tool.Path -eq $selected.Path) { $results.SelectedIndex = $i }
        }
        if ($results.SelectedIndex -lt 0 -and $results.Items.Count) { $results.SelectedIndex = 0 }
    } finally {
        $results.EndUpdate()
    }
    $status.Text = if ($results.Items.Count) { "$($results.Items.Count) 项工具" } else { '没有匹配的工具' }
    & $updateButtons
}

function Open-Tool($path) {
    try {
        Start-Process -FilePath $path -ErrorAction Stop
        $form.Close()
    } catch {
        [void][Windows.Forms.MessageBox]::Show($form, $_.Exception.Message, '无法打开工具')
    }
}

$openSelected = { if ($results.SelectedItem) { Open-Tool $results.SelectedItem.Path } }
$open.Add_Click($openSelected)
$results.Add_DoubleClick($openSelected)
$results.Add_SelectedIndexChanged($updateButtons)
$search.Add_TextChanged($refresh)
$categories.Add_SelectedIndexChanged({
    if ($search.Text) { $search.Clear() } else { & $refresh }
})
$pin.Add_Click({
    $path = $results.SelectedItem.Path
    $wasPinned = $pins.ContainsKey($path)
    if ($wasPinned) { $pins.Remove($path) } else { $pins[$path] = $true }
    try {
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $pinsPath) -Force
        Set-Content -LiteralPath $pinsPath -Value @($pins.Keys | Sort-Object) -Encoding UTF8
    } catch {
        if ($wasPinned) { $pins[$path] = $true } else { $pins.Remove($path) }
        [void][Windows.Forms.MessageBox]::Show($form, $_.Exception.Message, '无法保存常用工具')
    }
    & $refresh
})
$files.Add_Click({ Open-Tool (Join-Path $env:ProgramFiles 'Explorer++\Explorer++.exe') })
$run.Add_Click({ (New-Object -ComObject Shell.Application).FileRun(); $form.Close() })
$powerMenu = New-Object Windows.Forms.ContextMenuStrip
foreach ($action in @(@('重新启动', 'Reboot'), @('关机', 'Shutdown'))) {
    $item = $powerMenu.Items.Add($action[0])
    $item.Tag = $action[1]
    $item.Add_Click({
        param($sender)
        if ([Windows.Forms.MessageBox]::Show($form, "确定要$($sender.Text)？", '电源', 'YesNo') -eq 'Yes') {
            Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\wpeutil.exe') -ArgumentList $sender.Tag
            $form.Close()
        }
    })
}
$power.Add_Click({ $powerMenu.Show($power, 0, $power.Height) })
$form.Add_KeyDown({
    param($sender, $eventArgs)
    if ($eventArgs.KeyCode -eq 'Escape') { $form.Close() }
    if ($eventArgs.KeyCode -eq 'Down' -and $search.Focused -and $results.Items.Count) {
        $eventArgs.SuppressKeyPress = $true
        $results.Focus()
    }
})
$form.Add_Shown({
    $work = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $form.Location = New-Object Drawing.Point(($work.Left + 12), ($work.Bottom - $form.Height - 12))
    $search.Focus()
})
$categories.SelectedIndex = 0
try {
    [void]$form.ShowDialog()
} finally {
    $form.Dispose()
    $instance.ReleaseMutex()
    $instance.Dispose()
}
