// opgen's one reading of HPACK (RFC 7541): where an h2 response's header block starts. Pure and
// header-only, so the test runs on every platform (tests/gen_tests.cpp, gen.h2_status).
#pragma once

#include <cstddef>

namespace oneport::opgen::detail
{

	/// The most bytes after the prefix that an HPACK integer of 32 bits takes (RFC 7541 s5.1).
	inline constexpr std::size_t kMaxIntegerBytes = 5;

	/// Whether an h2 header block from the server begins with :status 200, the static table's
	/// index 8 (0x88), after any dynamic table size updates, which RFC 7541 puts at the beginning
	/// of a header block (s4.2) and encodes as the bits 001 and a 5-bit prefix integer (s6.3, s5.1).
	/// An update whose integer does not end within kMaxIntegerBytes bytes is refused.
	inline bool h2_status_200(const std::byte* p, std::size_t n) noexcept
	{
		std::size_t i = 0;
		while (i < n && (std::to_integer<unsigned>(p[i]) & 0xE0u) == 0x20u)
		{
			// A dynamic table size update; a prefix of all ones continues in bytes whose top bit is set.
			const bool more = (std::to_integer<unsigned>(p[i]) & 0x1Fu) == 0x1Fu;
			++i;
			if (!more) continue;
			std::size_t k = 0;
			while (i < n && (std::to_integer<unsigned>(p[i]) & 0x80u) != 0)
			{
				++i;
				if (++k >= kMaxIntegerBytes) return false;
			}
			if (i == n) return false;
			++i;  // the integer's last byte
		}
		return i < n && p[i] == std::byte{0x88};
	}

}  // namespace oneport::opgen::detail
