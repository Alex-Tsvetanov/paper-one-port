// Shared pieces of the oneport test suite: one test per process, "PASS: ..." and exit 0, or
// "FAIL: <file>:<line>: <reason>" and exit 1 (tests/unit_tests.cpp holds main).
//
// No test prints bytes it received or sent, only counts, lengths and printable first lines: the
// sanitizer gate scans the test output for report lines, and a received byte string must never
// be able to match that pattern.
#pragma once

#include <functional>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>

namespace oneport::test
{

	/// nullopt: the test passed; otherwise where and why it failed.
	using Result = std::optional<std::string>;
	using Registry = std::map<std::string, std::function<Result()>, std::less<>>;

	void register_detect_tests(Registry& r);
	void register_http_tests(Registry& r);
	void register_server_tests(Registry& r);   // Linux only; empty elsewhere
	void register_apps_tests(Registry& r);     // pure, every platform
	void register_clienthello_tests(Registry& r);  // pure, every platform
	void register_handler_tests(Registry& r);  // Linux with TLS only; empty elsewhere
	void register_relay_tests(Registry& r);    // Linux with TLS only; empty elsewhere
#if defined(_WIN32)
	void register_iocp_tests(Registry& r);     // Windows with TLS (M6a): the IOCP pins and the server on IOCP
#endif

	/// Runs hard case `hc` on `backend` ("epoll" or "io_uring") with `dispatch` ("inproc" or
	/// "relay") in detection mode `mode` ("replay" or "peek"). Returns the process exit code.
	int run_case(int hc, std::string_view backend, std::string_view dispatch, std::string_view mode);

	/// The path of the oneport binary, for the binary's smoke test (argv of the test process).
	inline std::string& binary_path()
	{
		static std::string path;
		return path;
	}

}  // namespace oneport::test

#define CHECK(cond, msg)                                                       \
	do                                                                         \
	{                                                                          \
		if (!(cond))                                                           \
		{                                                                      \
			std::ostringstream check_msg_;                                     \
			check_msg_ << __FILE__ << ":" << __LINE__ << ": " << msg;          \
			return ::oneport::test::Result(check_msg_.str());                  \
		}                                                                      \
	} while (false)
