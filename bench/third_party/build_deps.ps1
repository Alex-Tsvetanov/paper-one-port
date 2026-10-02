# Builds the pinned third-party C libraries of oneport on W, one install prefix per build flavour
# (design/proposal.md, Z3 and I23): the Windows counterpart of build_deps.sh. MSVC only.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File bench\third_party\build_deps.ps1 [release|asan ...]
#   $env:ONEPORT_LIBS = "openssl"; ... build_deps.ps1 asan         (one library; default both)
#
# Versions, URLs and sha256 come from bench\cmake\pins.cmake, the one source of them, read as
# build_deps.sh reads them. The archive is downloaded into $ONEPORT_OPT\src (default
# %USERPROFILE%\opt\src) if absent, and the build stops unless its sha256 equals the pin. Each
# library and flavour is built in its own fresh copy of the source under $ONEPORT_OPT\build and
# installed into $ONEPORT_OPT\<lib>-<version>-<flavour>, which CMakeLists.txt finds by the same
# names. An existing build directory or prefix is never removed or overwritten: the script stops
# instead. Logs: $ONEPORT_OPT\build\logs\<lib>-<flavour>.log, and a .done file with the exit code.
#
# The toolchain, checked before any build:
#   MSVC     cl 19.51.36246 (hypotheses.md, "Words"), from the vcvars64.bat of $ONEPORT_VCVARS
#            (default: the Build Tools 18 install), whose environment the builds run in;
#   Perl     Strawberry Perl, perl\bin of $ONEPORT_PERL_ROOT (default
#            $ONEPORT_OPT\strawberry-perl-5.42.3.1), first on PATH: OpenSSL's NOTES-WINDOWS.md
#            recommends it, and Git's MSYS perl is not suitable for the VC targets;
#   NASM     $ONEPORT_NASM (default $ONEPORT_OPT\nasm-3.02), on PATH: NOTES-WINDOWS.md names NASM
#            as the only supported assembler for VC-WIN64A.
# Only perl\bin of Strawberry Perl goes on PATH, not its c\bin (a MinGW toolchain), so nothing
# there can shadow MSVC's tools.
#
# The flavours and their flags (the same compiler as the server: MSVC 19.51.36246 on W):
#   release  no sanitizer; the Debug and Release builds of oneport link it
#   asan     AddressSanitizer, MSVC's /fsanitize=address (hypotheses.md, section 11: on W only
#            ASan is required; MSVC has no UBSan, TSan or MSan)
# OpenSSL: the options that select features are L's (build_deps.sh): a static build (no-shared),
# no loadable modules, no tests, no documentation; the asan flavour also leaves out the openssl
# program (no-apps), which selects no feature. The target and toolchain options differ by host,
# as proposal I23 says: VC-WIN64A here (linux-x86_64-clang on L). OpenSSL's enable-asan adds the
# gcc-style -fsanitize=address, which cl does not take, so the asan flavour passes MSVC's flag as
# a Configure argument instead (Configure passes every argument that begins with "/" to the
# compiler, Configure lines 1167 to 1174 at 3.5.9). OpenSSL compiles its static libraries with
# "/MT /Zl" (Configurations/10-main.conf line 1580 at 3.5.9), so they name no C runtime and link
# into oneport's /MD (Release) and /MDd (Debug) builds alike.
# nghttp2: the library only (ENABLE_LIB_ONLY), static, in a CMake Release build with Ninja and cl.
# The Release flags (CMAKE_C_FLAGS_RELEASE) add /Zl, as OpenSSL does for its static libraries, so
# the library names no C runtime either; the asan flavour also adds /fsanitize=address and /Z7
# (debug information in the objects, so the library carries it). They go in the Release flags,
# not CMAKE_C_FLAGS, because CMake's compiler checks build a Debug executable, which /Zl leaves
# without a C runtime and whose /RTC1 /fsanitize=address refuses.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Flavours)
if (-not $Flavours) { $Flavours = @('release', 'asan') }

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pins = Join-Path $here '..\cmake\pins.cmake'
$opt = if ($env:ONEPORT_OPT) { $env:ONEPORT_OPT } else { Join-Path $env:USERPROFILE 'opt' }
$vcvars = if ($env:ONEPORT_VCVARS) { $env:ONEPORT_VCVARS } else { 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat' }
$perlRoot = if ($env:ONEPORT_PERL_ROOT) { $env:ONEPORT_PERL_ROOT } else { Join-Path $opt 'strawberry-perl-5.42.3.1' }
$nasmDir = if ($env:ONEPORT_NASM) { $env:ONEPORT_NASM } else { Join-Path $opt 'nasm-3.02' }
$libs = if ($env:ONEPORT_LIBS) { $env:ONEPORT_LIBS -split '\s+' } else { @('nghttp2', 'openssl') }
$wantCl = '19.51.36246'
# Windows' own bsdtar, which reads .tar.gz and .tar.xz (another tar on PATH may not take C:\ paths).
$tar = Join-Path $env:SystemRoot 'System32\tar.exe'

function Get-Pin([string]$name) {
    $m = Select-String -Path $pins -Pattern ('^set\(' + $name + ' "([^"]*)"\)$')
    if (-not $m) { throw "build_deps: no $name in $pins" }
    return $m.Matches[0].Groups[1].Value
}

function Get-Archive([string]$url, [string]$want) {
    $src = Join-Path $opt 'src'
    New-Item -ItemType Directory -Force -Path $src | Out-Null
    $file = Join-Path $src ([System.IO.Path]::GetFileName($url))
    if (-not (Test-Path $file)) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $file
    }
    $got = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLowerInvariant()
    if ($got -ne $want) { throw "build_deps: $file has sha256 $got, the pin is $want" }
    return $file
}

