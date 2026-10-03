#!/usr/bin/env python3
"""The competitors of hypotheses.md section 2.3 as the window runner starts them on L: the proxies
(M3 and B3) and, since M4b-2, the in-process libraries' harnesses (B3 and the hard cases).

Each proxy has its configurations in bench/competitors/<name>/ (m3, b3 and cases, Appendix B), its
binary under ~/opt (bench/competitors/install.sh, the pins in bench/cmake/pins.cmake), and here
its command line. Each library has a first-party harness in bench/competitors/<name>/, built per
checkout into <build>/harness (build_harnesses.sh), and two configurations, cases and b3
(Appendix B), each a file of the harness's arguments (one argument and its value per line, `#`
comments); the JVM harnesses take the flags of jvm.args before their class path. `render` fills a configuration's fields written between @ signs; `start` starts the system
fresh under taskset on the front core, in a session of its own (so its whole process group,
nginx's master and worker included, is stopped by one signal), with the soft open-file limit
raised to the hard one (WL7's limits), writes its pid file, and waits until its port accepts a
connection; `stop` stops the group with SIGTERM and collects its output. Never pgrep -f: the pid
is the one Popen started, and the group is the session it leads.

Linux only (taskset, /proc). The rendering is pure and runs anywhere (test_competitors.py).
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OPT = Path(os.environ.get("ONEPORT_OPT", str(Path.home() / "opt")))

# WL7 (frozen): N_PEND pending connections; Appendix B's limits are 2 x N_PEND and a backlog of
# N_PEND.
N_PEND = 10_000
# Section 1 (frozen): T_fb = T_dec = T_hdr = 3 s, and 60 s in B3 for every system with a
# detection timer. Appendix B matches each proxy's timer to the server's.
TIMER_S = {"m3": 3, "b3": 60, "cases": 3, "cases-fallback": 3}
# Appendix B: each proxy has three configurations, cases, M3 and B3. The cases configuration has
# two kinds here (M4b-1): "cases", no fallback, and "cases-fallback", the SMTP fallback, for the
# systems that have one (HAProxy's default_backend, Envoy's default chain, sslh's on-timeout); both
# render from one file. Section 10 runs the competitors' cases "at matched timers and at their
# defaults": TIMERS.
KINDS = ("m3", "b3", "cases", "cases-fallback")
CASES_KINDS = ("cases", "cases-fallback")
FALLBACK_SYSTEMS = ("haproxy", "envoy", "sslh-ev", "cmux")
# The systems whose cases configuration has the listener that requires the PROXY header: sslh
# reads it only when built with libproxyprotocol, which the pinned build lacks (M4b-1), and
# Appendix B names no PROXY for sslh. Among the libraries Netty (HAProxyMessageDecoder) and Jetty
# (ProxyConnectionFactory, inside its detector, so the header is optional there) read it.
PROXY_SYSTEMS = ("nginx", "haproxy", "envoy", "caddy-l4", "netty", "jetty")
TIMERS = ("matched", "default")
# A line of a cases file that begins with the field MATCHED is a comment at the system's defaults,
# and one that begins with FALLBACK is a comment in the kind without a fallback.
COMMENT = {"MATCHED": "# at the system's default: ", "FALLBACK": "# not in this kind (no fallback): "}
# The cases configurations' second listener, which requires the PROXY header, is the first port + 1.
PROXY_PORT_OFFSET = 1
# The stub's listeners follow its first port in the order of I20: HTTP/1.1, h2c, TLS, MQTT, SSH,
# SMTP (bench/server/config.cpp, --relay-port).
STUB_OFFSET = {"http1": 0, "h2c": 1, "tls": 2, "mqtt": 3, "ssh": 4, "smtp": 5}
TOKEN = re.compile(r"@[A-Z][A-Z0-9_]*@")
READY_S = 20.0
JVM_ARGS = HERE / "jvm.args"
# The libraries' kinds: no M3 configuration (Appendix B: "Each library harness has two, cases and
# B3").
LIBRARY_KINDS = ("cases", "cases-fallback", "b3")


def pin(name: str, pins: Path = REPO / "bench" / "cmake" / "pins.cmake") -> str:
    m = re.search(rf'^set\({re.escape(name)} "([^"]*)"\)$', pins.read_text(), re.M)
    if not m:
        raise KeyError(f"no {name} in {pins}")
    return m.group(1)


def args_lines(text: str) -> list[str]:
    """A rendered argument file: each line that is neither blank nor a comment is split on white
    space into arguments (an argument and its value, or a flag alone)."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out += s.split()
    return out


