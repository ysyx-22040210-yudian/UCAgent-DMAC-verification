<#
.SYNOPSIS
Launch the native Tk application with a verified Python 3.8+ interpreter and no console window.
.PARAMETER Python
Python executable name or absolute path. No packages, PATH entries, or SSH credentials are changed.
#>
param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$desktopInterpreter = & $Python -c 'import sys, tkinter; assert sys.version_info >= (3, 8), "Python 3.8+ required"; print(sys.executable)'
if ($LASTEXITCODE -ne 0 -or -not $desktopInterpreter) {
    throw 'Select a Python 3.8+ interpreter with tkinter using -Python.'
}
$desktopInterpreter = $desktopInterpreter.Trim()
$desktopWindowed = Join-Path (Split-Path -Parent $desktopInterpreter) 'pythonw.exe'
if (Test-Path -LiteralPath $desktopWindowed -PathType Leaf) {
    $desktopInterpreter = $desktopWindowed
}
$desktopEntry = Join-Path $PSScriptRoot 'ucagent_app.pyw'
Start-Process -FilePath $desktopInterpreter -ArgumentList @('"' + $desktopEntry + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
