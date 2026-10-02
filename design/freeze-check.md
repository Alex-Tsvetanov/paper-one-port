# Freeze check of hypotheses.md

Checked: `hypotheses.md` at commit eab511f of `paper-one-port` (status DRAFT), against
`design/proposal.md` at the same commit, the first audit (`design/proposal-audit.md`), the second
audit (`design/proposal-audit-2.md`), rules D1 to D9 (`CLAUDE.md`) and the format of P2's
`papers/typed-routing/hypotheses-round2.md`. Written 2026-10-02 as the last check before the
freeze. Nothing here is a result.

Taken as given and not reopened: the coordinator's freeze order (hypotheses freeze, engineering,
code freeze, the A/A pilot in dedicated mode, the simulation, one pilot entry, then any one-port
window of the frozen code), and the seeds as placeholders fixed in one revision-log entry before
the code freeze.

Method:
- Both files read in full; P2's file read for its structure.
- Every number of sections 4.2, 4.5 and 4.6 and the proposal's section 9 recomputed in a scratch
  script (Python; exact binomial sums in `fractions`; `statistics.NormalDist` for Φ; the
  chi-square quantile by bisection on the regularized lower incomplete gamma function). The script
  is not committed.
- Kernel claims read in the Linux v7.2 sources, the version the proposal and both audits use
  (https://raw.githubusercontent.com/torvalds/linux/v7.2/): `net/ipv4/tcp.c`,
  `net/ipv4/tcp_input.c`, `net/ipv4/tcp_output.c`, `net/core/skbuff.c`,
  `include/linux/skbuff.h`, `include/net/sock.h`, `drivers/net/loopback.c`.
- What each competitor does with unread bytes is taken from `design/competitor-survey.md`, whose
  source reads are cited there. The competitors' sources were not read again.

Counts: 1 MAJOR, 7 MINOR, and 10 wording items. Verdict: **not frozen.** FC1 changes what B3
measures, so it is not a wording fix, and B3 cannot change after the freeze. `hypotheses.md` is
left unchanged, with its DRAFT status line; the wording items are listed in section 4 for the same
revision as FC1.

## 1. Result by check

| Check | Result |
|---|---|
| 1. N1 text | Passes on every direct path. Residual discretion: FC2 to FC5, all MINOR. None lets one-port against dedicated data enter a pilot output by a rule. |
| 2a. T measurable | Passes. |
| 2b. `K_BASE` cancels from Q | Passes, exactly. |
| 2c. "Whole-system" with its two exclusions | Fails: FC1. |
| 3a. B3 test exact and complete | Passes, except one undefined case in the BCa (FC6). |
| 3b. Competitor buffer settings | Pass: each sourced or justified. |
| 4. Self-containment | Passes. Small gaps: FC7, FC8, wording items. |
| 5. Consistency with the proposal | Passes, including D9 and the time totals. |
| 6. Rules | No private library named; 0 em and 0 en dashes; a few numbers lack a label or a source (wording items). |

## 2. What passed

### 2.1 N1 (section 8, the definitions, 4.6 step 1)

- **Direct contrast.** "No window, on any code, times one-port mode against dedicated mode
  before the pilot entry" (lines 609 to 610).
- **The frozen code.** Step 4 runs in dedicated mode only (rule E's IOCP receive form, the A/A
  pilot, its timer and split parts). Step 6 is committed "before any one-port window of the
  frozen code". Everything one-port on the frozen code is in step 7: rule E's two one-port
  choices, M2's rates, the B3 feasibility windows, `K_BASE`, and every confirmatory, secondary and
  hard-case run. So it does not matter whether a hard-case run counts as a window.
- **The pilot's inputs.** Both arms in dedicated mode; λ from the C1 pilot cells; G from the
  timer part and `GAP_SPLIT` from the split part, both against dedicated ports. Every output
  follows by a fixed rule with fixed seeds, and the entry says "Nothing in it is chosen".
- **Reruns.** Per cell at most ⌈P/4⌉ = 4, by the rules of section 7; a cell short of P valid
  sessions is not resolved. The whole pilot at most once, only after an infrastructure fault or a
  code change, only before the pilot entry and before any one-port window of the frozen code, with
  the same seeds; the abandoned pilot archived and named. After either cutoff, never.
- **What counts as a one-port window.** Any timed window in one-port mode, whatever it is compared
  with; unit tests and untimed counter checks excluded. This covers relay windows against the
  proxies and one-port option against option.
- **The pilot entry's contents** (9.2) hold the coordinator's list: R_C, the resolved list, m_C,
  the joint powers, the WL2 rates, `G_L`, `G_W`, `GAP_SPLIT`; also `CODE_FREEZE`,
  `ANALYSIS_COMMIT`, the archive's sha256, the invalid windows and reruns, every Power_c(R) with
  each R_c, and the IOCP receive form named again.
- **Step 1's precondition.** At eab511f the tree holds no server code: `bench/` and `analysis/`
  contain only `.gitkeep`.

### 2.2 N3 (WL7, B3)

- **Each term is measurable with the stated method.** U from the summed `VmRSS` of the system's
  processes; Kq from the `r` field of `ss -tm` per accepted socket; Ks from `Slab` in
  `/proc/meminfo`; `K_BASE` as the median Ks of 16 `ophold` windows. `/proc` reports kB and `ss`
  bytes; the analysis converts.
- **`K_BASE` cancels exactly.** W = U + Kq + Ks uses no `K_BASE`. So
  (T_comp + `K_BASE`) / (T_srv + `K_BASE`) = W_comp / W_srv and D = W_comp - W_srv =
  T_comp - T_srv hold identically for any value of `K_BASE`, given one value per host for both
  arms. No decision and no validity rule depends on it.
- **The two named exclusions are correctly outside W.** `f` is an accounting reservation. Kernel
  memory outside `Slab` that no receive queue is charged for (page tables, kernel stacks, vmalloc)
  is in none of the three readings. The failure is inside W: FC1.

### 2.3 N2 (B3)

- **The test.** Null "the median Q is at most 1.10". The sign test counts Q strictly above 1.10;
  a tie or a session without a ratio counts against; at the boundary X is stochastically at most Bin(16, 1/2),
  so p = P(X ≥ x) is exact for any shape. The BCa uses the lower end of the
  two-sided 1 - 2α interval at 1.10, with the share below 1.10 clipped. Holm over the 18 cells,
  once per computation, a pass under both; p = 1 below 16 valid sessions. D9 at R = 16:
  2^-16 = 1.53e-5 < 0.025/18 = 1.39e-3. The 16 descriptive cells use the same statistic outside
  Holm. The dual rule's error control rests on the exact sign test, as in the cost family.
- **Buffer settings.** The rule is a labelled design choice. Every row is sourced in the proposal's
  section 6 and "Sources added": nginx (stream core and stream proxy module docs; survey 2.1),
  HAProxy (configuration.txt v3.4.6 lines 4208, 5002, 6286 and 12180), Envoy (`listener.proto`,
  `tls_inspector.proto` and the edge best-practices page, v1.39.2), caddy-l4 and sslh-ev (survey
  2.7, 2.8), Netty (source lines at 4.2.18.Final), Jetty (12.1 standard modules page), cmux and
  hyper-util (survey 2.10, 2.12). Each change meets the rule: Envoy's 32 KiB is the edge page's
  value for TCP proxies; tls_inspector's buffer doubles on demand; HAProxy's
  `option use-small-buffers` falls back to a regular buffer (line 12180). One item stays on the
  proposal's "not verified" list: the receive allocator of Netty's native epoll transport. Netty is
  descriptive.

### 2.4 Self-containment

`hypotheses.md` alone states the scope (1), the arms (2.1, 2.3, 2.4), the families (2.2), every
primary hypothesis with its test and pass rule (5), the statistics (4.1 to 4.4), D9 sizing (4.5),
the R_C rule (4.6), seeds and orders (4.7), the freeze order (8), the cell lists (6), the
validity rules (7), the pilot placeholders (9.2), the secondaries (10), the sanitizer gaps (11),
the narrowing order M3, then B3, then cost per backend (12), and the hard-case table (Appendix A).

### 2.5 Consistency with the proposal

Identical in both files: the names C1 to C3, B1 to B3 and M1 to M3; the cells (cost 12 per
hypothesis, 8 on L and 4 on W, so m_C ≤ 36; B3 (5 + 4) × 2 = 18 Holm and 4 × 2 × 2 = 16
descriptive; mechanism 6 + 4 + 10 = 20, 18 on L and 2 on W); the margins [0.98, 1.02] and 1.10;
R_C's candidates; R_B = R_M = 16; P = 16; ⌈R/4⌉.

D9, 2^-R < 0.025/m, recomputed:

| Family | m | α/m | D9 minimum R | 2^-R at that minimum | R used | 2^-R at R used |
|---|---|---|---|---|---|---|
| Cost | 36 at most | 6.944e-4 | 11 | 4.883e-4 | R_C ≥ 11 | at most 4.883e-4 |
| B3 | 18 | 1.389e-3 | 10 | 9.766e-4 | 16 | 1.526e-5 |
| Mechanism | 20 | 1.250e-3 | 10 | 9.766e-4 | 16 | 1.526e-5 |

For every m_C from 1 to 36, 2^-11 < 0.025/m_C, so any resolved subset meets D9 at every candidate.

Also reproduced:
- the sign-test grid of 4.5 at α/36: allowed counts 0, 1, 2, 3, 4, 5, 6 at R = 11, 15, 18, 22, 25,
  28, 31, with every fraction and both p columns; R = 32 allows 6;
- at R = 16: 17/65536 = 2.59e-4 (clears α/k for every k ≤ 20), 137/65536 = 2.09e-3 (k ≤ 11),
  697/65536 = 1.06e-2 (k ≤ 2);
- the BCa floors: 5.0e-5 at z0 = 0; the |z0| limit 0.347 for even R; for odd R the acceleration
  bound 0.0092, 0.0058, 0.0027 and 0.0019 at R = 11, 15, 25 and 31, the floor 8.6e-5 at R = 11,
  and the limits 0.289, 0.311, 0.330 and 0.335;
- q = 10.3070 and s_U / s = 1.20637; the largest bandwidth factor 0.5169; the variance range
  0.9375 to 0.9507; the Monte Carlo standard error 0.0126; 2^-6 = 0.0156; `SETTLE_ABS` × `N_PEND`
  = 80,000 bytes.

Time. `hypotheses.md` states no totals and refers to the proposal's section 9 (lines 809 to 810).
Every row and part of that section reproduces, and so do the totals: on L 158,242.33 s at
R_C = 11 and 174,154.33 s at 31; on W 19,188.56 s and 27,144.56 s; and the five other candidates'
totals in 9.3's text, to the second (the text truncates seconds).

### 2.6 Rules

- **No private library of the author is named.** Every occurrence of "librar", "private" and
  "thesis" in `hypotheses.md` was read. They concern the in-process competitor libraries, the
  analysis code's pinned library versions, Rust's standard library and third-party libraries on W.
- **Dashes.** A count of U+2013 and U+2014 gives 0 in `hypotheses.md` and in `proposal.md`. This
  file was counted the same way before the commit.

## 3. Findings

### FC1. MAJOR. W counts the kernel memory of queued bytes twice, so "whole-system" is not accurate and Q is biased in four Holm cells

Location: `hypotheses.md` WL7 (Kq line 247; Ks lines 249 to 251; T and W lines 256 to 262), B3
(lines 483 to 497), section 10 (lines 736 to 737); `proposal.md` WL7 (lines 683 to 703) and B3
(lines 1076 to 1079).

Evidence:
- **Kq holds each queued skb's truesize.** `tcp_queue_rcv` puts the skb on the receive queue and
  calls `skb_set_owner_r` (net/ipv4/tcp_input.c lines 5532 to 5545), which adds `skb->truesize` to
  `sk_rmem_alloc` (include/net/sock.h lines 2474 to 2481). That is the `r` field of `ss -tm`.
- **truesize includes the skb's own structures.** TCP's send path allocates with
  `alloc_skb_fclone(MAX_TCP_HEADER, ...)` and sets `truesize = SKB_TRUESIZE(skb_end_offset(skb))`
  (net/ipv4/tcp.c lines 926 to 935). `SKB_TRUESIZE(X)` is X plus the aligned sizes of
  `struct sk_buff` and `struct skb_shared_info` (include/linux/skbuff.h lines 273 to 275). The
  payload goes into page fragments, which are not slab memory.
- **Those structures are slab objects.** `alloc_skb_fclone` calls `__alloc_skb` with
  `SKB_ALLOC_FCLONE` (include/linux/skbuff.h line 1434), which takes the struct from the cache
  "skbuff_fclone_cache" (net/core/skbuff.c lines 683 to 686). The linear head, with its
  `skb_shared_info` at the end, comes from `kmalloc_reserve`: the cache "skbuff_small_head" when it
  fits, kmalloc otherwise (lines 606 to 640). The caches are created in `skb_init` (lines 5196 to
  5222).
- **On loopback the receive queue holds these skbs.** `__tcp_transmit_skb` sends a clone, which
  shares the head (`skb_clone`, or `pskb_copy` if the skb is already cloned; net/ipv4/tcp_output.c
  lines 1560 to 1563), and `loopback_xmit` hands it to `__netif_rx` without a copy
  (drivers/net/loopback.c lines 70 to 94).
- **So W counts them twice.** While a byte sits unread, the struct and the linear head of its skb
  are in `Slab`, so in Ks, and again inside Kq. Per queued skb, the overlap is at least the fixed
  part of `SKB_TRUESIZE`, the aligned sizes of `struct sk_buff` and `struct skb_shared_info`;
  their values can be read on L at the code freeze. The payload's page fragments are outside
  `Slab` and are counted once, in Kq, which is right.
- **Who leaves bytes queued** (survey, the "Confirmed at" table and 2.1, 2.3, 2.5, 2.8):
  - Envoy's listener filters peek with `MSG_PEEK`, and tls_inspector never drains, so the bytes
    stay in the socket (envoy v1.39.2 `listener_filter_buffer_impl.cc` lines 40 and 59);
  - nginx's stream preread peeks when nginx does not terminate TLS and the event method is epoll
    with RDHUP (nginx 1.30.5 `ngx_stream_core_module.c` lines 315 to 357). That is the B3
    configuration of Appendix B;
  - HAProxy reads into its channel buffer; sslh reads; the server in replay, the proposed default,
    reads into the handler's buffer.
- **Effect on B3:**
  - the silent case: nothing is queued, Kq is 0 for every system, no effect;
  - the partial-ClientHello case against nginx and Envoy, on epoll and on io_uring: 4 of the 18
    Holm cells. W_comp carries the overlap and W_srv does not, so Q is biased upward, in the
    server's favour;
  - if rule E makes peek the server's default on a backend, the server's W carries the overlap in
    the cells against the competitors that read, and the bias there turns against the server;
  - the secondary B3 cells of the server's other detection mode against its default (section 10)
    compare peek with replay, so the peek side of every such Q carries the overlap.
- **Check 2c therefore fails.** The text presents U, Kq and Ks as disjoint parts of W, with only
  `f` and kernel memory outside `Slab` left out. Kq and Ks overlap. `K_BASE` is not affected, since
  `ophold`'s connections are silent.

Why this is not a wording fix: removing the overlap changes what B3 measures, and B3 is frozen
with the hypotheses. It needs a decision by the coordinator and Alex. Options, none chosen here:
- (a) Read `/proc/slabinfo` at the baseline and at each sample (root on L) and subtract from Ks
  the growth of the skb caches ("skbuff_head_cache", "skbuff_fclone_cache", "skbuff_small_head"),
  so that a queued skb is counted once, in Kq. `K_BASE` then uses the same Ks. Heads that fall
  back to kmalloc stay in Ks, and the text says so.
- (b) Keep W, name the overlap as a third limitation beside `f` and the memory outside `Slab`,
  report Kq beside every cell, and state the direction of the bias in the four cells. This leaves
  a known bias in a confirmatory statistic.
- (c) Another construction that counts each kernel byte once.
Whichever is chosen, the same text goes into the proposal's WL7 and B3 and into its revision log.

### FC2. MINOR. A code-change repeat of the pilot can be decided after the simulation has produced R_C and the resolved list

Location: section 8 step 4, "Reruns" (lines 634 to 640); "A code change after the pilot" (lines
663 to 667).

Evidence: the whole pilot may be repeated after a code change "only before the pilot entry and
before any one-port window of the frozen code". Step 5, the simulation, comes before the entry.
So a repeat can be decided with R_C and the resolved list in view, and the repeat draws them
again. "Had to change" names no condition.

Fix, inside the accepted order: once the simulation of step 5 has run, a code change follows the
rule for a later change (that pilot's outputs go into the entry and stand). Before that, a
code-change repeat needs a change forced by a named failure (a test, a sanitizer record, the gate,
or a crash), recorded with its evidence in the revision log.

### FC3. MINOR. A second code change before the pilot entry is undefined

Location: lines 634 to 640 and 663 to 665.

Evidence: a code change before the entry "needs new records and a new pilot, under the cap
above", and the cap allows one repeat. If the cap is spent, or the repeat is itself stopped by an
infrastructure fault, the text does not say what happens.

Fix: if the cap is spent, the pilot entry is made from the last pilot, cells without P valid
sessions are not resolved, and a further change follows the rule for a later change.

### FC4. MINOR. The timer and split parts have no validity or rerun rule

Location: section 8 step 4, the timer and split parts (lines 623 to 631); 9.2, `G_L`, `G_W` and
`GAP_SPLIT` (lines 701 to 702).

Evidence: G is set by the largest lateness over all of a host's timer runs, and `GAP_SPLIT` by
every replicate. A run in which the server or `opcase` failed has no lateness or no counters. The
text neither excludes such a run nor allows the part alone to run again, and the cap on repeats
names the pilot as a whole.

Fix: a timer run or split replicate whose server or `opcase` failed is excluded and listed in the
pilot entry; the parts run again only with the whole pilot, under its cap.

### FC5. MINOR. Development data can give an indirect one-port against dedicated estimate

Location: section 8 step 2 (lines 607 to 613).

Evidence: before the code freeze, development may time "dedicated mode against anything, and
one-port mode against the competitors". A dedicated window and a one-port window against the same
system, in the same cell, give a one-port against dedicated ratio on pre-freeze code. No rule
feeds it into a pilot output; the only discretionary entry is the code-change repeat of FC2.

Fix, without changing the accepted scope: the revision log lists every development cell in which
both modes were timed against the same system or option, and the methods disclose it. FC2's fix
closes the one path by which it could matter.

### FC6. MINOR. The BCa has no rule for a session without a ratio

Location: B3 (lines 488 to 493); 4.2 (lines 312 to 314).

Evidence: a session whose W_srv is 0 or less "has no ratio and counts against". The sign test
defines this; the BCa, which resamples session values and takes their median, does not. The case
is not expected, since Ks holds both loopback ends of every connection, but it is not excluded by
any rule.

Fix: in both computations such a session takes Q = 0, below every bound.

### FC7. MINOR. Section 10's IOCP accept cells name an undefined default

Location: section 10 (lines 729 to 730); proposal 5.7 (lines 1216 to 1217) and I5.

Evidence: "AcceptEx with a receive buffer, and the posted-buffer form, each against the default
form". `hypotheses.md` does not say that the default AcceptEx form has no receive buffer (the
proposal's I5 does). And if rule E chooses the posted-buffer receive form on IOCP, the second cell
compares the default with itself.

Fix: name the default AcceptEx form, and say that the second cell compares the receive form that
rule E did not choose with the one it chose.

### FC8. MINOR. The secondary cells' resampling order is not a cell order

Location: 4.7, resampling (lines 439 to 443).

Evidence: the secondary cells draw from `SEED_BOOT_S` "in the order of section 10". Section 10
lists groups of cells; within a group (for example the 9 SSH cells or the 3 mixed cells) no order
is given, so the secondary intervals cannot be reproduced from the seed alone.

Fix: within each bullet of section 10, the order of 6.1 (hypothesis, host, backend, protocol), then
system in the order of 2.3.

## 4. Wording items, for the same revision

None changes a rule. They were not applied, because the file is not frozen in this commit.

| Item | Line | Change |
|---|---|---|
| W1 | 22 to 23 | Source the versions of L and W: P2's `hypotheses-round2.md`, section 1 (kernel 7.2.3, clang 22.1.8, go1.27.1 at its line 76; MSVC 19.51.36246 in its records), as the proposal's LB1 and Z1 do. |
| W2 | 30 | α = 0.025: add "as in P2" (P2's section 5 uses family-wise 0.025). |
| W3 | 101 | The 536-byte PROXY v2 limit: "the size both formats were designed to fit (survey 2.4)", as the proposal's I9 says. |
| W4 | 210, 582 | The 99% rule for open-loop windows: label it a design choice, from audit F11. |
| W5 | 282 to 283 | Name the check of one exchange per protocol "the probe", the word that WL7 (line 231) and section 7 (line 572) use. |
| W6 | 287 to 293 | The CPU placement: add "as in P2's H6", the proposal's LB2 source. |
| W7 | 294, 363 to 364 | R_B = R_M = 16: add the reason, "P2's reference, between the D9 minimum and 32, a design choice" (proposal 5.6). |
| W8 | 593 | "last 60 s": add `TCP_TIMEWAIT_LEN` (include/net/tcp.h line 140 at v7.2), as the proposal's I30 does. |
| W9 | 629 | The split part's 16 replicates: add "the hard cases' replicate count" (proposal ST13 step 8). |
| W10 | 877 | Envoy row: "(default 16 KiB, doubling on demand up to 16 KiB)" reads as a contradiction. Write "(default: the maximum, 16 KiB; a smaller initial size doubles on demand up to it)". |

## 5. Verdict

Not frozen. FC1 must be decided and applied in both `hypotheses.md` and `proposal.md` before the
freeze; FC2 to FC8 and W1 to W10 are text for the same revision. After that revision, a short
check of the new B3 text and of FC2's rule suffices; the rest of this check stands.
