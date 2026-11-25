    $webView = Get-ChildItem (Join-Path $env:ProgramFiles 'WebView2') -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'msedgewebview2.exe') -PathType Leaf } |
        Select-Object -First 1
    if (!$webView) { throw '找不到内置的 WebView2 运行时。' }
    $key = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\ClientState\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    if (!(Test-Path -LiteralPath $key)) { New-Item -Path $key -Force | Out-Null }
    Set-ItemProperty -LiteralPath $key -Name EBWebView -Value $webView.FullName
    $env:WEBVIEW2_BROWSER_EXECUTABLE_FOLDER = $webView.FullName
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = '--allow-run-as-system --disable-direct-composition'
    if ((Split-Path -Leaf $entry) -eq 'cc-switch.exe') {
        # Tauri's WebView2 startup in WinPE requires these arguments through the application policy.
        $policy = 'HKLM:\SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments'
        if (!(Test-Path -LiteralPath $policy)) { New-Item -Path $policy -Force | Out-Null }
        Set-ItemProperty -LiteralPath $policy -Name (Split-Path -Leaf $entry) -Value $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
    }
