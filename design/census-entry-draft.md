# Draft: a revision-log entry for the kernel census on the laptop

A draft for the paper session, not an entry. It is logged only if Alex chooses option (b) of the
decision in `design/STATE.md` section 0, "The kernel census on the laptop", and only by a paper
session, appended at the true end of the revision log of `laptop-w-bringup`. Nothing above the log
is edited. If it is logged, it is logged before the first census job runs.

### 2026-10-25: The kernel census on the laptop (a descriptive reading)

This entry does not edit the frozen text above. It decides nothing and changes no decision. No
timing campaign runs under it.

1. The definition. The census is the one defined by the entry "2026-10-22: Computer
   Communications, and the kernel listening-descriptor census", item 2, logged on the branch
   `dev/alex-tsvetanov/comcom-manuscript` (bb473a4), whose rows are those of its tool,
   `paper/census_listen.py` at bb473a4. The measured Release binary is started with no client and
   no load. It binds 127.0.0.1 only. On L the count is the rows of `ss -Hltnp` for that process. On
   W it is netstat's LISTENING rows for that process, and GetExtendedTcpTable must list the same
   addresses. The server's own listening lines are stored and are not the count.
2. The binaries. W is the laptop's Windows (the entry "W's runs on the laptop's Windows"). So W's
   binary is the oneport of the gate that bound the laptop's W rows, `gate-W.json` of the lab job
   p3-gate-w-5 (sha256 96248c8f...), not the one of `lab/gates/measured-W.json`. L's binary is the
   one of `lab/gates/gate-L.json` (sha256 c6517177...), as on 22 October.
3. The rows. L: epoll in one-port mode with the shared listener and one worker, in dedicated mode,
   and in one-port mode with SO_REUSEPORT and two workers; io_uring in one-port and in dedicated
   mode. W: IOCP in one-port and in dedicated mode. Detection replay, dispatch in process.
4. Two checks added, both readings of the kernel. On L the rows of `/proc/net/tcp` and
   `/proc/net/tcp6` in the LISTEN state whose inode is a socket of the process must list the same
   addresses as ss. On W netstat's IPv6 table and GetExtendedTcpTable's IPv6 table are read too, and
   must hold no row of the process.
5. How it runs. `paper/laptop_w/census_host.py`, one untimed lab job per system
   (`paper/laptop_w/jobs/census-l.json` and `census-w.json`, commit e886724). It refuses a gate or a
   binary other than those of item 2. `paper/laptop_w/census_lw.py` writes
   `results/laptop-w/census-macros.tex` and `results/laptop-w/tables/census.tex` from the two jobs'
   archives, and refuses a functional test, the desktop's binary and any gate other than the
   analysis's.
6. Why it decides nothing. No hypothesis names the census. No value of it enters `summary.json`,
   `decisions.csv` or any other macros file of the laptop set. The paper reports it as a descriptive
   count, beside the frozen results.
