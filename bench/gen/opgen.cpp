// opgen's run (opgen.hpp): one worker thread per generator CPU (worker.hpp), each with its own
// epoll loop (bench/loop, as the server's) and its own share of the connection slots or of the
// open-loop schedule. Workers record every exchange with its times; the main thread classifies
// them by the window's two clock readings after the workers have joined, so no count depends on
// when a worker saw the phase change. On Windows (M6b) each worker has a completion port of its
// own (worker_win.cpp), and run() below is the same code: the readings it takes (a worker
// thread's CPU time, the process's, a sleep until a time) have Windows forms under POSIX names.
#include "opgen.hpp"

#if defined(__linux__) || defined(_WIN32)

#if defined(_WIN32)
// Before OpenSSL's headers, which include windows.h on Windows: no min and max macros.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#endif

#include "tls.hpp"
#include "worker.hpp"

#include <algorithm>
#include <cmath>
#include <memory>
#include <thread>

#if defined(_WIN32)
#include <winsock2.h>
#include <windows.h>
#else
#include <pthread.h>
#include <time.h>
#endif

namespace oneport::opgen
{

	namespace
	{

		using detail::now_ns;
		using detail::Control;
		using detail::End;
		using detail::Record;
		using detail::Worker;

#if defined(_WIN32)
		// Windows forms of the readings run() takes, under their POSIX names so that run() is one
		// text on both platforms. A "clock" is a worker thread's handle; the process's is null.
		using clockid_t = HANDLE;
		const HANDLE CLOCK_PROCESS_CPUTIME_ID = nullptr;

		int pthread_getcpuclockid(HANDLE thread, clockid_t* out) noexcept
		{
			*out = thread;
			return thread == nullptr ? -1 : 0;
		}

		/// User plus kernel time of a worker thread (GetThreadTimes) or of the process
		/// (GetProcessTimes), in seconds. Windows counts it in 100 ns units and advances it on the
		/// clock tick, so over a 5 s window it is exact to about 0.3% per thread.
		double clock_s(clockid_t h) noexcept
		{
			FILETIME c{}, e{}, k{}, u{};
			const BOOL ok = h == nullptr ? GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u) : GetThreadTimes(h, &c, &e, &k, &u);
			if (!ok) return 0;
			auto v = [](const FILETIME& f) { return (static_cast<std::uint64_t>(f.dwHighDateTime) << 32) | f.dwLowDateTime; };
			return static_cast<double>(v(k) + v(u)) / 1e7;
		}

