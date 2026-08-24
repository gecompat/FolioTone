[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('init', 'new', 'register', 'resolve', 'validate')]
    [string]$Operation,

    [string]$RegistryPath = '.ai/identity/registry.json',
    [string]$ArtifactPath,

    [ValidateSet('DIRECT', 'DEFERRED')]
    [string]$Mode = 'DIRECT',

    [string]$Kind,
    [string]$Title,
    [string]$Uid,
    [string]$HumanRef,
    [Nullable[int]]$ExpectedRegistryRevision
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RegistryProfile = 'foundation-artifact-registry/v1'

function New-DefaultPrefixes {
    return [ordered]@{
        CAP  = [ordered]@{ kind = 'capability';       next_sequence = 1; width = 4 }
        REQ  = [ordered]@{ kind = 'requirement';      next_sequence = 1; width = 4 }
        WI   = [ordered]@{ kind = 'work_item';        next_sequence = 1; width = 4 }
        DEC  = [ordered]@{ kind = 'decision';         next_sequence = 1; width = 4 }
        GATE = [ordered]@{ kind = 'gate';             next_sequence = 1; width = 4 }
        RISK = [ordered]@{ kind = 'risk';             next_sequence = 1; width = 4 }
        EXP  = [ordered]@{ kind = 'experiment';       next_sequence = 1; width = 4 }
        OPS  = [ordered]@{ kind = 'operational_work'; next_sequence = 1; width = 4 }
        INC  = [ordered]@{ kind = 'incident';         next_sequence = 1; width = 4 }
        REL  = [ordered]@{ kind = 'release';          next_sequence = 1; width = 4 }
        TEST = [ordered]@{ kind = 'test';             next_sequence = 1; width = 4 }
    }
}

function New-InitialRegistry {
    return [ordered]@{
        schema_version     = 1
        profile            = $RegistryProfile
        registry_revision  = 0
        prefixes           = New-DefaultPrefixes
        allocations        = [ordered]@{}
    }
}

function New-Uuid7Urn {
    [Int64]$milliseconds = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    [byte[]]$bytes = New-Object byte[] 16
    for ($index = 5; $index -ge 0; $index--) {
        $bytes[$index] = [byte]($milliseconds -band 0xff)
        $milliseconds = $milliseconds -shr 8
    }

    [byte[]]$random = New-Object byte[] 10
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($random)
    [Array]::Copy($random, 0, $bytes, 6, 10)
    $bytes[6] = [byte](($bytes[6] -band 0x0f) -bor 0x70)
    $bytes[8] = [byte](($bytes[8] -band 0x3f) -bor 0x80)

    $hex = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
    $uuid = '{0}-{1}-{2}-{3}-{4}' -f $hex.Substring(0, 8), $hex.Substring(8, 4), $hex.Substring(12, 4), $hex.Substring(16, 4), $hex.Substring(20, 12)
    return "urn:uuid:$uuid"
}

function Normalize-Uid([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        $Value = New-Uuid7Urn
    }
    if ($Value -notmatch '^urn:uuid:([0-9a-fA-F-]{36})$') {
        throw 'artifact UID must use urn:uuid:<uuid>'
    }
    $guidText = $Matches[1].ToLowerInvariant()
    [Guid]$parsed = [Guid]::Empty
    if (-not [Guid]::TryParse($guidText, [ref]$parsed)) {
        throw 'artifact UID is not a valid UUID'
    }
    $versionNibble = $guidText.Substring(14, 1)
    if ($versionNibble -notin @('4', '7')) {
        throw 'Foundation reference client accepts UUIDv4 or UUIDv7 artifact UIDs'
    }
    return "urn:uuid:$guidText"
}

function Read-JsonHashtable([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "file not found: $Path"
    }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable)
}

function Write-JsonAtomic([string]$Path, $Value) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    $directory = [IO.Path]::GetDirectoryName($fullPath)
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $temp = Join-Path $directory ('.' + [IO.Path]::GetFileName($fullPath) + '.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $json = $Value | ConvertTo-Json -Depth 30
        [IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temp, $fullPath, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force
        }
    }
}

