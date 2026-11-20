$ErrorActionPreference = 'Stop'

Add-Type -Namespace OmniAI -Name StartupConsole -MemberDefinition @'
[DllImport("kernel32.dll")]
public static extern IntPtr GetConsoleWindow();

[DllImport("user32.dll")]
public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
'@

$console = [OmniAI.StartupConsole]::GetConsoleWindow()
if (-not [OmniAI.StartupConsole]::ShowWindowAsync($console, 0)) {
    throw 'Unable to hide the WinPE startup console.'
}