def jvm_args(path: Path = JVM_ARGS) -> list[str]:
    """The JVM's flags of jvm.args, one per line."""
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#")]


def harness_dir(build: Path) -> Path:
    """Where build_harnesses.sh puts the harnesses of a checkout's build: beside the C++ build."""
    return build / "harness"


@dataclass(frozen=True)
class System:
    name: str
    version_pin: str
    files: dict[str, str]  # kind -> configuration file name in bench/competitors/<name>/
    binary: str            # a proxy's under OPT, with {v} the version; a library's harness under <build>/harness
    library: bool = False
    main_class: str = ""   # the JVM harnesses' class

    def binary_path(self, harness: Path | None = None) -> Path:
        if self.library:
            if harness is None:
                raise ValueError(f"{self.name} is a library: its harness is built per checkout (build_harnesses.sh)")
            return harness / self.binary
        return OPT / self.binary.format(v=pin(self.version_pin))

    def template(self, kind: str) -> Path:
        if kind == "cases-fallback" and self.name not in FALLBACK_SYSTEMS:
            raise ValueError(f"{self.name} has no fallback (Appendix B; design/competitor-survey.md), so no cases-fallback")
        if self.library and kind not in LIBRARY_KINDS:
            raise ValueError(f"{self.name} is a library: no {kind} configuration (Appendix B: cases and B3)")
        return HERE / self.name / self.files["cases" if kind in CASES_KINDS else kind]

    def command(self, config: Path, run_dir: Path, harness: Path | None = None) -> list[str]:
        if self.library:
            args = args_lines(config.read_text())
            if self.main_class:  # Netty and Jetty: the JVM, its flags, the harness and the pinned jars
                java = OPT / f"jdk-{pin('ONEPORT_JDK_VERSION')}" / "bin" / "java"
                lib = OPT / f"{self.name}-{pin(self.version_pin)}" / "lib"
                return [str(java)] + jvm_args() + ["-cp", f"{self.binary_path(harness)}:{lib}/*", self.main_class] + args
            return [str(self.binary_path(harness))] + args
        b = str(self.binary_path())
        if self.name == "nginx":
            # -p: the prefix for the paths nginx resolves itself; -e: its error log before the
            # configuration's error_log takes over (nginx 1.19.5 and later).
            return [b, "-p", str(run_dir), "-e", str(run_dir / "error.log"), "-c", str(config)]
        if self.name == "haproxy":
            return [b, "-db", "-f", str(config)]  # -db: foreground, no daemon or master-worker
        if self.name == "envoy":
            return [b, "-c", str(config), "--concurrency", "1", "--disable-hot-restart"]
        if self.name == "caddy-l4":
            return [b, "run", "--config", str(config), "--adapter", "caddyfile"]
        if self.name == "sslh-ev":
            return [b, "-F", str(config)]
        raise KeyError(self.name)


SYSTEMS: dict[str, System] = {s.name: s for s in (
    System("nginx", "ONEPORT_NGINX_VERSION", {"m3": "m3.conf", "b3": "b3.conf", "cases": "cases.conf"}, "nginx-{v}/sbin/nginx"),
    System("haproxy", "ONEPORT_HAPROXY_VERSION", {"m3": "m3.cfg", "b3": "b3.cfg", "cases": "cases.cfg"}, "haproxy-{v}/sbin/haproxy"),
    System("envoy", "ONEPORT_ENVOY_VERSION", {"m3": "m3.yaml", "b3": "b3.yaml", "cases": "cases.yaml"}, "envoy-{v}/bin/envoy"),
    System("caddy-l4", "ONEPORT_CADDY_L4_VERSION", {"m3": "m3.Caddyfile", "b3": "b3.Caddyfile", "cases": "cases.Caddyfile"},
           "caddy-l4-{v}/caddy"),
    System("sslh-ev", "ONEPORT_SSLH_VERSION", {"m3": "m3.cfg", "b3": "b3.cfg", "cases": "cases.cfg"}, "sslh-{v}/bin/sslh-ev"),
    System("netty", "ONEPORT_NETTY_VERSION", {"b3": "b3.args", "cases": "cases.args"}, "netty/harness.jar", True, "oneport.NettyHarness"),
    System("jetty", "ONEPORT_JETTY_VERSION", {"b3": "b3.args", "cases": "cases.args"}, "jetty/harness.jar", True, "oneport.JettyHarness"),
    System("cmux", "ONEPORT_CMUX_VERSION", {"b3": "b3.args", "cases": "cases.args"}, "cmux/oneport-cmux", True),
    System("hyper-util", "ONEPORT_HYPER_UTIL_VERSION", {"b3": "b3.args", "cases": "cases.args"}, "hyper-util/oneport-hyper-util", True),
)}
# Section 6.3's order (M3: nginx, HAProxy, Envoy, caddy-l4, sslh-ev).
ORDER = ("nginx", "haproxy", "envoy", "caddy-l4", "sslh-ev")
# The in-process libraries, in section 2.3's order; the server runs in-process against them in B3
# (section 5.2).
LIBRARIES = ("netty", "jetty", "cmux", "hyper-util")
JVM_SYSTEMS = ("netty", "jetty")


