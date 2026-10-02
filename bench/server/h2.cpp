#include "h2.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <string_view>

#include <nghttp2/nghttp2.h>

namespace oneport::server::h2
{

	namespace
	{

		constexpr std::string_view kBody = "Hello, World!";

		nghttp2_nv header(std::string_view name, std::string_view value) noexcept
		{
			// nghttp2 does not write through these pointers (NO_COPY: the strings are static).
			return nghttp2_nv{reinterpret_cast<std::uint8_t*>(const_cast<char*>(name.data())),
			                  reinterpret_cast<std::uint8_t*>(const_cast<char*>(value.data())), name.size(), value.size(),
			                  NGHTTP2_NV_FLAG_NO_COPY_NAME | NGHTTP2_NV_FLAG_NO_COPY_VALUE};
		}

		/// The body, in as many DATA frames as flow control asks for. nghttp2 keeps one copy of
		/// the data source per response and passes it here each time, so its `fd` field holds
		/// the offset sent so far.
		nghttp2_ssize read_body(nghttp2_session*, std::int32_t, std::uint8_t* buf, std::size_t length, std::uint32_t* flags,
		                        nghttp2_data_source* source, void*)
		{
			const auto sent = static_cast<std::size_t>(source->fd);
			const std::size_t n = std::min(length, kBody.size() - sent);
			std::memcpy(buf, kBody.data() + sent, n);
			source->fd = static_cast<int>(sent + n);
			if (sent + n == kBody.size()) *flags |= NGHTTP2_DATA_FLAG_EOF;
			return static_cast<nghttp2_ssize>(n);
		}

		/// A request stream that ends (its HEADERS or DATA with END_STREAM) gets the response.
		int on_frame_recv(nghttp2_session* s, const nghttp2_frame* f, void*)
		{
			const bool ends = (f->hd.flags & NGHTTP2_FLAG_END_STREAM) != 0;
			const bool request = (f->hd.type == NGHTTP2_HEADERS && f->headers.cat == NGHTTP2_HCAT_REQUEST) || f->hd.type == NGHTTP2_DATA;
			if (!ends || !request) return 0;
			static const std::array<nghttp2_nv, 3> kHeaders{header(":status", "200"), header("content-type", "text/plain"),
			                                                header("content-length", "13")};
			nghttp2_data_provider2 body{};
			body.source.fd = 0;
			body.read_callback = read_body;
			if (nghttp2_submit_response2(s, f->hd.stream_id, kHeaders.data(), kHeaders.size(), &body) != 0) return NGHTTP2_ERR_CALLBACK_FAILURE;
			return 0;
		}

		const nghttp2_session_callbacks* callbacks()
		{
			static nghttp2_session_callbacks* const cbs = [] {
				nghttp2_session_callbacks* c = nullptr;
				if (nghttp2_session_callbacks_new(&c) != 0) return static_cast<nghttp2_session_callbacks*>(nullptr);
				nghttp2_session_callbacks_set_on_frame_recv_callback(c, on_frame_recv);
				return c;
			}();
			return cbs;
		}

	}  // namespace

	nghttp2_session* open() noexcept
	{
		const nghttp2_session_callbacks* cbs = callbacks();
		if (cbs == nullptr) return nullptr;
		nghttp2_session* s = nullptr;
		if (nghttp2_session_server_new(&s, cbs, nullptr) != 0) return nullptr;
		const nghttp2_settings_entry settings{NGHTTP2_SETTINGS_MAX_CONCURRENT_STREAMS, 100};
		if (nghttp2_submit_settings(s, NGHTTP2_FLAG_NONE, &settings, 1) != 0)
		{
			nghttp2_session_del(s);
			return nullptr;
		}
		return s;
	}

	void close(nghttp2_session* s) noexcept { nghttp2_session_del(s); }

	bool feed(nghttp2_session* s, std::span<const std::byte> bytes) noexcept
	{
		const nghttp2_ssize r = nghttp2_session_mem_recv2(s, reinterpret_cast<const std::uint8_t*>(bytes.data()), bytes.size());
		return r >= 0 && static_cast<std::size_t>(r) == bytes.size();
	}

	bool drain(nghttp2_session* s, std::vector<std::byte>& out)
	{
		for (;;)
		{
			const std::uint8_t* p = nullptr;
			const nghttp2_ssize n = nghttp2_session_mem_send2(s, &p);
			if (n < 0) return false;
			if (n == 0) return true;
			const auto* b = reinterpret_cast<const std::byte*>(p);
			out.insert(out.end(), b, b + n);
		}
	}

	bool finished(nghttp2_session* s) noexcept { return nghttp2_session_want_read(s) == 0 && nghttp2_session_want_write(s) == 0; }

}  // namespace oneport::server::h2
