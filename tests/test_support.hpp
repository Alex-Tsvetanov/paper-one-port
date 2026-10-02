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
	void register_server_tests(Registry& r);  // Linux only; empty elsewhere

	/// Runs hard case `hc` on the epoll backend with in-process dispatch in `mode` ("replay" or
	/// "peek"). Returns the process exit code.
	int run_case(int hc, std::string_view mode);

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
