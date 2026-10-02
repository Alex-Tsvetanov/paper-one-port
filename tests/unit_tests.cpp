// The oneport test suite, one test per process:
//
//   oneport_tests flags <case>              the flag parser (bench/server/config.cpp)
//   oneport_tests loop <backend> <case>     the event loop (bench/loop) on one compiled backend
//   oneport_tests test <name>               detect.*, http.* (tests/*_tests.cpp)
//
// Exit 0 and "PASS: ..." on success; exit 1 and "FAIL: <file>:<line>: <reason>" on a failed check;
// exit 2 on a usage error. The flag tests pass an explicit platform to the parser, so they run
// alike on every host.
#include "config.hpp"
#include "oneport/loop.hpp"
#include "test_support.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <expected>
#include <functional>
#include <initializer_list>
#include <map>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace
{

	using namespace std::chrono_literals;
	using Clock = std::chrono::steady_clock;
	using oneport::Platform;

	using oneport::test::Result;

	// ---- flags ----

	using Args = std::vector<std::string_view>;

	std::expected<oneport::Command, std::string> parse(const Args& args, Platform platform)
	{
		return oneport::parse_args(args, platform);
	}

	Args base(std::string_view backend = "epoll")
	{
		return {"--mode", "one-port", "--detect", "replay", "--dispatch", "inproc", "--backend", backend};
	}

	Args with(Args args, std::initializer_list<std::string_view> more)
	{
		args.insert(args.end(), more);
		return args;
	}

	Args without(const Args& args, std::string_view flag)
	{
		Args out;
		for (std::size_t i = 0; i < args.size(); ++i)
		{
			if (args[i] == flag)
			{
				++i;  // its value
				continue;
			}
			out.push_back(args[i]);
		}
		return out;
	}

	bool refused_with(const Args& args, Platform platform, std::string_view needle)
	{
		const auto r = parse(args, platform);
		return !r && r.error().find(needle) != std::string::npos;
	}

	bool has_line(const oneport::Config& c, std::string_view line)
	{
		return oneport::describe(c).find(std::string(line) + "\n") != std::string::npos;
	}

	Result flags_arms()
	{
		const char* modes[] = {"one-port", "dedicated", "stub"};
		const char* detects[] = {"replay", "peek"};
		const char* dispatches[] = {"inproc", "relay"};
		const char* linux_backends[] = {"epoll", "io_uring"};
		for (const char* m : modes)
			for (const char* d : detects)
				for (const char* p : dispatches)
				{
					for (const char* b : linux_backends)
					{
						const Args a{"--mode", m, "--detect", d, "--dispatch", p, "--backend", b};
						const auto r = parse(a, Platform::Linux);
						CHECK(r.has_value(), m << " " << d << " " << p << " " << b << " refused: " << r.error());
						CHECK(r->kind == oneport::Command::serve, "a plain arm is a serve command");
						CHECK(oneport::token(r->config.mode) == m, "mode " << m);
						CHECK(oneport::token(r->config.detect) == d, "detect " << d);
						CHECK(oneport::token(r->config.dispatch) == p, "dispatch " << p);
						CHECK(oneport::token(r->config.backend) == b, "backend " << b);
						CHECK(has_line(r->config, std::string("mode ") + m), "describe echoes mode " << m);
						CHECK(has_line(r->config, std::string("backend ") + b), "describe echoes backend " << b);
					}
					const Args a{"--mode", m, "--detect", d, "--dispatch", p, "--backend", "IOCP"};
					const auto r = parse(a, Platform::Windows);
					if (std::string_view(p) == "inproc")
					{
						CHECK(r.has_value(), m << " " << d << " inproc IOCP refused: " << r.error());
						CHECK(oneport::token(r->config.backend) == "IOCP", "backend IOCP");
					}
					else
					{
						CHECK(!r.has_value(), m << " " << d << " relay IOCP accepted");
					}
				}
		return std::nullopt;
	}

	Result flags_required()
	{
		const Args full = base();
		for (const std::string_view f : {"--mode", "--detect", "--dispatch", "--backend"})
		{
			CHECK(refused_with(without(full, f), Platform::Linux, "missing " + std::string(f) + ":"), "no " << f << " is refused");
		}
		CHECK(refused_with({}, Platform::Linux, "missing --mode, --detect, --dispatch, --backend: the four arm flags have no default"),
		      "an empty command line names all four");
		CHECK(refused_with({"--print-config"}, Platform::Linux, "missing --mode"), "--print-config alone is refused");
		return std::nullopt;
	}

	Result flags_spellings()
	{
		const std::pair<std::string_view, std::string_view> wrong[] = {
			{"--mode", "oneport"},     {"--mode", "one_port"},     {"--mode", "One-port"},  {"--mode", "Dedicated"},
			{"--detect", "Replay"},    {"--detect", "peeking"},    {"--dispatch", "in-process"}, {"--dispatch", "Relay"},
			{"--backend", "iocp"},     {"--backend", "uring"},     {"--backend", "IO_URING"},    {"--backend", "Epoll"},
			{"--iocp-receive", "zero"}, {"--relay-copy", "user"},  {"--proxy", "yes"},           {"--fallback", "smtp"},
			{"--fallback", "ssh"},     {"--listener", "reuse"},
		};
		for (const auto& [flag, value] : wrong)
		{
			Args a = without(base(), flag);
			a.push_back(flag);
			a.push_back(value);
			CHECK(refused_with(a, Platform::Linux, std::string(flag) + ": '" + std::string(value) + "' is not one of "),
			      flag << " " << value << " is refused as a spelling");
		}
		CHECK(refused_with(with(without(base(), "--backend"), {"--backend", "iocp"}), Platform::Windows, "is not one of epoll, io_uring, IOCP"),
		      "the error lists the backend spellings");
		return std::nullopt;
	}

	Result flags_unknown()
	{
		CHECK(refused_with(with(without(base(), "--detect"), {"--detection", "replay"}), Platform::Linux, "unknown flag '--detection'"),
		      "--detection is not a spelling of --detect");
		CHECK(refused_with(with(base(), {"--Mode", "one-port"}), Platform::Linux, "unknown flag '--Mode'"), "flags are case-sensitive");
		CHECK(refused_with(with(base(), {"--mode=one-port"}), Platform::Linux, "unknown flag '--mode=one-port'"), "no --flag=value form");
		CHECK(refused_with(with(base(), {"-m"}), Platform::Linux, "unexpected argument '-m'"), "no short flags");
		CHECK(refused_with(with(base(), {"extra"}), Platform::Linux, "unexpected argument 'extra'"), "no positional arguments");
		return std::nullopt;
	}

	Result flags_duplicates()
	{
		CHECK(refused_with(with(base(), {"--mode", "dedicated"}), Platform::Linux, "--mode is given twice"), "a second --mode");
		CHECK(refused_with(with(base(), {"--workers", "1", "--workers", "1"}), Platform::Linux, "--workers is given twice"),
		      "a second --workers, even with the same value");
		CHECK(refused_with(with(base(), {"--print-config", "--print-config"}), Platform::Linux, "--print-config is given twice"),
		      "a second --print-config");
		return std::nullopt;
	}

	Result flags_missing_value()
	{
		CHECK(refused_with(with(base(), {"--port"}), Platform::Linux, "--port needs a value"), "a flag at the end");
		CHECK(refused_with({"--mode", "--detect", "replay", "--dispatch", "inproc", "--backend", "epoll"}, Platform::Linux,
		                   "--mode needs a value"),
		      "a flag followed by a flag");
		return std::nullopt;
	}

	Result flags_defaults()
	{
		const auto r = parse(base(), Platform::Linux);
		CHECK(r.has_value(), "the base arm parses: " << r.error());
		const std::string want = "mode one-port\n"
		                         "detect replay\n"
		                         "dispatch inproc\n"
		                         "backend epoll\n"
		                         "iocp-receive zero-byte\n"
		                         "relay-copy user-space\n"
		                         "proxy off\n"
		                         "fallback none\n"
		                         "listener shared\n"
		                         "workers 1\n"
		                         "port unset\n"
		                         "t-fb-ms 3000\n"
		                         "t-dec-ms 3000\n"
		                         "t-hdr-ms 3000\n";
		const std::string got = oneport::describe(r->config);
		CHECK(got == want, "describe() of the defaults is\n" << got);
		return std::nullopt;
	}

	Result flags_options()
	{
		const Args a = with(base(), {"--iocp-receive", "posted", "--relay-copy", "splice", "--proxy", "on", "--fallback", "SMTP",
		                             "--listener", "reuseport", "--workers", "2", "--port", "8080", "--t-fb-ms", "60000",
		                             "--t-dec-ms", "60000", "--t-hdr-ms", "250"});
		const auto r = parse(a, Platform::Linux);
		CHECK(r.has_value(), "every option parses: " << r.error());
		for (const char* line : {"iocp-receive posted", "relay-copy splice", "proxy on", "fallback SMTP", "listener reuseport", "workers 2",
		                         "port 8080", "t-fb-ms 60000", "t-dec-ms 60000", "t-hdr-ms 250"})
		{
			CHECK(has_line(r->config, line), "describe echoes '" << line << "'");
		}
		const auto s = parse(with(base(), {"--fallback", "SSH"}), Platform::Linux);
		CHECK(s.has_value() && has_line(s->config, "fallback SSH"), "SSH is a fallback");
		return std::nullopt;
	}

	Result flags_numbers()
	{
		for (const std::string_view v : {"0", "-1", "+1", "1x", " 1", "1.0", "", "4294967296"})
		{
			CHECK(refused_with(with(base(), {"--workers", v}), Platform::Linux, "--workers: '"), "--workers '" << v << "' is refused");
		}
		CHECK(parse(with(base(), {"--workers", "4294967295"}), Platform::Linux).has_value(), "the largest worker count parses");
		for (const std::string_view v : {"0", "65536", "-1", "80a"})
		{
			CHECK(refused_with(with(base(), {"--port", v}), Platform::Linux, "is not a port from 1 to 65535"), "--port '" << v << "' is refused");
		}
		for (const std::string_view v : {"1", "65535"})
		{
			CHECK(parse(with(base(), {"--port", v}), Platform::Linux).has_value(), "--port " << v << " parses");
		}
		for (const std::string_view flag : {"--t-fb-ms", "--t-dec-ms", "--t-hdr-ms"})
		{
			for (const std::string_view v : {"0", "-5", "1.5", "3s", "9223372036854775808"})
			{
				CHECK(refused_with(with(base(), {flag, v}), Platform::Linux, "is not a whole number of milliseconds"),
				      flag << " '" << v << "' is refused");
			}
			CHECK(parse(with(base(), {flag, "1"}), Platform::Linux).has_value(), flag << " 1 parses");
			CHECK(parse(with(base(), {flag, "9223372036854775807"}), Platform::Linux).has_value(), flag << " at the int64 limit parses");
		}
		return std::nullopt;
	}

	Result flags_combinations()
	{
		CHECK(refused_with(with(without(base("IOCP"), "--dispatch"), {"--dispatch", "relay"}), Platform::Windows, "the relay is Linux only"),
		      "relay on IOCP is refused");
		CHECK(refused_with(with(base("IOCP"), {"--listener", "reuseport"}), Platform::Windows, "--listener reuseport needs epoll or io_uring"),
		      "reuseport on IOCP is refused");
		for (const std::string_view b : {"epoll", "io_uring"})
		{
			CHECK(parse(with(without(base(b), "--dispatch"), {"--dispatch", "relay", "--relay-copy", "splice"}), Platform::Linux).has_value(),
			      "relay with splice on " << b << " parses");
			CHECK(parse(with(base(b), {"--listener", "reuseport", "--workers", "2"}), Platform::Linux).has_value(),
			      "reuseport on " << b << " parses");
		}
		CHECK(parse(with(base("IOCP"), {"--iocp-receive", "posted"}), Platform::Windows).has_value(), "the posted form on IOCP parses");
		return std::nullopt;
	}

	Result flags_platform()
	{
		CHECK(refused_with(base("IOCP"), Platform::Linux, "--backend IOCP is not compiled on this platform (Linux compiles epoll and io_uring)"),
		      "Linux refuses IOCP");
		CHECK(refused_with(base("epoll"), Platform::Windows, "--backend epoll is not compiled on this platform (Windows compiles IOCP)"),
		      "Windows refuses epoll");
		CHECK(refused_with(base("io_uring"), Platform::Windows, "--backend io_uring is not compiled on this platform"),
		      "Windows refuses io_uring");
		const auto here = parse(base(oneport::kThisPlatform == Platform::Linux ? "epoll" : "IOCP"), oneport::kThisPlatform);
		CHECK(here.has_value(), "the default platform argument is this host's: " << here.error());
		return std::nullopt;
	}

	Result flags_dedicated_echoes()
	{
		for (const std::string_view m : {"dedicated", "stub"})
		{
			const auto r = parse(with(without(without(base(), "--mode"), "--detect"), {"--mode", m, "--detect", "peek", "--fallback", "SMTP"}),
			                     Platform::Linux);
			CHECK(r.has_value(), m << " with --detect peek parses: " << r.error());
			CHECK(has_line(r->config, "detect peek") && has_line(r->config, "fallback SMTP"), m << " echoes the flags it does not use");
		}
		return std::nullopt;
	}

	Result flags_help()
	{
		const auto r = parse({"--help"}, Platform::Linux);
		CHECK(r.has_value() && r->kind == oneport::Command::help, "--help alone is a help command");
		const auto mixed = parse(with(base(), {"--help"}), Platform::Linux);
		CHECK(mixed.has_value() && mixed->kind == oneport::Command::help, "--help after an arm is a help command");
		const std::string text = oneport::usage();
		for (const char* f : {"--mode", "--detect", "--dispatch", "--backend", "--iocp-receive", "--relay-copy", "--proxy", "--fallback",
		                      "--listener", "--workers", "--port", "--t-fb-ms", "--t-dec-ms", "--t-hdr-ms", "--print-config", "--help"})
		{
			CHECK(text.find(f) != std::string::npos, "the usage names " << f);
		}
		for (const char* v : {"one-port, dedicated, stub", "replay, peek", "inproc, relay", "epoll, io_uring, IOCP"})
		{
			CHECK(text.find(v) != std::string::npos, "the usage lists " << v);
		}
		return std::nullopt;
	}

	Result flags_print_config()
	{
		const auto p = parse(with(base(), {"--print-config"}), Platform::Linux);
		CHECK(p.has_value() && p->kind == oneport::Command::print_config, "--print-config is a print command");
		const auto s = parse(base(), Platform::Linux);
		CHECK(s.has_value() && s->kind == oneport::Command::serve, "without it the command serves");
		return std::nullopt;
	}

	// ---- loop ----

	/// Runs `body` on a new thread and waits for it at most `limit`. If the thread is still
	/// running then, the test fails at once with _Exit: nothing is destroyed under a thread that
	/// is blocked in a wait.
	Result on_thread(std::function<Result()> body, std::chrono::milliseconds limit)
	{
		std::mutex m;
		std::condition_variable cv;
		bool done = false;
		Result result;
		std::thread t([&] {
			Result r;
			try
			{
				r = body();
			}
			catch (const std::exception& e)
			{
				r = std::string("exception on the worker: ") + e.what();
			}
			{
				std::lock_guard lock(m);
				result = std::move(r);
				done = true;
			}
			cv.notify_all();
		});
		std::unique_lock lock(m);
		if (!cv.wait_for(lock, limit, [&] { return done; }))
		{
			std::printf("FAIL: the worker did not return within %lld ms\n", static_cast<long long>(limit.count()));
			std::fflush(stdout);
			std::_Exit(1);
		}
		lock.unlock();
		t.join();
		return result;
	}

	template <class Loop>
	Result loop_construct()
	{
		{
			Loop never_started;
		}
		Loop loop;
		loop.start();
		CHECK(!loop.stopped() && loop.passes() == 0, "a new loop is not stopped and has no pass");
		return std::nullopt;
	}

	template <class Loop>
	Result loop_bounded_wait()
	{
		Loop loop;
		loop.start();
		const auto bound = 20ms;
		const auto t0 = Clock::now();
		loop.wait(std::chrono::nanoseconds(bound));
		const auto elapsed = Clock::now() - t0;
		CHECK(loop.passes() == 1, "one wait is one pass");
#if defined(__linux__)
		// Both Linux waits take the bound as a timespec on the monotonic clock and do not end early.
		CHECK(elapsed >= bound, "a bounded wait ended early, after "
		                            << std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count() << " us");
#else
		(void)elapsed;  // a Windows wait can end up to one timer tick early (proposal I13)
#endif
		return std::nullopt;
	}

	template <class Loop>
	Result loop_zero_wait()
	{
		Loop loop;
		loop.start();
		for (int i = 0; i < 3; ++i) loop.wait(std::chrono::nanoseconds(0));
		CHECK(loop.passes() == 3, "three zero waits are three passes");
		return std::nullopt;
	}

	template <class Loop>
	Result loop_stop_wakes_blocked()
	{
		Loop loop;
		std::atomic<bool> waiting{false};
		std::thread stopper([&] {
			while (!waiting.load()) std::this_thread::sleep_for(1ms);
			std::this_thread::sleep_for(50ms);  // let the worker block
			loop.stop();
		});
		const Result r = on_thread(
			[&]() -> Result {
				loop.start();  // the worker is the issuer on io_uring
				waiting.store(true);
				loop.wait(std::nullopt);
				CHECK(loop.stopped(), "the blocking wait returned without stop()");
				return std::nullopt;
			},
			10000ms);
		stopper.join();
		return r;
	}

	template <class Loop>
	Result loop_stop_before_start()
	{
		Loop loop;
		loop.stop();
		return on_thread(
			[&]() -> Result {
				loop.start();
				loop.wait(std::nullopt);
				CHECK(loop.stopped() && loop.passes() == 1, "a wait after stop() returns at once");
				return std::nullopt;
			},
			10000ms);
	}

	template <class Loop>
	Result loop_stop_is_sticky()
	{
		Loop loop;
		return on_thread(
			[&]() -> Result {
				loop.start();
				loop.stop();
				for (int i = 0; i < 3; ++i) loop.wait(std::nullopt);
				loop.stop();
				loop.wait(std::nullopt);
				CHECK(loop.passes() == 4, "every wait after stop() returns at once");
				return std::nullopt;
			},
			10000ms);
	}

	template <class Loop>
	Result loop_start_twice_refused()
	{
		Loop loop;
		loop.start();
		bool refused = false;
		try
		{
			loop.start();
		}
		catch (const std::logic_error&)
		{
			refused = true;
		}
		CHECK(refused, "a second start() was accepted");
		return std::nullopt;
	}

	template <class Loop>
	Result loop_wait_before_start_refused()
	{
		Loop loop;
		bool refused = false;
		try
		{
			loop.wait(std::chrono::nanoseconds(0));
		}
		catch (const std::logic_error&)
		{
			refused = true;
		}
		CHECK(refused, "wait() before start() was accepted");
		CHECK(loop.passes() == 0, "a refused wait is not a pass");
		return std::nullopt;
	}

	template <class Loop>
	Result loop_negative_bound_refused()
	{
		Loop loop;
		loop.start();
		bool refused = false;
		try
		{
			loop.wait(std::chrono::nanoseconds(-1));
		}
		catch (const std::invalid_argument&)
		{
			refused = true;
		}
		CHECK(refused, "a negative bound was accepted");
		CHECK(loop.passes() == 0, "a refused wait is not a pass");
		return std::nullopt;
	}

	template <class Loop>
	std::map<std::string, std::function<Result()>> loop_tests()
	{
		return {
			{"construct", loop_construct<Loop>},
			{"bounded_wait", loop_bounded_wait<Loop>},
			{"zero_wait", loop_zero_wait<Loop>},
			{"stop_wakes_blocked", loop_stop_wakes_blocked<Loop>},
			{"stop_before_start", loop_stop_before_start<Loop>},
			{"stop_is_sticky", loop_stop_is_sticky<Loop>},
			{"start_twice_refused", loop_start_twice_refused<Loop>},
			{"wait_before_start_refused", loop_wait_before_start_refused<Loop>},
			{"negative_bound_refused", loop_negative_bound_refused<Loop>},
		};
	}

	std::map<std::string, std::function<Result()>> flag_tests()
	{
		return {
			{"arms", flags_arms},
			{"required", flags_required},
			{"spellings", flags_spellings},
			{"unknown", flags_unknown},
			{"duplicates", flags_duplicates},
			{"missing_value", flags_missing_value},
			{"defaults", flags_defaults},
			{"options", flags_options},
			{"numbers", flags_numbers},
			{"combinations", flags_combinations},
			{"platform", flags_platform},
			{"dedicated_echoes", flags_dedicated_echoes},
			{"help", flags_help},
			{"print_config", flags_print_config},
		};
	}

	std::optional<std::map<std::string, std::function<Result()>>> loop_tests_for(std::string_view backend)
	{
#if defined(__linux__)
		if (backend == "epoll") return loop_tests<oneport::loop::EpollLoop>();
		if (backend == "io_uring") return loop_tests<oneport::loop::UringLoop>();
#elif defined(_WIN32)
		if (backend == "IOCP") return loop_tests<oneport::loop::IocpLoop>();
#endif
		return std::nullopt;
	}

	int usage_error(const char* what)
	{
		std::fprintf(stderr,
		             "oneport_tests: %s\nusage: oneport_tests flags <case> | loop <backend> <case> | test <name>"
		             "\n",
		             what);
		return 2;
	}

}  // namespace

