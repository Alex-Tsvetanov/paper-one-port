// oneport: the paper's own one-port server (design/proposal.md, section 2).
//
// --print-config prints the configuration and exits 0. Serving: the epoll backend with in-process
// dispatch in one-port and dedicated mode; any other arm exits with kExitNotServed and says which
// milestone serves it. The server listens on 127.0.0.1, prints one "listening" line per
// port, and runs until SIGINT or SIGTERM; it then prints its counters (proposal I29) and exits 0.
// This file does not read the mode (proposal I21): the listener setup does.
//
// On Windows (M6a) the server runs until Ctrl+C or Ctrl+Break reaches its console, or until the
// named event "Local\oneport-stop-<pid>" is set: a harness or a test that started it stops it so,
// without sharing its console (a design choice of M6a).
#include "config.hpp"
#include "server.hpp"

#include <cstdio>
#include <exception>
#include <string_view>
#include <vector>

#if defined(__linux__)
#include <csignal>
#include <pthread.h>
#elif defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <string>
#endif

namespace
{

	constexpr int kExitUsage = 2;
	constexpr int kExitNotServed = 3;
	constexpr int kExitFailed = 1;

}  // namespace

int main(int argc, char** argv)
{
	const std::vector<std::string_view> args(argv + 1, argv + argc);
	const auto cmd = oneport::parse_args(args);
	if (!cmd)
	{
		std::fprintf(stderr, "oneport: %s\n(oneport --help lists the flags)\n", cmd.error().c_str());
		return kExitUsage;
	}
	switch (cmd->kind)
	{
		case oneport::Command::help: std::fputs(oneport::usage().c_str(), stdout); return 0;
		case oneport::Command::print_config: std::fputs(oneport::describe(cmd->config).c_str(), stdout); return 0;
		case oneport::Command::serve: break;
	}
	if (const auto why = oneport::server::not_served(cmd->config))
	{
		std::fprintf(stderr, "oneport: not served yet: %s; the flags parsed as:\n%s", why->c_str(), oneport::describe(cmd->config).c_str());
		return kExitNotServed;
	}
#if defined(__linux__)
	// Block the stop signals in every thread; this thread waits for them.
	sigset_t stop_signals;
	sigemptyset(&stop_signals);
	sigaddset(&stop_signals, SIGINT);
	sigaddset(&stop_signals, SIGTERM);
	pthread_sigmask(SIG_BLOCK, &stop_signals, nullptr);
	std::signal(SIGPIPE, SIG_IGN);
	try
	{
		oneport::server::Server server(cmd->config);
		server.start();
		const auto ports = server.ports();
		const auto& listeners = server.listeners();
		for (std::size_t i = 0; i < ports.size(); ++i)
		{
			std::printf("oneport: listening %s 127.0.0.1:%u\n", listeners[i].name.c_str(), static_cast<unsigned>(ports[i]));
		}
		std::printf("oneport: connection state %zu bytes\n", oneport::server::Server::conn_state_bytes());
		std::fflush(stdout);
		int sig = 0;
		sigwait(&stop_signals, &sig);
		server.stop();
		std::fputs(oneport::server::describe(server.totals()).c_str(), stdout);
		std::fflush(stdout);
		if (const auto error = server.error())
		{
			std::fprintf(stderr, "oneport: %s\n", error->c_str());
			return kExitFailed;
		}
		return 0;
	}
	catch (const std::exception& e)
	{
		std::fprintf(stderr, "oneport: %s\n", e.what());
		return kExitFailed;
	}
#elif defined(_WIN32)
	// The stop event, named by this process's id; the console handler sets it too.
	const std::wstring stop_name = L"Local\\oneport-stop-" + std::to_wstring(GetCurrentProcessId());
	static HANDLE stop_event = nullptr;
	stop_event = CreateEventW(nullptr, TRUE, FALSE, stop_name.c_str());
	if (stop_event == nullptr)
	{
		std::fprintf(stderr, "oneport: CreateEvent failed (%lu)\n", GetLastError());
		return kExitFailed;
	}
	SetConsoleCtrlHandler(
		[](DWORD) -> BOOL {
			SetEvent(stop_event);
			return TRUE;
		},
		TRUE);
	try
	{
		oneport::server::Server server(cmd->config);
		server.start();
		const auto ports = server.ports();
		const auto& listeners = server.listeners();
		for (std::size_t i = 0; i < ports.size(); ++i)
		{
			std::printf("oneport: listening %s 127.0.0.1:%u\n", listeners[i].name.c_str(), static_cast<unsigned>(ports[i]));
		}
		std::printf("oneport: connection state %zu bytes\n", oneport::server::Server::conn_state_bytes());
		std::fflush(stdout);
		WaitForSingleObject(stop_event, INFINITE);
		server.stop();
		std::fputs(oneport::server::describe(server.totals()).c_str(), stdout);
		std::fflush(stdout);
		if (const auto error = server.error())
		{
			std::fprintf(stderr, "oneport: %s\n", error->c_str());
			return kExitFailed;
		}
		return 0;
	}
	catch (const std::exception& e)
	{
		std::fprintf(stderr, "oneport: %s\n", e.what());
		return kExitFailed;
	}
#else
	std::fprintf(stderr, "oneport: not served yet on this platform\n");
	return kExitNotServed;
#endif
}