def cpu_mask(cpu: int, ncpus: int = 16) -> str:
    """nginx's worker_cpu_affinity bit mask: one character per CPU, CPU 0 rightmost."""
    if not 0 <= cpu < ncpus:
        raise ValueError(f"CPU {cpu} outside 0 to {ncpus - 1}")
    return "".join("1" if i == cpu else "0" for i in reversed(range(ncpus)))


# Rule E (hypotheses.md section 8): "If rule E chooses `splice`, HAProxy gets `option splice-auto`"
# (Appendix B; section 5.3). HAProxy's M3 and B3 configurations hold the field SPLICE_AUTO, filled by
# the window's runner from the relay copy of the server's arm in the same cell (M7c).
SPLICE_AUTO = {True: "option splice-auto              # rule E chose splice for the server's relay (section 8; Appendix B)",
               False: "# option splice-auto: not set; rule E's relay copy is user space (section 8)"}


def fields(kind: str, port: int, stub_port: int, cpu: int, run_dir: Path, timers: str = "matched", splice: bool = False) -> dict[str, str]:
    """The fields of a configuration, written between @ signs. The admin port (caddy-l4) is the front port + 50, a
    design choice inside the run's port block. `stub_port` is the backend's first port: the stub's in M3 and B3,
    the server's in dedicated mode in the cases (its listeners in the order of I20, as the stub's). `splice`: the
    server's relay in the same cell splices (rule E), so HAProxy gets option splice-auto."""
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r}, not one of {KINDS}")
    if timers not in TIMERS:
        raise ValueError(f"timers {timers!r}, not one of {TIMERS}")
    out = {
        "PORT": str(port),
        "STUB_HTTP": str(stub_port + STUB_OFFSET["http1"]),
        "STUB_TLS": str(stub_port + STUB_OFFSET["tls"]),
        "TIMER_S": str(TIMER_S[kind]),
        "CPU": str(cpu),
        "CPU_MASK": cpu_mask(cpu),
        "RUN_DIR": str(run_dir),
        "ADMIN_PORT": str(port + 50),
        "N_PEND": str(N_PEND),
        "N_PEND_X2": str(2 * N_PEND),
        "TIMER_MS": str(TIMER_S[kind] * 1000),
        "REPO": str(REPO),
        "SPLICE_AUTO": SPLICE_AUTO[bool(splice)],
    }
    if kind in CASES_KINDS:
        out["PORT_PROXY"] = str(port + PROXY_PORT_OFFSET)
        for name, off in STUB_OFFSET.items():
            out["BACKEND_" + ("HTTP" if name == "http1" else name.upper())] = str(stub_port + off)
        out["MATCHED"] = "" if timers == "matched" else COMMENT["MATCHED"]
        out["FALLBACK"] = "" if kind == "cases-fallback" else COMMENT["FALLBACK"]
    elif timers != "matched":
        raise ValueError("M3 and B3 have their own timers (section 1, Appendix B); the defaults setting is the cases'")
    return out


def render_text(text: str, values: dict[str, str]) -> str:
    """Fills every field written between @ signs; refuses an unknown field or one left unfilled."""
    def sub(m: re.Match) -> str:
        key = m.group(0)[1:-1]
        if key not in values:
            raise KeyError(f"no value for {m.group(0)}")
        return values[key]
    out = TOKEN.sub(sub, text)
    if TOKEN.search(out):
        raise ValueError(f"unfilled field {TOKEN.search(out).group(0)}")
    return out


def render(system: str, kind: str, port: int, stub_port: int, cpu: int, run_dir: Path, timers: str = "matched",
           splice: bool = False) -> str:
    s = SYSTEMS[system]
    return render_text(s.template(kind).read_text(), fields(kind, port, stub_port, cpu, run_dir, timers, splice))


# ---------------------------------------------------------------- processes (Linux)