		/// Sleeps until `t` (now_ns) on a high-resolution waitable timer: a wait that ends on the
		/// default timer tick would end up to 15.625 ms late (design/w-procedure.md, section 3).
		void sleep_until(std::int64_t t)
		{
			static thread_local HANDLE timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
			for (;;)
			{
				const std::int64_t now = now_ns();
				if (now >= t) return;
				LARGE_INTEGER due;
				due.QuadPart = -std::max<LONGLONG>(1, static_cast<LONGLONG>((t - now) / 100));
				if (timer == nullptr || !SetWaitableTimerEx(timer, &due, 0, nullptr, nullptr, nullptr, 0))
				{
					Sleep(static_cast<DWORD>((t - now + 999'999) / 1'000'000));
					continue;
				}
				WaitForSingleObject(timer, INFINITE);
			}
		}

		/// Winsock 2.2 for the run.
		struct Winsock
		{
			Winsock()
			{
				WSADATA d{};
				ok = ::WSAStartup(MAKEWORD(2, 2), &d) == 0;
			}
			~Winsock()
			{
				if (ok) ::WSACleanup();
			}
			Winsock(const Winsock&) = delete;
			Winsock& operator=(const Winsock&) = delete;
			bool ok = false;
		};
#else
		double clock_s(clockid_t id) noexcept
		{
			timespec ts{};
			if (clock_gettime(id, &ts) != 0) return 0;
			return static_cast<double>(ts.tv_sec) + static_cast<double>(ts.tv_nsec) / 1e9;
		}

		void sleep_until(std::int64_t t)
		{
			for (;;)
			{
				const std::int64_t now = now_ns();
				if (now >= t) return;
				const std::int64_t d = t - now;
				timespec ts{static_cast<time_t>(d / 1'000'000'000), static_cast<long>(d % 1'000'000'000)};
				clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, nullptr);
			}
		}
#endif

	}  // namespace

	Result run(const Options& o, std::ostream* markers)
	{
		Result r;
		if (o.threads == 0 || o.port == 0 || o.k_src == 0)
		{
			r.error = "threads, port and k_src must be at least 1";
			return r;
		}
#if defined(_WIN32)
		const Winsock winsock;
		if (!winsock.ok)
		{
			r.error = "WSAStartup failed";
			return r;
		}
#endif
		tls::Ctx ctx;
		if (o.proto == Proto::tls)
		{
			try
			{
				ctx = tls::client_ctx();
			}
			catch (const std::exception& e)
			{
				r.error = e.what();
				return r;
			}
		}
		Options opts = o;
		if (opts.probe)
		{
			opts.threads = 1;
			opts.rate = 0;
			opts.load = Load::churn;
		}
		Control ctl;
		std::vector<std::unique_ptr<Worker>> workers;
		for (unsigned k = 0; k < opts.threads; ++k) workers.push_back(std::make_unique<Worker>(opts, ctl, k, ctx.get()));
		ctl.origin = now_ns();
		std::vector<std::thread> threads;
		for (auto& w : workers) threads.emplace_back([&w] { w->run(); });
		std::vector<clockid_t> clocks(threads.size());
		for (std::size_t k = 0; k < threads.size(); ++k)
		{
			if (pthread_getcpuclockid(threads[k].native_handle(), &clocks[k]) != 0)
			{
				// Without each worker's own clock the generator rule would read nothing: fail the run.
				ctl.phase.store(2, std::memory_order_release);
				for (auto& t : threads) t.join();
				r.error = "pthread_getcpuclockid failed";
				return r;
			}
		}
		std::vector<double> cpu0(threads.size());
		double proc0 = 0;
		if (!opts.probe)
		{
			sleep_until(ctl.origin + opts.warmup.count());
			for (std::size_t k = 0; k < threads.size(); ++k) cpu0[k] = clock_s(clocks[k]);
			proc0 = clock_s(CLOCK_PROCESS_CPUTIME_ID);
			r.start_ns = now_ns();
			if (markers != nullptr) *markers << "MEASURE_START " << r.start_ns << std::endl;
			sleep_until(r.start_ns + opts.duration.count());
			r.end_ns = now_ns();
			r.thread_cpu_s.resize(threads.size());
			for (std::size_t k = 0; k < threads.size(); ++k) r.thread_cpu_s[k] = clock_s(clocks[k]) - cpu0[k];
			r.process_cpu_s = clock_s(CLOCK_PROCESS_CPUTIME_ID) - proc0;
			ctl.t_end.store(r.end_ns, std::memory_order_release);
			ctl.phase.store(1, std::memory_order_release);
			if (markers != nullptr) *markers << "MEASURE_END " << r.end_ns << std::endl;
			// The drain: each worker ends by itself once its exchanges finish or time out.
			const std::int64_t limit = r.end_ns + opts.timeout.count() + 400'000'000;
			while (ctl.finished.load(std::memory_order_acquire) < threads.size() && now_ns() < limit) sleep_until(now_ns() + 2'000'000);
			ctl.phase.store(2, std::memory_order_release);
		}
		for (auto& t : threads) t.join();
		for (const auto& w : workers)
		{
			if (!w->error().empty())
			{
				r.error = "worker: " + w->error();
				return r;
			}
		}
		r.wall_s = static_cast<double>(r.end_ns - r.start_ns) / 1e9;
		for (const double s : r.thread_cpu_s)
		{
			r.cpu_s += s;
			if (r.wall_s > 0) r.max_thread_cpu_pct = std::max(r.max_thread_cpu_pct, 100.0 * s / r.wall_s);
		}
		if (r.wall_s > 0) r.cpu_pct = 100.0 * r.cpu_s / (r.wall_s * static_cast<double>(opts.threads));
		// Classify every record by the window's two readings.
		std::vector<std::uint64_t> ttfb;
		std::vector<std::uint64_t> ttfb_connect;
		std::vector<std::uint64_t> exch;
		std::vector<std::uint64_t> lag;
		const bool open = opts.rate > 0;
		for (const auto& w : workers)
		{
			r.peak_concurrency = std::max(r.peak_concurrency, w->peak());
			r.due_unfinished += w->unfinished();
			if (opts.probe)
			{
				r.probe_detail = w->probe_detail;
				for (const Record& x : w->records())
				{
					if (x.how == End::completed) ++r.measure.completed;
					else detail::count(r.measure.errors, x.how);
				}
				r.measure.connects += w->connects();
				continue;
			}
			for (const Record& x : w->records())
			{
				if (x.how == End::completed) ++r.all_completed;
				// Closed loop: by when it ended; open loop: by when it fell due.
				const std::int64_t key = open ? x.due : x.end;
				if (key >= r.end_ns) continue;  // after the window: drained, not counted
				const bool in_window = key >= r.start_ns;
				Phase& ph = in_window ? r.measure : r.warmup;
				if (x.how == End::completed) ++ph.completed;
				else detail::count(ph.errors, x.how);
				if (!in_window) continue;
				if (open)
				{
					if (x.how == End::completed) ++r.due_completed;
					else detail::count(r.due_errors, x.how);
				}
				if (x.how != End::completed) continue;
				const std::int64_t from = open ? x.due : x.begin;
				if (x.first >= 0)
				{
					ttfb.push_back(static_cast<std::uint64_t>(x.first - from));
					if (open) ttfb_connect.push_back(static_cast<std::uint64_t>(x.first - x.begin));
				}
				exch.push_back(static_cast<std::uint64_t>(x.end - from));
				if (open) lag.push_back(static_cast<std::uint64_t>(std::max<std::int64_t>(0, x.begin - x.due)));
			}
			r.measure.connects += w->connects();
		}
		if (open)
		{
			// Every exchange of the schedule due in the window, started or not: the 99% rule's
			// denominator (WL2), so an exchange the generator never started counts against it.
			const double step = 1e9 / opts.rate;
			const auto first = static_cast<std::uint64_t>(std::max(0.0, std::floor(static_cast<double>(r.start_ns - ctl.origin) / step) - 2));
			for (std::uint64_t n = first;; ++n)
			{
				const auto due = ctl.origin + static_cast<std::int64_t>(std::llround(static_cast<double>(n) * step));
				if (due >= r.end_ns) break;
				if (due >= r.start_ns) ++r.due;
			}
		}
		r.ttfb = quantiles(std::move(ttfb));
		r.ttfb_connect = quantiles(std::move(ttfb_connect));
		r.exchange = quantiles(std::move(exch));
		r.issue_lag = quantiles(std::move(lag));
		r.ok = true;
		return r;
	}

}  // namespace oneport::opgen

#else

namespace oneport::opgen
{
	Result run(const Options&, std::ostream*)
	{
		Result r;
		r.error = "opgen runs on Linux and Windows only";
		return r;
	}
}  // namespace oneport::opgen

#endif
