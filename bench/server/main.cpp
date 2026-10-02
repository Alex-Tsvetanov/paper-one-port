// oneport: the paper's own one-port server (design/proposal.md, section 2).
//
// M0 parses and checks the flags. --print-config prints the configuration and exits 0; serving
// is not implemented in M0 and exits with kExitNotImplemented.
#include "config.hpp"

#include <cstdio>
#include <string_view>
#include <vector>

namespace
{

	constexpr int kExitUsage = 2;
	constexpr int kExitNotImplemented = 3;

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
	std::fprintf(stderr, "oneport: serving is not implemented in M0; the flags parsed as:\n%s",
	             oneport::describe(cmd->config).c_str());
	return kExitNotImplemented;
}
