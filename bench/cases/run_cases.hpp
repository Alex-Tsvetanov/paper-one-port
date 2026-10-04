// opcase case: the hard cases against any system by port (see run_cases.cpp). Linux.
#pragma once

#include "cases.hpp"

#include <cstdint>
#include <string>

namespace oneport::opcase
{

	/// One variant's frozen expectation as a JSON line (`opcase case --list`).
	std::string variant_line(const Variant& v, int hc);

	/// One run's JSON line: the variant, its frozen expectation, and the transcript.
	std::string run_line(const Variant& v, int hc, unsigned replicate, std::uint16_t port, const Transcript& t);

	/// `opcase case ...` (argv[1] is "case"); returns the exit status.
	int run_cases(int argc, char** argv);

}  // namespace oneport::opcase
