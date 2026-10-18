# Install official Python 3.11 or newer when the player does not already have it.
param(
    [Parameter(Mandatory = $true)]
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Minimum = [version]"3.11"

function Test-StoreStub([string]$Path) {
    return $Path -match '\\WindowsApps\\'
}

function Get-PythonVersion([string]$Exe) {
    if (-not $Exe -or (Test-StoreStub $Exe) -or -not (Test-Path -LiteralPath $Exe)) {
        return $null
    }
    $raw = & $Exe -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        return $null
    }
    try {
        return [version](($raw | Select-Object -Last 1).ToString().Trim())
    } catch {
        return $null
    }
}

function Add-Candidate([System.Collections.Generic.List[string]]$Found, [string]$Exe) {
    if (-not $Exe -or (Test-StoreStub $Exe)) {
        return
    }
    if ((Test-Path -LiteralPath $Exe) -and -not $Found.Contains($Exe)) {
        $Found.Add($Exe)
    }
}

function Find-Python {
    $found = [System.Collections.Generic.List[string]]::new()
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher -and -not (Test-StoreStub $launcher.Source)) {
        $resolved = & $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            Add-Candidate $found (($resolved | Select-Object -Last 1).ToString().Trim())
        }
    }
    foreach ($name in @("python", "python3")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            Add-Candidate $found $command.Source
        }
    }
    foreach ($root in @(
            "$env:LocalAppData\Programs\Python",
            "$env:ProgramFiles",
            ${env:ProgramFiles(x86)}
        )) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) {
            continue
        }
        Get-ChildItem -LiteralPath $root -Directory -Filter "Python*" -ErrorAction SilentlyContinue | ForEach-Object {
            Add-Candidate $found (Join-Path $_.FullName "python.exe")
        }
    }
    $bestPath = $null
    $bestVersion = $null
    foreach ($exe in $found) {
        $version = Get-PythonVersion $exe
        if ($version -and $version -ge $Minimum -and (-not $bestVersion -or $version -gt $bestVersion)) {
            $bestPath = $exe
            $bestVersion = $version
        }
    }
    return $bestPath
}

function Get-Installer {
    $page = (Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/downloads/windows/" -Headers @{"User-Agent" = "civrev-link"}).Content
    $suffix = switch ($env:PROCESSOR_ARCHITECTURE) {
        "AMD64" { "amd64" }
        "ARM64" { "arm64" }
        "x86" { "" }
        default { throw "No Python installer for this processor ($env:PROCESSOR_ARCHITECTURE)." }
    }
    if ($suffix) {
        $pattern = "https://www\.python\.org/ftp/python/(\d+\.\d+\.\d+)/python-\1-$suffix\.exe"
    } else {
        $pattern = "https://www\.python\.org/ftp/python/(\d+\.\d+\.\d+)/python-\1\.exe"
    }
    $best = $null
    $bestUrl = $null
    foreach ($match in [regex]::Matches($page, $pattern)) {
        $version = [version]$match.Groups[1].Value
        if ($version -ge $Minimum -and (-not $best -or $version -gt $best)) {
            $best = $version
            $bestUrl = $match.Value
        }
    }
    if (-not $bestUrl) {
        throw "Could not find a Python 3.11 or newer Windows installer."
    }
    return @{ Version = $best; Url = $bestUrl }
}

function Install-Python {
    $chosen = Get-Installer
    $version = $chosen.Version
    $url = $chosen.Url
    $name = Split-Path $url -Leaf
    $installer = Join-Path $env:TEMP $name
    $log = Join-Path $env:TEMP "civrev-python-install.log"
    Write-Host "Installing Python $version."
    Invoke-WebRequest -UseBasicParsing -Uri $url -Headers @{"User-Agent" = "civrev-link"} -OutFile $installer
    $proc = Start-Process -FilePath $installer -ArgumentList @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=0",
        "Include_test=0",
        "/log",
        $log
    ) -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "The Python installer failed (exit $($proc.ExitCode)). See $log"
    }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$userPath;$machinePath"
    $direct = Join-Path $env:LocalAppData ("Programs\Python\Python{0}{1}\python.exe" -f $version.Major, $version.Minor)
    if (Test-Path -LiteralPath $direct) {
        return $direct
    }
    return Find-Python
}

$python = Find-Python
if (-not $python) {
    $python = Install-Python
}
if (-not $python) {
    throw "Python installed, but python.exe was not found."
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($OutFile, $python + "`n", $utf8)