function Use-RegistryLock([string]$Path, [scriptblock]$Action) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    $directory = [IO.Path]::GetDirectoryName($fullPath)
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $lockPath = $fullPath + '.lock'
    $stream = $null
    try {
        $stream = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
        $writer.WriteLine("pid=$PID")
        $writer.Flush()
        $writer.Dispose()
        $stream = $null
        return (& $Action)
    }
    catch [IO.IOException] {
        if (Test-Path -LiteralPath $lockPath) {
            throw "registry lock already exists: $lockPath"
        }
        throw
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if (Test-Path -LiteralPath $lockPath) {
            Remove-Item -LiteralPath $lockPath -Force
        }
    }
}

function Assert-Registry([hashtable]$Registry) {
    if ($Registry.schema_version -ne 1 -or $Registry.profile -ne $RegistryProfile) {
        throw 'unsupported registry schema/profile'
    }
    if ([int]$Registry.registry_revision -lt 0) {
        throw 'registry_revision must be a non-negative integer'
    }
    if ($Registry.prefixes.Count -lt 1) {
        throw 'registry prefixes must be non-empty'
    }

    $kinds = @{}
    foreach ($prefix in $Registry.prefixes.Keys) {
        if ($prefix -notmatch '^[A-Z][A-Z0-9_]*$') {
            throw "invalid prefix registry entry: $prefix"
        }
        $row = $Registry.prefixes[$prefix]
        $kindValue = [string]$row.kind
        if ([string]::IsNullOrWhiteSpace($kindValue) -or $kinds.ContainsKey($kindValue)) {
            throw "prefix kind must be unique and non-empty: $prefix"
        }
        $kinds[$kindValue] = $true
        if ([int]$row.next_sequence -lt 1 -or [int]$row.width -lt 1) {
            throw "invalid allocation state for $prefix"
        }
    }

    $uids = @{}
    foreach ($ref in $Registry.allocations.Keys) {
        if ($ref -notmatch '^[A-Z][A-Z0-9_]*-[0-9]+$') {
            throw "invalid allocated human reference: $ref"
        }
        $normalized = Normalize-Uid ([string]$Registry.allocations[$ref])
        if ($uids.ContainsKey($normalized)) {
            throw "artifact UID has multiple final human references: $normalized"
        }
        $uids[$normalized] = $true
    }
}

function Assert-ExpectedRevision([hashtable]$Registry) {
    if ($null -ne $ExpectedRegistryRevision -and [int]$Registry.registry_revision -ne [int]$ExpectedRegistryRevision) {
        throw "stale registry revision: expected $ExpectedRegistryRevision, actual $($Registry.registry_revision)"
    }
}

function Get-PrefixForKind([hashtable]$Registry, [string]$KindValue) {
    $matches = @($Registry.prefixes.Keys | Where-Object { $Registry.prefixes[$_].kind -eq $KindValue })
    if ($matches.Count -ne 1) {
        throw "kind must resolve to exactly one prefix: $KindValue"
    }
    return [string]$matches[0]
}

function Add-Allocation([hashtable]$Registry, [string]$KindValue, [string]$ArtifactUid) {
    $prefix = Get-PrefixForKind $Registry $KindValue
    $row = $Registry.prefixes[$prefix]
    $sequence = [int]$row.next_sequence
    $width = [Math]::Max([int]$row.width, $sequence.ToString().Length)
    $ref = $prefix + '-' + $sequence.ToString('D' + $width)
    if ($Registry.allocations.ContainsKey($ref)) {
        throw "allocation collision: $ref"
    }
    foreach ($existingRef in $Registry.allocations.Keys) {
        if ($Registry.allocations[$existingRef] -eq $ArtifactUid) {
            throw "artifact UID already registered as $existingRef"
        }
    }
    $Registry.allocations[$ref] = $ArtifactUid
    $row.next_sequence = $sequence + 1
    $Registry.registry_revision = [int]$Registry.registry_revision + 1
    return $ref
}

function New-ArtifactRecord([string]$ArtifactUid, [AllowNull()]$Ref, [string]$KindValue, [string]$TitleValue) {
    $isRegistered = $null -ne $Ref -and -not [string]::IsNullOrWhiteSpace([string]$Ref)
    return [ordered]@{
        schema_version     = 1
        artifact_uid       = $ArtifactUid
        human_ref          = $Ref
        kind               = $KindValue
        title              = $TitleValue
        registration_state = $(if ($isRegistered) { 'REGISTERED' } else { 'DRAFT' })
        aliases            = @()
        external_refs      = @()
        relations          = @()
    }
}

