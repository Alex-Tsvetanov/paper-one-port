# opgen, the load generator (hypotheses.md, section 2.4; proposal I30, I33): churn and keep-alive,
# closed and open loop, per protocol, on the event loop of bench/loop and the TLS settings of
# bench/tls. A library (the tests run it in-process against the server) and the binary the window
# runner starts. The command line and the report build everywhere; the engine on Linux (epoll) and,
# since M6b, on Windows (a completion port per worker, worker_win.cpp).
add_library(opgen_core STATIC opgen.hpp hpack.hpp opgen.cpp options.cpp)
target_include_directories(opgen_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(opgen_core PUBLIC oneport_loop opcase)
# The engine needs TLS.
if(TARGET oneport_tls AND CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_sources(opgen_core PRIVATE exchange.hpp exchange.cpp worker.hpp worker.cpp parse.cpp)
    target_link_libraries(opgen_core PUBLIC oneport_tls)
elseif(TARGET oneport_tls AND WIN32)
    target_sources(opgen_core PRIVATE exchange.hpp exchange.cpp worker.hpp worker.cpp worker_win.cpp parse.cpp)
    target_link_libraries(opgen_core PUBLIC oneport_tls ws2_32 mswsock)
endif()
oneport_warnings(opgen_core)

add_executable(opgen main.cpp)
target_link_libraries(opgen PRIVATE opgen_core)
oneport_warnings(opgen)
