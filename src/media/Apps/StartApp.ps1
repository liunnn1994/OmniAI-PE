param([Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9]+$')][string]$AppName)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$packages = Join-Path (Split-Path $PSScriptRoot) 'AppPackages'
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

function Test-PackageFiles([string]$Directory, $Files) {
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
            if (!$remaining.ContainsKey($name) -or (Get-Hash $item.FullName) -ne $remaining[$name]) {
                return $false
            }
            $remaining.Remove($name)
        }
    }
    return ($remaining.Count -eq 0)
}

$mutex = New-Object Threading.Mutex($false, 'Local\OmniAI-PE-AppCache')
$acquired = $false
try {
    try { $acquired = $mutex.WaitOne() }
    catch [Threading.AbandonedMutexException] { $acquired = $true }
    $app = Get-Content -LiteralPath (Join-Path $packages "$AppName.json") -Raw -Encoding UTF8 | ConvertFrom-Json

    $selected = $null
    if (Test-Path -LiteralPath $preference -PathType Leaf) {
        $previous = (Get-Content -LiteralPath $preference -Raw -Encoding UTF8).Trim()
        if ($previous -and (Test-Path -LiteralPath $previous -PathType Container)) { $selected = $previous }
    }
    if (!$selected) {
        $picker = New-Object Windows.Forms.FolderBrowserDialog
        try {
            $picker.Description = "请选择应用缓存目录。首次启动 $AppName 需要解包约 $([math]::Ceiling($app.size / 1MB)) MiB。"
            $picker.ShowNewFolderButton = $false
            if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
            $selected = $picker.SelectedPath
        } finally { $picker.Dispose() }
    }
    Assert-LocalDirectory $selected
    $cache = Join-Path $selected 'OmniAI-PE-AppCache'
    if (!(Test-Path -LiteralPath $cache)) { New-Item -ItemType Directory -Path $cache | Out-Null }
    Assert-LocalDirectory $cache
    $version = Join-Path $cache "$AppName-$($app.version.Substring(0, 16))"
    $longest = ($app.files.PSObject.Properties | ForEach-Object { $_.Name.Length } | Measure-Object -Maximum).Maximum
    if (($version.Length + 1 + $longest) -gt 259) {
        throw "路径过长。请为 $AppName 选择更靠近盘符根目录的位置。"
    }
    $valid = $false
    if (Test-Path -LiteralPath $version) {
        Assert-LocalDirectory $version
        $valid = Test-PackageFiles $version $app.files
    }

    if (!$valid) {
        $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($cache))
        if ($drive.AvailableFreeSpace -lt ([long]$app.size + 64MB)) {
            throw "空间不足。请为 $AppName 选择另一个可写盘。"
        }
        $archive = Join-Path $packages $app.archive
        if ((Get-Hash $archive) -ne $app.sha256) { throw "应用包校验失败。$AppName" }
        $token = [Guid]::NewGuid().ToString('N')
        $pendingPath = Join-Path $cache ".$($token.Substring(0, 16))"
        New-Item -ItemType Directory -Path $pendingPath | Out-Null
        try {
            $destination = $pendingPath
            if ($app.subdirectory) { $destination = Join-Path $destination $app.subdirectory }
            Write-Host "正在展开 $AppName ..."
            $sevenZip = Join-Path $env:ProgramFiles '7-Zip\7z.exe'
            & $sevenZip x -y -bsp1 "-o$destination" -- $archive
            if ($LASTEXITCODE -ne 0) { throw "应用解包失败。$AppName" }
            $overlay = Join-Path $PSScriptRoot $AppName
            if (Test-Path -LiteralPath $overlay -PathType Container) {
                Get-ChildItem -LiteralPath $overlay -Force |
                    Copy-Item -Destination $pendingPath -Recurse -Force
            }
            if (!(Test-PackageFiles $pendingPath $app.files)) { throw "应用文件校验失败。$AppName" }
            if (Test-Path -LiteralPath $version) {
                [IO.Directory]::Move($version, "$version.previous-$token")
            }
            [IO.Directory]::Move($pendingPath, $version)
        } finally {
            if (Test-Path -LiteralPath $pendingPath -PathType Container) {
                Assert-LocalDirectory $pendingPath
                Remove-Item -LiteralPath $pendingPath -Recurse -Force
            }
        }
    }

    New-Item -ItemType Directory -Path (Split-Path $preference) -Force | Out-Null
    Set-Content -LiteralPath $preference -Value $selected -Encoding UTF8
    $entry = Join-Path $version $app.entry
    $launch = @{ FilePath = $entry; WorkingDirectory = (Split-Path $entry) }
    if ($app.arguments) { $launch.ArgumentList = $app.arguments }
    Start-Process @launch
} catch {
    Remove-Item -LiteralPath $preference -ErrorAction SilentlyContinue
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, "$AppName - OmniAI PE")
    exit 1
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    $sha.Dispose()
}
