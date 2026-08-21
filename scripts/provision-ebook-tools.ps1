[CmdletBinding()]
param(
    [ValidateSet("Auto", "Native", "Wsl")]
    [string]$DockerBackend = "Auto",

    [string]$WslDistribution,

    [ValidatePattern("^[a-z0-9][a-z0-9._/-]*:[a-zA-Z0-9][a-zA-Z0-9._-]*$")]
    [string]$Image = "foliotone-ebook-tools:local"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$dockerMode = $null
$linuxRepoRoot = $null

function Test-NativeLinuxDocker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $false
    }
    $osType = & docker info --format '{{.OSType}}' 2>$null
    return $LASTEXITCODE -eq 0 -and $osType.Trim() -eq "linux"
}

function Test-WslLinuxDocker {
    param([Parameter(Mandatory)][string]$Distribution)

    $osType = & wsl.exe -d $Distribution -- docker info --format '{{.OSType}}' 2>$null
    return $LASTEXITCODE -eq 0 -and ($osType -replace "`0", "").Trim() -eq "linux"
}

function Find-WslDockerDistribution {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        return $null
    }
    if ($WslDistribution) {
        if (Test-WslLinuxDocker -Distribution $WslDistribution) {
            return $WslDistribution
        }
        throw "WSL distribution '$WslDistribution' has no reachable Linux Docker engine."
    }
    $distributions = & wsl.exe --list --quiet 2>$null
    foreach ($distribution in $distributions) {
        $name = ($distribution -replace "`0", "").Trim()
        if ($name -and (Test-WslLinuxDocker -Distribution $name)) {
            return $name
        }
    }
    return $null
}

function Invoke-ToolchainDocker {
    param([Parameter(ValueFromRemainingArguments)][string[]]$Arguments)

    if ($script:dockerMode -eq "Native") {
        & docker @Arguments
    }
    else {
        & wsl.exe -d $script:WslDistribution --cd $script:linuxRepoRoot -- docker @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

if ($DockerBackend -in @("Auto", "Native") -and (Test-NativeLinuxDocker)) {
    $dockerMode = "Native"
}
elseif ($DockerBackend -eq "Native") {
    throw "The active native Docker engine is not a Linux engine."
}
else {
    $WslDistribution = Find-WslDockerDistribution
    if (-not $WslDistribution) {
        throw "No reachable Linux Docker engine was found in WSL2."
    }
    $dockerMode = "Wsl"
    if ($repoRoot -notmatch "^(?<drive>[A-Za-z]):\\(?<tail>.+)$") {
        throw "The repository must use a local Windows drive for WSL provisioning."
    }
    $drive = $Matches.drive.ToLowerInvariant()
    $tail = $Matches.tail.Replace("\", "/")
    $linuxRepoRoot = "/mnt/$drive/$tail"
    & wsl.exe -d $WslDistribution -- test -d $linuxRepoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "The repository path is not mounted inside WSL: $linuxRepoRoot"
    }
}

Write-Host "Provisioning the locked E-book toolchain with $dockerMode Docker."
if ($dockerMode -eq "Wsl") {
    Write-Host "WSL distribution: $WslDistribution"
}

Invoke-ToolchainDocker build `
    --platform linux/amd64 `
    --file packaging/ebook-tools/Dockerfile `
    --tag $Image `
    .

Invoke-ToolchainDocker run `
    --rm `
    --network none `
    --read-only `
    --tmpfs /tmp `
    --cap-drop ALL `
    --security-opt no-new-privileges `
    $Image `
    ebook-tools-doctor

Write-Host "E-book toolchain image is ready: $Image"
