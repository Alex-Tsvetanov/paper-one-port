// The HTTP/1.1 handler's request parser and its fixed responses (design/proposal.md I26;
// hypotheses.md, section 2.1, "Handlers"). Pure: no I/O. The same code serves both modes.
//
// The request line follows the detector's grammar: the HTTP/1.1 matcher of the detection table
// runs first, in both modes, so at most one leading CRLF, one of the nine methods and one SP. A
// request line that breaks that grammar, or has a second SP after the method, is closed without a
// response, as the detector closes it in one-port mode. Any other malformed request gets 400.
//
// What this parser takes, beyond the grammar, are design choices of M1 (design/status.md): the
// request-target is one or more visible ASCII characters; the version is HTTP/1.1 or HTTP/1.0;
// header lines are field-name ":" OWS value OWS CRLF with no obsolete line folding; HTTP/1.1
// needs exactly one Host (RFC 9112 s3.2); no request body, so a Content-Length other than 0 or any
// Transfer-Encoding is a 400; HTTP/1.0 closes after the response; a request that does not fit in
// the receive buffer is a 400.
#pragma once

#include "detect.hpp"

#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace oneport::http1
{

	/// The 200 response of I26: Content-Type text/plain, Content-Length 13, body "Hello, World!".
	inline constexpr std::string_view kResponse200 = "HTTP/1.1 200 OK\r\n"
	                                                 "Content-Type: text/plain\r\n"
	                                                 "Content-Length: 13\r\n"
	                                                 "\r\n"
	                                                 "Hello, World!";
	/// The 400 response, then the connection closes (a design choice of M1: no body).
	inline constexpr std::string_view kResponse400 = "HTTP/1.1 400 Bad Request\r\n"
	                                                 "Content-Length: 0\r\n"
	                                                 "Connection: close\r\n"
	                                                 "\r\n";

	enum class Status : std::uint8_t
	{
		more,         // no complete request yet
		request,      // a complete request of `length` bytes
		bad_grammar,  // the request line breaks the detector's grammar: close, no response
		bad_request,  // malformed: answer 400, then close
	};

	struct Parsed
	{
		Status status = Status::more;
		std::uint32_t length = 0;  // bytes of the request, with any leading CRLF
		bool keep_alive = false;
	};

	namespace detail
	{

		constexpr std::uint8_t at(std::span<const std::byte> b, std::size_t i) noexcept { return detect::u8(b[i]); }

		/// tchar of RFC 9110 s5.6.2.
		constexpr bool is_tchar(std::uint8_t c) noexcept
		{
			if ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')) return true;
			constexpr std::string_view kOther = "!#$%&'*+-.^_`|~";
			return kOther.find(static_cast<char>(c)) != std::string_view::npos;
		}

		constexpr bool is_vchar(std::uint8_t c) noexcept { return c >= 0x21 && c <= 0x7E; }

		constexpr char lower(std::uint8_t c) noexcept { return static_cast<char>(c >= 'A' && c <= 'Z' ? c + 32 : c); }

		constexpr bool iequals(std::span<const std::byte> s, std::string_view t) noexcept
		{
			if (s.size() != t.size()) return false;
			for (std::size_t i = 0; i < s.size(); ++i)
			{
				if (lower(detect::u8(s[i])) != t[i]) return false;
			}
			return true;
		}

		constexpr bool equals(std::span<const std::byte> s, std::string_view t) noexcept
		{
			if (s.size() != t.size()) return false;
			for (std::size_t i = 0; i < s.size(); ++i)
			{
				if (detect::u8(s[i]) != static_cast<std::uint8_t>(t[i])) return false;
			}
			return true;
		}

		constexpr std::span<const std::byte> trim(std::span<const std::byte> s) noexcept
		{
			while (!s.empty() && (detect::u8(s.front()) == ' ' || detect::u8(s.front()) == '\t')) s = s.subspan(1);
			while (!s.empty() && (detect::u8(s.back()) == ' ' || detect::u8(s.back()) == '\t')) s = s.first(s.size() - 1);
			return s;
		}

		/// Does a comma-separated list of tokens hold `token`, case-insensitively?
		constexpr bool has_token(std::span<const std::byte> value, std::string_view token) noexcept
		{
			std::size_t start = 0;
			for (std::size_t i = 0; i <= value.size(); ++i)
			{
				if (i == value.size() || detect::u8(value[i]) == ',')
				{
					if (iequals(trim(value.subspan(start, i - start)), token)) return true;
					start = i + 1;
				}
			}
			return false;
		}

		/// The index of the next CRLF at or after `from`, or npos. A bare LF is reported as `bare_lf`.
		constexpr std::size_t find_crlf(std::span<const std::byte> b, std::size_t from, bool& bare_lf) noexcept
		{
			for (std::size_t i = from; i < b.size(); ++i)
			{
				if (at(b, i) == '\n')
				{
					if (i == from || at(b, i - 1) != '\r') bare_lf = true;
					return i - 1;
				}
			}
			return std::string_view::npos;
		}

	}  // namespace detail

	/// Parses one request from the start of `b`. `buffer_full` says the caller's buffer has no
	/// room left, so a request that is still incomplete can never complete: 400.
	constexpr Parsed parse(std::span<const std::byte> b, bool buffer_full) noexcept
	{
		using namespace detail;
		Parsed out;
		// 1. The detector's grammar: at most one leading CRLF, a listed method, one SP.
		const detect::Match m = detect::match_http1(b);
		if (m.verdict == detect::Verdict::no) return {Status::bad_grammar};
		if (m.verdict == detect::Verdict::more) return {buffer_full ? Status::bad_request : Status::more};
		std::size_t i = m.at;  // after the method's SP
		if (i < b.size() && at(b, i) == ' ') return {Status::bad_grammar};  // a second SP
		// 2. The rest of the request line: request-target SP HTTP-version CRLF.
		bool bare_lf = false;
		const std::size_t line_end = find_crlf(b, i, bare_lf);
		if (bare_lf) return {Status::bad_request};
		if (line_end == std::string_view::npos) return {buffer_full ? Status::bad_request : Status::more};
		std::size_t t = i;
		while (t < line_end && is_vchar(at(b, t))) ++t;
		if (t == i || t >= line_end || at(b, t) != ' ') return {Status::bad_request};
		// HTTP-version, case-sensitive (RFC 9112 s2.3).
		const std::span<const std::byte> version = b.subspan(t + 1, line_end - t - 1);
		const bool http11 = equals(version, "HTTP/1.1");
		if (!http11 && !equals(version, "HTTP/1.0")) return {Status::bad_request};
		// 3. Header lines up to the empty line.
		std::size_t p = line_end + 2;
		int hosts = 0;
		bool close = !http11;
		for (;;)
		{
			bare_lf = false;
			const std::size_t end = find_crlf(b, p, bare_lf);
			if (bare_lf) return {Status::bad_request};
			if (end == std::string_view::npos) return {buffer_full ? Status::bad_request : Status::more};
			if (end == p) break;  // the empty line
			std::size_t c = p;
			while (c < end && is_tchar(at(b, c))) ++c;
			if (c == p || c >= end || at(b, c) != ':') return {Status::bad_request};  // no space before the colon (RFC 9112 s5.1)
			const std::span<const std::byte> field = b.subspan(p, c - p);
			const std::span<const std::byte> value = trim(b.subspan(c + 1, end - c - 1));
			for (const std::byte v : value)
			{
				const std::uint8_t vc = detect::u8(v);
				if (!(is_vchar(vc) || vc == ' ' || vc == '\t' || vc >= 0x80)) return {Status::bad_request};
			}
			if (iequals(field, "host")) ++hosts;
			if (iequals(field, "transfer-encoding")) return {Status::bad_request};
			if (iequals(field, "content-length") && !(value.size() == 1 && detect::u8(value[0]) == '0')) return {Status::bad_request};
			if (iequals(field, "connection"))
			{
				if (has_token(value, "close")) close = true;
			}
			p = end + 2;
		}
		if (http11 && hosts != 1) return {Status::bad_request};
		out.status = Status::request;
		out.length = static_cast<std::uint32_t>(p + 2);
		out.keep_alive = !close;
		return out;
	}

}  // namespace oneport::http1
