// opgen's command line (opgen.hpp). Exit 0 when the run worked (and with --probe, when its one
// exchange completed), 1 otherwise, 2 for a usage error.
#include "opgen.hpp"

#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#if defined(__linux__)
#include <csignal>
#include <sys/resource.h>
#endif

int main(int argc, char** argv)
{
	const std::vector<std::string_view> args(argv + 1, argv + argc);
	for (const auto a : args)
	{
		if (a == "--help")
		{
			std::fputs(oneport::opgen::usage().c_str(), stdout);
			return 0;
		}
	}
	const auto o = oneport::opgen::parse_args(args);
	if (!o)
	{
		std::fprintf(stderr, "opgen: %s\n%s", o.error().c_str(), oneport::opgen::usage().c_str());
		return 2;
	}
	std::string out;
	for (std::size_t i = 0; i + 1 < args.size(); ++i)
	{
		if (args[i] == "--out") out = std::string(args[i + 1]);
	}
#if defined(__linux__)
	std::signal(SIGPIPE, SIG_IGN);
	// Every process of a window starts with its soft RLIMIT_NOFILE at the hard limit (WL7's rule,
	// applied to the generator too).
	rlimit lim{};
	if (getrlimit(RLIMIT_NOFILE, &lim) == 0 && lim.rlim_cur < lim.rlim_max)
	{
		lim.rlim_cur = lim.rlim_max;
		setrlimit(RLIMIT_NOFILE, &lim);
	}
#endif
	const oneport::opgen::Result r = oneport::opgen::run(*o, &std::cout);
	const std::string json = oneport::opgen::to_json(*o, r) + "\n";
	if (out.empty())
	{
		std::cout << json << std::flush;
	}
	else
	{
		std::ofstream f(out, std::ios::binary);
		f << json;
		if (!f)
		{
			std::fprintf(stderr, "opgen: cannot write %s\n", out.c_str());
			return 1;
		}
	}
	if (!r.ok)
	{
		std::fprintf(stderr, "opgen: %s\n", r.error.c_str());
		return 1;
	}
	if (o->probe)
	{
		std::fprintf(stderr, "opgen: probe %s\n", r.probe_detail.c_str());
		return r.measure.completed == 1 ? 0 : 1;
	}
	return 0;
}