def raise_nofile() -> None:
    """The soft RLIMIT_NOFILE raised to the hard limit (WL7's limits), in the child before exec."""
    import resource  # POSIX only; the rendering above runs anywhere
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < hard:
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))


def parse_listening(text: str, port: int, host: str = "127.0.0.1") -> bool:
    """Whether /proc/net/tcp lists a socket in LISTEN (state 0A) on host:port."""
    want = "".join(f"{int(o):02X}" for o in reversed(host.split("."))) + f":{port:04X}"
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 3 and parts[1] == want and parts[3] == "0A":
            return True
    return False


def wait_port(port: int, limit_s: float = READY_S, host: str = "127.0.0.1") -> bool:
    """Ready once the port is listening, read from /proc/net/tcp: no connection is made, so a
    system that routes an empty connection to a default route (HAProxy at the end of its
    inspect-delay) sends nothing to the stub before the window."""
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        if parse_listening(Path("/proc/net/tcp").read_text(), port, host):
            return True
        time.sleep(0.05)
    return False


@dataclass
class Running:
    system: str
    kind: str
    proc: subprocess.Popen
    run_dir: Path
    config: Path
    port: int
    command: list[str] = field(default_factory=list)


def start(system: str, kind: str, port: int, stub_port: int, cpus: list[int], run_dir: Path, timers: str = "matched",
          harness: Path | None = None, splice: bool = False) -> Running:
    """Starts a system fresh on `cpus` (the front core) and waits for its port. A library's harness
    is found in `harness` (harness_dir of the build); its stub_port is unused (it serves in-process)."""
    s = SYSTEMS[system]
    run_dir.mkdir(parents=True, exist_ok=True)
    config = run_dir / f"{kind}.{s.template(kind).name.split('.', 1)[1]}"
    config.write_text(render(system, kind, port, stub_port, cpus[0], run_dir, timers, splice))
    cmd = ["taskset", "-c", ",".join(map(str, cpus))] + s.command(config, run_dir, harness)
    env = dict(os.environ)
    if system == "caddy-l4":
        # Caddy keeps its autosave and data under the XDG directories; the run's directory holds them.
        env.update(XDG_CONFIG_HOME=str(run_dir / "xdg-config"), XDG_DATA_HOME=str(run_dir / "xdg-data"))
        adapted = subprocess.run([str(s.binary_path()), "adapt", "--config", str(config), "--adapter", "caddyfile"],
                                 capture_output=True, text=True, env=env)
        (run_dir / "adapted.json").write_text(adapted.stdout if adapted.returncode == 0 else adapted.stderr)
    out = open(run_dir / "stdout.log", "wb")
    err = open(run_dir / "stderr.log", "wb")
    proc = subprocess.Popen(cmd, stdout=out, stderr=err, start_new_session=True, cwd=run_dir, env=env,
                            preexec_fn=raise_nofile)
    out.close()
    err.close()
    (run_dir / "pid").write_text(f"{proc.pid}\n")
    r = Running(system, kind, proc, run_dir, config, port, cmd)
    if not wait_port(port) or proc.poll() is not None:
        stop(r)
        tail = (run_dir / "stderr.log").read_text(errors="replace")[-400:]
        raise RuntimeError(f"{system} did not start on port {port} (exit {proc.poll()}): {tail}")
    return r


def group_pids(pgid: int) -> list[int]:
    """Every process of a process group, from /proc (never pgrep -f)."""
    pids = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
        except OSError:
            continue
        fields_ = stat[stat.rindex(")") + 2:].split()
        if int(fields_[2]) == pgid:
            pids.append(int(d.name))
    return sorted(pids)


def group_cpu_ticks(pgid: int) -> int:
    """utime + stime of every process of the group (nginx: master and worker), in clock ticks."""
    total = 0
    for pid in group_pids(pgid):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            continue
        f = stat[stat.rindex(")") + 2:].split()
        total += int(f[11]) + int(f[12])
    return total


def group_rss_kb(pgid: int) -> int:
    total = 0
    for pid in group_pids(pgid):
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS"):
                    total += int(line.split()[1])
        except OSError:
            continue
    return total


def stop(r: Running, grace: float = 10.0) -> int | None:
    """SIGTERM to the system's process group, then SIGKILL after `grace` seconds."""
    if r.proc.poll() is None:
        try:
            os.killpg(r.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            r.proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            os.killpg(r.proc.pid, signal.SIGKILL)
            r.proc.wait()
    # Any process of the group still alive (a worker after its master), then the group is empty.
    for pid in group_pids(r.proc.pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return r.proc.returncode