function Write-Result($Value) {
    $Value | ConvertTo-Json -Depth 30
}

try {
    switch ($Operation) {
        'init' {
            $result = Use-RegistryLock $RegistryPath {
                if (Test-Path -LiteralPath $RegistryPath) {
                    throw "registry already exists: $RegistryPath"
                }
                $registry = New-InitialRegistry
                Write-JsonAtomic $RegistryPath $registry
                return $registry
            }
            Write-Result $result
        }

        'new' {
            if ([string]::IsNullOrWhiteSpace($Kind) -or [string]::IsNullOrWhiteSpace($Title)) {
                throw 'new requires -Kind and -Title'
            }
            $artifactUid = Normalize-Uid $Uid
            if ($Mode -eq 'DEFERRED') {
                $registry = Read-JsonHashtable $RegistryPath
                Assert-Registry $registry
                [void](Get-PrefixForKind $registry $Kind)
                $artifact = New-ArtifactRecord $artifactUid $null $Kind $Title
            }
            else {
                $artifact = Use-RegistryLock $RegistryPath {
                    $registry = Read-JsonHashtable $RegistryPath
                    Assert-Registry $registry
                    Assert-ExpectedRevision $registry
                    $ref = Add-Allocation $registry $Kind $artifactUid
                    Write-JsonAtomic $RegistryPath $registry
                    return (New-ArtifactRecord $artifactUid $ref $Kind $Title)
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($ArtifactPath)) {
                Write-JsonAtomic $ArtifactPath $artifact
            }
            Write-Result $artifact
        }

        'register' {
            if ([string]::IsNullOrWhiteSpace($ArtifactPath)) {
                throw 'register requires -ArtifactPath'
            }
            $artifact = Read-JsonHashtable $ArtifactPath
            $artifactUid = Normalize-Uid ([string]$artifact.artifact_uid)
            $kindValue = [string]$artifact.kind
            if ([string]::IsNullOrWhiteSpace($kindValue)) {
                throw 'artifact kind is required'
            }

            $artifact = Use-RegistryLock $RegistryPath {
                $registry = Read-JsonHashtable $RegistryPath
                Assert-Registry $registry
                Assert-ExpectedRevision $registry
                if (-not [string]::IsNullOrWhiteSpace([string]$artifact.human_ref)) {
                    if ($registry.allocations[[string]$artifact.human_ref] -ne $artifactUid) {
                        throw 'artifact human_ref is not registered to its UID'
                    }
                    return $artifact
                }

                $recovered = $null
                foreach ($existingRef in $registry.allocations.Keys) {
                    if ($registry.allocations[$existingRef] -eq $artifactUid) {
                        $recovered = $existingRef
                        break
                    }
                }
                if ($null -eq $recovered) {
                    $recovered = Add-Allocation $registry $kindValue $artifactUid
                    Write-JsonAtomic $RegistryPath $registry
                }
                $artifact.human_ref = $recovered
                $artifact.registration_state = 'REGISTERED'
                return $artifact
            }
            Write-JsonAtomic $ArtifactPath $artifact
            Write-Result $artifact
        }

        'resolve' {
            if ([string]::IsNullOrWhiteSpace($HumanRef)) {
                throw 'resolve requires -HumanRef'
            }
            $registry = Read-JsonHashtable $RegistryPath
            Assert-Registry $registry
            if (-not $registry.allocations.ContainsKey($HumanRef)) {
                throw "human reference is not registered: $HumanRef"
            }
            Write-Result ([ordered]@{ schema_version = 1; human_ref = $HumanRef; artifact_uid = $registry.allocations[$HumanRef] })
        }

        'validate' {
            $registry = Read-JsonHashtable $RegistryPath
            Assert-Registry $registry
            Write-Result ([ordered]@{
                schema_version = 1
                valid = $true
                registry_revision = [int]$registry.registry_revision
                allocation_count = [int]$registry.allocations.Count
            })
        }
    }
    exit 0
}
catch {
    [Console]::Error.WriteLine('[BLOCK] ' + $_.Exception.Message)
    exit 2
}