function Assert-Fresh([string]$path) {
    if (Test-Path $path) { throw "build_deps: $path exists; remove it by hand to rebuild" }
}

# The vcvars64.bat environment, imported into this process, then Perl and NASM first on PATH.
function Enter-Toolchain {
    if (-not (Test-Path $vcvars)) { throw "build_deps: no $vcvars" }
    $dump = & cmd.exe /c "`"$vcvars`" >nul 2>&1 && set"
    foreach ($line in $dump) {
        if ($line -match '^([^=]+)=(.*)$') { Set-Item -Path ("env:" + $matches[1]) -Value $matches[2] }
    }
    $env:PATH = (Join-Path $perlRoot 'perl\bin') + ';' + $nasmDir + ';' + $env:PATH
    $clLine = (& cmd.exe /c 'cl 2>&1') | Select-Object -First 1
    if ($clLine -notmatch [regex]::Escape("Version $wantCl")) { throw "build_deps: cl is not $wantCl ($clLine)" }
    $perlArch = & perl -MConfig -e 'print $Config{archname}'
    if ($perlArch -notmatch '^MSWin32') { throw "build_deps: perl on PATH is not a native Windows perl ($perlArch)" }
    $nasmLine = & nasm -v
    return "$clLine; perl $(& perl -e 'print $^V') ($perlArch) at $((Get-Command perl).Source); $nasmLine at $((Get-Command nasm).Source)"
}

# Runs one command line in cmd.exe with its output appended to the log; throws on a non-zero exit.
function Invoke-Logged([string]$log, [string]$dir, [string]$line) {
    Add-Content -Path $log -Value "> $line"
    Push-Location $dir
    try {
        & cmd.exe /c "$line >> `"$log`" 2>&1"
        if ($LASTEXITCODE -ne 0) { throw "build_deps: exit $LASTEXITCODE from: $line" }
    }
    finally { Pop-Location }
}

function Get-OpensslFlags([string]$flavour) {
    switch ($flavour) {
        'release' { return @() }
        'asan' { return @('no-apps', '/fsanitize=address') }
        default { throw "build_deps: unknown flavour $flavour" }
    }
}

# CMAKE_C_FLAGS_RELEASE: CMake's MSVC Release default ("/MD /O2 /Ob2 /DNDEBUG": nghttp2 asks for
# CMake 3.14, so the runtime flag is still in this variable) and the flavour's additions.
function Get-Nghttp2ReleaseFlags([string]$flavour) {
    switch ($flavour) {
        'release' { return '/MD /O2 /Ob2 /DNDEBUG /Zl' }
        'asan' { return '/MD /O2 /Ob2 /DNDEBUG /Zl /fsanitize=address /Z7' }
        default { throw "build_deps: unknown flavour $flavour" }
    }
}

