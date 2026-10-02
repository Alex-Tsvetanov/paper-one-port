// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
#include "common.hpp"

#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>

namespace oneport::loop::detail
{

	void fatal(const char* what, long os_error) noexcept
	{
		std::fprintf(stderr, "oneport loop: fatal: %s (os error %ld)\n", what, os_error);
		std::fflush(stderr);
		std::abort();
	}

	Bound checked_bound(Bound bound)
	{
		if (bound && bound->count() < 0)
		{
			throw std::invalid_argument("oneport loop: a wait bound must be >= 0 ns, got " + std::to_string(bound->count()));
		}
		return bound;
	}

}  // namespace oneport::loop::detail
