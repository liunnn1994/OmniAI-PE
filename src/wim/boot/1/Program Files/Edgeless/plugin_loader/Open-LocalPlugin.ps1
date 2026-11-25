param([Parameter(Mandatory = $true)][string]$Package)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
if (!$env:LOCALAPPDATA) {
    $env:LOCALAPPDATA = [Environment]::GetFolderPath('LocalApplicationData')
    if (!$env:LOCALAPPDATA) {
        $profile = $env:USERPROFILE
        if (!$profile) { $profile = Join-Path $env:SystemDrive 'Users\Default' }
        $env:LOCALAPPDATA = Join-Path $profile 'AppData\Local'
    }
}
$preference = Join-Path $env:LOCALAPPDATA 'OmniAI-PE\app-cache.txt'
$sha = [Security.Cryptography.SHA256]::Create()

function Get-Hash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try { [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose() }
}

function Assert-LocalDirectory([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $drive = [IO.Path]::GetPathRoot($full)
    if ($drive -notmatch '^[A-Z]:\\$' -or $drive.TrimEnd('\') -eq $env:SystemDrive) {
        throw '请选择有足够空间的本地可写盘。'
    }
    $item = Get-Item -LiteralPath $full -Force
    while ($item) {
        if ($item -isnot [IO.DirectoryInfo] -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "缓存目录或上级目录包含重定向路径。$full"
        }
        $item = $item.Parent
    }
}

function Test-PackageFiles([string]$Directory, [string]$IntegrityPath, $Files) {
    $remaining = @{}
    foreach ($property in $Files.PSObject.Properties) {
        $remaining[$property.Name] = $property.Value
    }
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($Directory)
    while ($pending.Count) {
        foreach ($item in Get-ChildItem -LiteralPath ($pending.Pop()) -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
            if ($item.PSIsContainer) {
                $pending.Push($item.FullName)
                continue
            }
            $name = $item.FullName.Substring($Directory.Length + 1).Replace('\', '/')
            if ($name -eq $IntegrityPath) { continue }
            if (!$remaining.ContainsKey($name) -or (Get-Hash $item.FullName) -ne $remaining[$name]) {
                return $false
            }
            $remaining.Remove($name)
        }
    }
    return ($remaining.Count -eq 0)
}

$mutex = New-Object Threading.Mutex($false, 'Local\OmniAI-PE-EdgelessCache')
$acquired = $false
try {
    $archive = Get-Item -LiteralPath $Package
    if ($archive.BaseName -notmatch '^([A-Za-z0-9]+)_[0-9.]+_OmniAI$' -or $archive.Extension -ne '.7zf') {
        throw 'Invalid Edgeless application package.'
    }
    $app = $Matches[1]
    $integrityPath = "$app/Edgeless-Integrity.json"
    $sevenZip = Join-Path $env:ProgramFiles '7-Zip\7z.exe'
    $record = & $sevenZip x -so -- $archive.FullName $integrityPath
    if ($LASTEXITCODE -or !$record) { throw "Cannot read the package integrity record. $app" }
    $record = $record | ConvertFrom-Json
    $key = (Get-Hash $archive.FullName).Substring(0, 16)

    try { $acquired = $mutex.WaitOne() }
    catch [Threading.AbandonedMutexException] { $acquired = $true }
    $selected = $null
    if (Test-Path -LiteralPath $preference -PathType Leaf) {
        $previous = (Get-Content -LiteralPath $preference -Raw -Encoding UTF8).Trim()
        if ($previous -and (Test-Path -LiteralPath $previous -PathType Container)) { $selected = $previous }
    }
    if (!$selected) {
        $picker = New-Object Windows.Forms.FolderBrowserDialog
        try {
            $picker.Description = "请选择 Edgeless 缓存目录。首次加载 $app 需要约 $([Math]::Ceiling($record.size / 1MB)) MiB。"
            $picker.ShowNewFolderButton = $false
            if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
            $selected = $picker.SelectedPath
        } finally { $picker.Dispose() }
    }
    Assert-LocalDirectory $selected
    $cache = Join-Path $selected 'OmniAI-PE-Edgeless'
    if (!(Test-Path -LiteralPath $cache)) { New-Item -ItemType Directory -Path $cache | Out-Null }
    Assert-LocalDirectory $cache
    $version = Join-Path $cache "$app-$key"
    $longest = ($record.files.PSObject.Properties | ForEach-Object { $_.Name.Length } | Measure-Object -Maximum).Maximum
    if ($version.Length + 1 + $longest -gt 259) { throw '缓存路径过长。请选择靠近盘符根目录的位置。' }
    $valid = $false
    if (Test-Path -LiteralPath $version) {
        Assert-LocalDirectory $version
        $valid = Test-PackageFiles $version $integrityPath $record.files
    }
    if (!$valid) {
        $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($cache))
        if ($drive.AvailableFreeSpace -lt ([long]$record.size + 64MB)) {
            throw '空间不足。请选择另一个可写盘。'
        }
        $token = [Guid]::NewGuid().ToString('N').Substring(0, 16)
        $pendingPath = Join-Path $cache ".$token"
        New-Item -ItemType Directory -Path $pendingPath | Out-Null
        try {
            & $sevenZip x -y -bsp1 "-o$pendingPath" -- $archive.FullName
            if ($LASTEXITCODE -or !(Test-PackageFiles $pendingPath $integrityPath $record.files)) {
                throw "Edgeless 插件解包或校验失败。$app"
            }
            if (Test-Path -LiteralPath $version) { [IO.Directory]::Move($version, "$version.previous-$token") }
            [IO.Directory]::Move($pendingPath, $version)
        } finally {
            if (Test-Path -LiteralPath $pendingPath) {
                Assert-LocalDirectory $pendingPath
                Remove-Item -LiteralPath $pendingPath -Recurse -Force
            }
        }
    }
    New-Item -ItemType Directory -Path (Split-Path $preference) -Force | Out-Null
    Set-Content -LiteralPath $preference -Value $selected -Encoding UTF8
    & (Join-Path $version "Install-$app.cmd")
    if ($LASTEXITCODE) { throw "Edgeless 插件启动失败。$app" }
} catch {
    Remove-Item -LiteralPath $preference -ErrorAction SilentlyContinue
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Edgeless')
    exit 1
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    $sha.Dispose()
}