int main(int argc, char** argv)
{
	const std::vector<std::string_view> a(argv + 1, argv + argc);
	std::map<std::string, std::function<Result()>> tests;
	std::string name;
	std::string test_case;
	if (a.size() == 2 && a[0] == "test")
	{
		oneport::test::Registry registry;
		oneport::test::register_detect_tests(registry);
		oneport::test::register_http_tests(registry);
		const auto it = registry.find(a[1]);
		if (it == registry.end()) return usage_error("no such test");
		Result r;
		try
		{
			r = it->second();
		}
		catch (const std::exception& e)
		{
			r = std::string("unexpected exception: ") + e.what();
		}
		if (r)
		{
			std::printf("FAIL: %s: %s\n", std::string(a[1]).c_str(), r->c_str());
			return 1;
		}
		std::printf("PASS: %s\n", std::string(a[1]).c_str());
		return 0;
	}
	if (a.size() == 2 && a[0] == "flags")
	{
		tests = flag_tests();
		name = "flags.";
		test_case = std::string(a[1]);
	}
	else if (a.size() == 3 && a[0] == "loop")
	{
		auto t = loop_tests_for(a[1]);
		if (!t) return usage_error("this platform does not compile that backend");
		tests = std::move(*t);
		name = "loop." + std::string(a[1]) + ".";
		test_case = std::string(a[2]);
	}
	else
	{
		return usage_error("bad arguments");
	}
	const auto it = tests.find(test_case);
	if (it == tests.end()) return usage_error("no such test");
	name += test_case;
	Result r;
	try
	{
		r = it->second();
	}
	catch (const std::exception& e)
	{
		r = std::string("unexpected exception: ") + e.what();
	}
	if (r)
	{
		std::printf("FAIL: %s: %s\n", name.c_str(), r->c_str());
		return 1;
	}
	std::printf("PASS: %s\n", name.c_str());
	return 0;
}
