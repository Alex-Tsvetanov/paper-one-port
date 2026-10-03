# The sanitizer record of oneport on W (hypotheses.md, section 11: "on W, MSVC 19.51.36246: ASan,
# with one compiler because the gate matches the compiler"; the Papers repo's rule D5). The W
# counterpart of bench/sanitize_oneport.sh, same record (bench/oneport_record.py, --host-tag W).
#
#   powershell -ExecutionPolicy Bypass -File bench\sanitize_oneport.ps1 -Records DIR [-DryRun]
#              [-Work DIR] [-RecordsLogs DIR] [-LabBin DIR] [-CtestJobs N] [-RepoUrl URL]
#
# From this checkout, which must have no tracked changes: in a vcvars x64 shell, configures the
# whole CMake project with MSVC and Ninja (Release, ONEPORT_SANITIZER=address, the asan flavour of
# OpenSSL and nghttp2 from bench\third_party\build_deps.ps1), builds it, hashes what it compiled
# (bench\build_inputs.py --host W), runs the whole CTest suite (ctest -V) with
# ASAN_OPTIONS=detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1 (M6a's development
# checks on W; MSVC's runtime offers no detect_leaks), keeps the logs under RecordsLogs\<name>\ with
# their SHA256SUMS, packed into <name>.tar.gz with its sha256 (tar.exe of Windows), and writes
# Records\oneport-<commit>-W-asan.json. Green only if the build and every test passed and no log
# holds a sanitizer report.
#
# -DryRun: a test of this driver, never citable: the name ends in -dryrun, the record is marked
# (the gate refuses it), Records may not be the Papers repo's lab\sanitizer-records, and the logs
# go under Work\records-logs.
#
# Untested when written (2026-10-03): W was in use, so nothing ran there. Run it only with Alex's
# yes, when W is free; it changes nothing outside Work, RecordsLogs and Records.
param(
    [Parameter(Mandatory = $true)][string]$Records,
    [switch]$DryRun,
    [string]$Work = (Join-Path $env:USERPROFILE "lab\p3\records-work"),
    [string]$RecordsLogs = "",
    [string]$LabBin = "",
    [int]$CtestJobs = 4,
    [string]$RepoUrl = ""
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
New-Item -ItemType Directory -Force $Records | Out-Null
$Records = (Resolve-Path $Records).Path
if ($DryRun -and ($Records -match '[\\/]lab[\\/]sanitizer-records$')) { throw "a dry run never writes into lab\sanitizer-records" }
if (git -C $repo status --porcelain --untracked-files=no) { throw "$repo has tracked changes; a record must name committed code" }
$commit = (git -C $repo rev-parse HEAD).Trim()
if (-not $RepoUrl) { $RepoUrl = (git -C $repo remote get-url origin).Trim() }
$suffix = ""
if ($DryRun) { $suffix = "-dryrun" }
$name = "oneport-$($commit.Substring(0, 9))-W-asan$suffix"
$workDir = Join-Path $Work "asan$suffix"
if (-not $RecordsLogs) {
    if ($DryRun) { $RecordsLogs = Join-Path $Work "records-logs" } else { $RecordsLogs = Join-Path $env:USERPROFILE "lab\records-logs" }
}
$logDir = Join-Path $RecordsLogs $name
$archive = Join-Path $RecordsLogs "$name.tar.gz"
if ((Test-Path $logDir) -or (Test-Path $archive)) { throw "$logDir or $archive exists; record logs are never overwritten" }
if (-not $LabBin) { $LabBin = Join-Path $repo "..\..\lab\bin" }
$inputsHash = Join-Path $LabBin "inputs_hash.py"
if (-not (Test-Path $inputsHash)) { throw "no $inputsHash (give -LabBin, the Papers repo's lab\bin)" }

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$vcvars = Join-Path (& $vswhere -latest -products * -property installationPath) "VC\Auxiliary\Build\vcvarsall.bat"
if (-not (Test-Path $vcvars)) { throw "vcvarsall.bat not found" }

if (Test-Path $workDir) { Remove-Item -Recurse -Force $workDir }
New-Item -ItemType Directory -Force $workDir | Out-Null
$build = Join-Path $workDir "build"
$asanOptions = "detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1"
$cmakeArgs = "-G Ninja -DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address"
$buildLog = Join-Path $workDir "build.log"
$ctestLog = Join-Path $workDir "ctest.log"
$bat = Join-Path $workDir "sanitize.cmd"
@(
    "@echo off"
    "call `"$vcvars`" x64 >nul || (echo 1 > `"$workDir\build.rc`" & exit /b 1)"
    "cmake -S `"$repo`" -B `"$build`" $cmakeArgs > `"$buildLog`" 2>&1 || (echo 2 > `"$workDir\build.rc`" & exit /b 2)"
    "ninja -C `"$build`" >> `"$buildLog`" 2>&1 || (echo 3 > `"$workDir\build.rc`" & exit /b 3)"
    "echo 0 > `"$workDir\build.rc`""
    "python `"$repo\bench\build_inputs.py`" --build `"$build`" --host W --out `"$workDir\build.inputs.json`" --inputs-hash `"$inputsHash`" >> `"$buildLog`" 2>&1"
    "set `"ASAN_OPTIONS=$asanOptions`""
    "cd /d `"$build`""
    "ctest -V -j $CtestJobs --timeout 900 > `"$ctestLog`" 2>&1"
    "echo %ERRORLEVEL% > `"$workDir\ctest.rc`""
    "exit /b 0"
) | Set-Content -Encoding ascii $bat
$start = Get-Date
& cmd.exe /c $bat
$seconds = [int]((Get-Date) - $start).TotalSeconds
$buildRc = 1
if (Test-Path "$workDir\build.rc") { $buildRc = [int](Get-Content "$workDir\build.rc" | Select-Object -First 1).Trim() }
$ctestRc = 1
if (Test-Path "$workDir\ctest.rc") { $ctestRc = [int](Get-Content "$workDir\ctest.rc" | Select-Object -First 1).Trim() }

# The logs, kept as bench/keep_record_logs.sh keeps them on L.
New-Item -ItemType Directory -Force $logDir | Out-Null
foreach ($f in @($buildLog, $ctestLog, (Join-Path $workDir "build.inputs.json"))) {
    if (Test-Path $f) { Copy-Item $f $logDir }
}
$sums = Get-ChildItem -File $logDir | Sort-Object Name | ForEach-Object {
    "$((Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower())  ./$($_.Name)"
}
$sums | Set-Content -Encoding ascii (Join-Path $logDir "SHA256SUMS")
& tar.exe -czf $archive -C $RecordsLogs $name
if ($LASTEXITCODE -ne 0) { throw "tar failed for $archive" }
$archiveSha = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLower()
"$archiveSha  $name.tar.gz" | Set-Content -Encoding ascii "$archive.sha256"

$recArgs = @("$repo\bench\oneport_record.py", "--work", $workDir, "--record", (Join-Path $Records "$name.json"),
    "--repo", $RepoUrl, "--commit", $commit, "--repo-head", $commit, "--sanitizer", "asan",
    "--cmake-args=$cmakeArgs", "--options=ASAN_OPTIONS=$asanOptions", "--host", $env:COMPUTERNAME, "--host-tag", "W",
    "--build-exit", "$buildRc", "--ctest-exit", "$ctestRc", "--seconds", "$seconds",
    "--pins", "$repo\bench\cmake\pins.cmake", "--logs-archive", $archive, "--logs-sha256", $archiveSha)
if ($DryRun) { $recArgs += "--dry-run" }
& python @recArgs
exit $LASTEXITCODE
