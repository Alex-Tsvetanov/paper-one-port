# The records of the code freeze on W, then the gate of the same commit's Release build: the W
# counterpart of bench/records_job.sh (hypotheses.md, sections 8 step 3 and 11; the Papers repo's rule
# D5). W needs one record, MSVC's ASan (bench/sanitize_oneport.ps1), and the gate of the measured
# Release build (gate-W.json), which W's runners give to the freeze guard (--gate) and whose binaries
# every W row names (bench/check_rows.py).
#
#   powershell -ExecutionPolicy Bypass -File bench\records_job_w.ps1 -Out DIR -Records DIR [-DryRun]
#              [-Only "release asan gate"] [-LabBin DIR] [-CtestJobs N]
#
# Run it inside a W lab job, from a clone of the commit to record with no tracked change, with Alex's
# yes (it builds the whole project twice and runs the suite under ASan):
#   python bench\run\wjob.py run --dir DIR --name NAME -- powershell -ExecutionPolicy Bypass -File ^
#       <clone>\bench\records_job_w.ps1 -Out <OUT> -Records <RECORDS>
# Steps, each stopping the job unless it succeeds (a record that is not green stops it, and its driver
# refuses to start over existing logs, so it is never made again in silence):
#   release  a Release build of the clone (Out\build-release, MSVC, Ninja): the measured build;
#   asan     oneport's record (bench\sanitize_oneport.ps1) into Records;
#   gate     bench\build_inputs.py --host W over the Release build, then bench\check_records.py
#            --host W with --inputs against Records, into Out\gate-W.json, and the inputs hash and
#            sha256 of every measured binary into Out\measured-W.json.
# -DryRun: a test of the drivers, never citable: the record is named ...-dryrun and marked, Records may
# not be the Papers repo's lab\sanitizer-records, the logs stay under Out, and the gate runs with
# --accept-dry-run, so its output is marked and bench\check_rows.py refuses it.
#
# Written in M7e and checked only by PowerShell's parser: W was in use, so nothing ran there.
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [Parameter(Mandatory = $true)][string]$Records,
    [switch]$DryRun,
    [string]$Only = "release asan gate",
    [string]$LabBin = "",
    [int]$CtestJobs = 4
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
New-Item -ItemType Directory -Force $Out, $Records | Out-Null
$Out = (Resolve-Path $Out).Path
$Records = (Resolve-Path $Records).Path
$status = "incomplete"
$steps = Join-Path $Out "steps.txt"
$logFile = Join-Path $Out "records.log"
function Log([string]$text) {
    $line = "$(Get-Date -Format o) $text"
    Write-Output $line
    Add-Content -Encoding ascii $logFile $line
}
function Finish([string]$s) {
    "$(Get-Date -Format o) $s" | Set-Content -Encoding ascii (Join-Path $Out "records.done")
}
try {
    if ($DryRun -and ($Records -match '[\\/]lab[\\/]sanitizer-records$')) { $status = "STOPPED: a dry run never writes into lab\sanitizer-records"; throw $status }
    if (git -C $repo status --porcelain --untracked-files=no) { $status = "STOPPED: $repo has tracked changes"; throw $status }
    $commit = (git -C $repo rev-parse HEAD).Trim()
    if (-not $LabBin) { $LabBin = Join-Path $repo "..\..\lab\bin" }
    $inputsHash = Join-Path $LabBin "inputs_hash.py"
    if (-not (Test-Path $inputsHash)) { $status = "STOPPED: no $inputsHash (give -LabBin, the Papers repo's lab\bin)"; throw $status }
    $suffix = ""
    if ($DryRun) { $suffix = " (DRY RUN: never citable)" }
    Log "records start, one-port $commit$suffix, host $env:COMPUTERNAME, steps: $Only"
    $build = Join-Path $Out "build-release"
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    $vcvars = Join-Path (& $vswhere -latest -products * -property installationPath) "VC\Auxiliary\Build\vcvarsall.bat"
    if (-not (Test-Path $vcvars)) { $status = "STOPPED: vcvarsall.bat not found"; throw $status }

    function Step([string]$name, [scriptblock]$body) {
        $t0 = Get-Date
        Log "== $name start"
        $ok = (& $body) | Select-Object -Last 1
        $s = [int]((Get-Date) - $t0).TotalSeconds
        Add-Content -Encoding ascii $steps "$name $(if ($ok) { 0 } else { 1 }) $s"
        Log "== $name $(if ($ok) { 'ok' } else { 'FAILED' }), $s s"
        if (-not $ok) { $script:status = "STOPPED: $name failed (see $Out\$name.log)"; throw $script:status }
    }

    if ($Only -match '\brelease\b') {
        Step "release" {
            $bat = Join-Path $Out "release.cmd"
            $rlog = Join-Path $Out "release.log"
            @(
                "@echo off"
                "call `"$vcvars`" x64 >nul || exit /b 1"
                "cmake -S `"$repo`" -B `"$build`" -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release > `"$rlog`" 2>&1 || exit /b 2"
                "ninja -C `"$build`" >> `"$rlog`" 2>&1 || exit /b 3"
                "exit /b 0"
            ) | Set-Content -Encoding ascii $bat
            & cmd.exe /c $bat | Out-Null
            $LASTEXITCODE -eq 0
        }
    }
    if ($Only -match '\basan\b') {
        Step "asan" {
            $alog = Join-Path $Out "asan.log"
            $sargs = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $repo "bench\sanitize_oneport.ps1"), "-Records", $Records,
                "-LabBin", $LabBin, "-CtestJobs", "$CtestJobs", "-Work", (Join-Path $Out "records-work"))
            if ($DryRun) { $sargs += @("-DryRun") }
            & powershell @sargs *> $alog
            $LASTEXITCODE -eq 0
        }
    }
    if ($Only -match '\bgate\b') {
        Step "gate" {
            # Each Python step runs inside cmd.exe, as the release step's build does: build_inputs.py
            # writes its summary line to standard error, which a native command run from PowerShell
            # 5.1 with $ErrorActionPreference "Stop" turns into a terminating error (found in the dry
            # run of the M7 freeze night, which stopped here).
            $glog = Join-Path $Out "gate.log"
            $inputs = Join-Path $Out "release.inputs.json"
            $gate = Join-Path $Out "gate-W.json"
            $measured = Join-Path $Out "measured-W.json"
            $py = @'
import json, sys
inputs, gate = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
b = inputs["builds"]["oneport"]
m = {"commit": sys.argv[4], "host": "W", "dry_run": gate["dry_run"], "citable": gate["citable"],
     "inputs_hash": {t: v["inputs_hash"] for t, v in b["targets"].items()}, "config": b.get("config"),
     "binaries": gate["binaries"], "records": sorted(gate["oneport"]["records"])}
json.dump(m, open(sys.argv[3], "w"), indent=1)
print(json.dumps({k: m[k] for k in ("commit", "dry_run", "citable", "binaries")}, indent=1))
'@
            $pyFile = Join-Path $Out "measured.py"
            $py | Set-Content -Encoding ascii $pyFile
            $dryArg = ""
            if ($DryRun) { $dryArg = " --accept-dry-run" }
            $bat = Join-Path $Out "gate.cmd"
            @(
                "@echo off"
                "python `"$repo\bench\build_inputs.py`" --build `"$build`" --host W --out `"$inputs`" --inputs-hash `"$inputsHash`" > `"$glog`" 2>&1 || exit /b 1"
                "python `"$repo\bench\check_records.py`" --records `"$Records`" --host W --inputs `"$inputs`" --out `"$gate`"$dryArg >> `"$glog`" 2>&1 || exit /b 2"
                "python `"$pyFile`" `"$inputs`" `"$gate`" `"$measured`" $commit >> `"$glog`" 2>&1 || exit /b 3"
                "exit /b 0"
            ) | Set-Content -Encoding ascii $bat
            & cmd.exe /c $bat | Out-Null
            $LASTEXITCODE -eq 0
        }
    }
    $status = "done"
    if ($DryRun) { $status = "done (dry run)" }
    Log "records $status"
}
catch {
    if ($status -eq "incomplete") { $status = "STOPPED: $($_.Exception.Message)" }
    Log $status
    Finish $status
    exit 1
}
Finish $status
exit 0
