// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
//
// Internal helpers shared by the backends.
#pragma once

#include "oneport/loop.hpp"

#include <cstddef>

#if defined(__has_feature)
#if __has_feature(memory_sanitizer)
#define ONEPORT_MSAN 1
#if __has_include(<sanitizer/msan_interface.h>)
#include <sanitizer/msan_interface.h>
#else
// The documented MemorySanitizer interface, for runtimes installed without their headers.
extern "C" void __msan_unpoison(const volatile void* a, std::size_t size);
#endif
#endif
#endif

namespace oneport::loop::detail
{

	/// A broken invariant on a path that cannot report an error (a stop signal that failed).
	/// Prints `what` and the OS error, then aborts: a lost stop must never be silent.
	[[noreturn]] void fatal(const char* what, long os_error) noexcept;

	/// Marks memory the kernel wrote as initialized for MemorySanitizer; nothing otherwise.
	/// MemorySanitizer cannot see what the kernel writes through a raw system call or into a
	/// shared ring (hypotheses.md, section 11), so every such structure is value-initialized
	/// first and each completion is unpoisoned here, exactly the bytes the kernel reports.
	inline void kernel_wrote([[maybe_unused]] const void* p, [[maybe_unused]] std::size_t n) noexcept
	{
#if defined(ONEPORT_MSAN)
		__msan_unpoison(p, n);
#endif
	}

	/// Checks a wait bound: nullopt or at least zero. Throws std::invalid_argument otherwise.
	Bound checked_bound(Bound bound);

}  // namespace oneport::loop::detail