function Build-Openssl([string]$flavour, [string]$log) {
    $version = Get-Pin 'ONEPORT_OPENSSL_VERSION'
    $archive = Get-Archive (Get-Pin 'ONEPORT_OPENSSL_URL') (Get-Pin 'ONEPORT_OPENSSL_SHA256')
    $src = Join-Path $opt "build\openssl-$version-$flavour"
    $prefix = Join-Path $opt "openssl-$version-$flavour"
    Assert-Fresh $src
    Assert-Fresh $prefix
    New-Item -ItemType Directory -Force -Path $src | Out-Null
    Invoke-Logged $log $src "`"$tar`" -xf `"$archive`" --strip-components=1"
    $cmd = @('perl', 'Configure', 'VC-WIN64A', 'no-shared', 'no-module', 'no-tests', 'no-docs') + (Get-OpensslFlags $flavour) +
           @("`"--prefix=$prefix`"", "`"--openssldir=$prefix\ssl`"", '--libdir=lib')
    Invoke-Logged $log $src ($cmd -join ' ')
    Invoke-Logged $log $src 'nmake'
    Invoke-Logged $log $src 'nmake install_sw'
}

function Build-Nghttp2([string]$flavour, [string]$log) {
    $version = Get-Pin 'ONEPORT_NGHTTP2_VERSION'
    $archive = Get-Archive (Get-Pin 'ONEPORT_NGHTTP2_URL') (Get-Pin 'ONEPORT_NGHTTP2_SHA256')
    $src = Join-Path $opt "build\nghttp2-$version-$flavour"
    $prefix = Join-Path $opt "nghttp2-$version-$flavour"
    Assert-Fresh $src
    Assert-Fresh $prefix
    New-Item -ItemType Directory -Force -Path $src | Out-Null
    Invoke-Logged $log $src "`"$tar`" -xf `"$archive`" --strip-components=1"
    $cmd = @('cmake', '-S', "`"$src`"", '-B', "`"$src\build`"", '-G', 'Ninja', '-DCMAKE_C_COMPILER=cl', '-DCMAKE_BUILD_TYPE=Release',
             '-DENABLE_LIB_ONLY=ON', '-DBUILD_SHARED_LIBS=OFF', '-DBUILD_STATIC_LIBS=ON', '-DENABLE_DOC=OFF', '-DBUILD_TESTING=OFF',
             "`"-DCMAKE_INSTALL_PREFIX=$prefix`"", '-DCMAKE_INSTALL_LIBDIR=lib', "`"-DCMAKE_C_FLAGS_RELEASE=$(Get-Nghttp2ReleaseFlags $flavour)`"")
    Invoke-Logged $log $src ($cmd -join ' ')
    Invoke-Logged $log $src "cmake --build `"$src\build`""
    Invoke-Logged $log $src "cmake --install `"$src\build`""
}

$toolchain = Enter-Toolchain
$logs = Join-Path $opt 'build\logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$failed = 0
foreach ($f in $Flavours) {
    Get-OpensslFlags $f | Out-Null  # an unknown flavour stops here
    foreach ($lib in $libs) {
        if ($lib -ne 'nghttp2' -and $lib -ne 'openssl') { throw "build_deps: unknown library $lib" }
        $log = Join-Path $logs "$lib-$f.log"
        $done = Join-Path $logs "$lib-$f.done"
        Set-Content -Path $log -Value "build_deps: $lib $f, $((Get-Date).ToString('o')), $toolchain"
        $rc = 0
        try {
            if ($lib -eq 'openssl') { Build-Openssl $f $log } else { Build-Nghttp2 $f $log }
        }
        catch {
            Add-Content -Path $log -Value "build_deps: $($_.Exception.Message)"
            $rc = 1
        }
        Set-Content -Path $done -Value $rc
        Write-Output "build_deps: $lib $f exit $rc ($log)"
        if ($rc -ne 0) { $failed = 1 }
    }
}
exit $failed
