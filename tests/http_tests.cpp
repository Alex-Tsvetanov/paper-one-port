// The HTTP/1.1 handler's parser (bench/server/http1.hpp): the detector's grammar in both modes
// (proposal I20, I26; hypotheses.md, section 11: "the HTTP/1.1 grammar on invalid input").
#include "http1.hpp"
#include "test_support.hpp"

#include <string>
#include <vector>

namespace oneport::test
{

	namespace
	{

		using http1::Status;

		http1::Parsed parse(std::string_view s, bool full = false)
		{
			std::vector<std::byte> b;
			for (const char c : s) b.push_back(static_cast<std::byte>(static_cast<unsigned char>(c)));
			return http1::parse(b, full);
		}

		Result valid()
		{
			const std::string_view get = "GET / HTTP/1.1\r\nHost: a\r\n\r\n";
			const auto p = parse(get);
			CHECK(p.status == Status::request && p.length == get.size() && p.keep_alive, "a keep-alive GET");
			const auto close = parse("GET / HTTP/1.1\r\nHost: a\r\nConnection: keep-alive, Close\r\n\r\n");
			CHECK(close.status == Status::request && !close.keep_alive, "Connection: close, case-insensitive, in a list");
			const auto ten = parse("GET / HTTP/1.0\r\n\r\n");
			CHECK(ten.status == Status::request && !ten.keep_alive, "HTTP/1.0 needs no Host and closes");
			const auto crlf = parse("\r\nGET / HTTP/1.1\r\nHost: a\r\n\r\n");
			CHECK(crlf.status == Status::request && crlf.length == 29, "one leading CRLF");
			for (const char* m : {"HEAD", "POST", "PUT", "DELETE", "OPTIONS", "TRACE", "PATCH"})
			{
				CHECK(parse(std::string(m) + " / HTTP/1.1\r\nHost: a\r\n\r\n").status == Status::request, m);
			}
			CHECK(parse("CONNECT a:80 HTTP/1.1\r\nHost: a:80\r\n\r\n").status == Status::request, "CONNECT");
			CHECK(parse("GET / HTTP/1.1\r\nHost: a\r\nContent-Length: 0\r\n\r\n").status == Status::request, "Content-Length: 0");
			CHECK(parse("GET / HTTP/1.1\r\nhost:a\r\nX-Y:  v \t\r\n\r\n").status == Status::request, "OWS");
			const auto two = parse("GET / HTTP/1.1\r\nHost: a\r\n\r\nGET /2 HTTP/1.1\r\nHost: a\r\n\r\n");
			CHECK(two.status == Status::request && two.length == get.size(), "pipelined: the first request's length");
			return std::nullopt;
		}

		Result grammar()
		{
			for (const char* s : {"\r\n\r\nGET / HTTP/1.1\r\n", "GETX / HTTP/1.1\r\n", "get / HTTP/1.1\r\n", "GET  / HTTP/1.1\r\n", "GET\t/ HTTP/1.1\r\n",
			                      "PRI * HTTP/2.0\r\n", "AAAA", "\nGET / HTTP/1.1\r\n", "BREW / HTTP/1.1\r\n"})
			{
				CHECK(parse(s).status == Status::bad_grammar, "the detector's grammar refuses '" << std::string(s).substr(0, 6) << "'");
			}
			return std::nullopt;
		}

		Result bad_request()
		{
			const char* bad[] = {
				"GET key\r\n",                                                      // HC25
				"GET / HTTP/1.1 \r\nHost: a\r\n\r\n",                               // a space after the version
				"GET / HTTP/2.0\r\nHost: a\r\n\r\n",                                // not 1.0 or 1.1
				"GET / http/1.1\r\nHost: a\r\n\r\n",                                // HTTP-name is case-sensitive
				"GET / HTTP/1.1\nHost: a\r\n\r\n",                                  // a bare LF
				"GET / HTTP/1.1\r\nHost a\r\n\r\n",                                 // no colon
				"GET / HTTP/1.1\r\nHost : a\r\n\r\n",                               // a space before the colon
				"GET / HTTP/1.1\r\n\r\n",                                           // no Host
				"GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n",                    // two Hosts
				"GET / HTTP/1.1\r\nHost: a\r\nContent-Length: 5\r\n\r\n",          // a body
				"GET / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n", // a body
				"GET / HTTP/1.1\r\nHost: a\r\n folded\r\n\r\n",                    // obsolete line folding
				"GET / HTTP/1.1\r\nHost: a\x01\r\n\r\n",                           // a control character
				"GET /\x7F HTTP/1.1\r\nHost: a\r\n\r\n",                           // DEL in the target
			};
			for (const char* b : bad)
			{
				CHECK(parse(b).status == Status::bad_request, "a 400 for '" << std::string(b).substr(0, 8) << "'");
			}
			return std::nullopt;
		}

		Result incomplete()
		{
			for (const char* s : {"G", "GET", "GET ", "GET /", "GET / HTTP/1.1", "GET / HTTP/1.1\r\n", "GET / HTTP/1.1\r\nHost: a\r\n", "\r"})
			{
				CHECK(parse(s).status == Status::more, "'" << s << "' waits for more");
				CHECK(parse(s, true).status == Status::bad_request, "'" << s << "' in a full buffer is a 400");
			}
			return std::nullopt;
		}

		Result responses()
		{
			CHECK(http1::kResponse200 == "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 13\r\n\r\nHello, World!", "the 200 of I26");
			CHECK(http1::kResponse200.size() - http1::kResponse200.find("\r\n\r\n") - 4 == 13, "a 13-byte body");
			return std::nullopt;
		}

	}  // namespace

	void register_http_tests(Registry& r)
	{
		r["http.valid"] = valid;
		r["http.grammar"] = grammar;
		r["http.bad_request"] = bad_request;
		r["http.incomplete"] = incomplete;
		r["http.responses"] = responses;
	}

}  // namespace oneport::test
