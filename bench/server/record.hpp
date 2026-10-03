// The per-connection decision record of the binary (hypotheses.md, WL8: "per case: outcome,
// transcript, and decision time against opcase's write times"; design/status.md, M1's note and M5):
// with --record PATH the server writes one JSON line per event its test hooks report, the end of
// each connection's detection, each relayed connection's route and each close, with every time
// in nanoseconds of the server's clock (std::chrono::steady_clock, CLOCK_MONOTONIC on L, the
// clock of opcase's write times). A hard-case run against a server in its own process matches the
// lines to opcase's transcripts by the client's local port (peer_port); each line is written
// through to the file at once (M7c), so a runner reads a connection's lines while the server runs.
// Without --record no hook is set, and the server runs exactly as before. Never set in a measured
// window.
#pragma once

#include "server.hpp"

#include <cstdio>
#include <memory>
#include <mutex>
#include <string>

namespace oneport::server
{

	class Recorder
	{
	public:
		/// Opens `path` for writing (truncating it). Throws std::runtime_error if it cannot.
		explicit Recorder(const std::string& path);
		~Recorder();
		Recorder(const Recorder&) = delete;
		Recorder& operator=(const Recorder&) = delete;

		/// The hooks that write to this record; the server calls them on its worker threads.
		Hooks hooks();

		/// Writes what is buffered; the server calls nothing after its stop().
		void flush();

		/// One line per report, as written (pure, for the tests).
		static std::string line(const DetectionReport& r);
		static std::string line(const RelayReport& r);
		static std::string line(const CloseReport& r);

	private:
		void write(const std::string& s);

		std::FILE* f_ = nullptr;
		std::mutex m_;
	};

}  // namespace oneport::server
