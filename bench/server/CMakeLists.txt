# oneport: the flag parser, the detection table, the server library (the tests link them) and the
# server binary.
add_library(oneport_config STATIC config.cpp config.hpp)
target_include_directories(oneport_config PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
oneport_warnings(oneport_config)

# The detection table is header-only and pure (detect.hpp); detect_checks.cpp compiles the
# compile-time checks of its corpus (detect_corpus.hpp), so a table that breaks one does not build.
add_library(oneport_server STATIC
    detect.hpp detect_corpus.hpp detect_checks.cpp http1.hpp apps.hpp apps.cpp clienthello.hpp
    counters.cpp listeners.cpp server.cpp server.hpp worker.hpp worker.cpp handlers.cpp)
target_include_directories(oneport_server PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(oneport_server PUBLIC oneport_config oneport_loop)
# The handlers that need the pinned libraries: h2 (nghttp2) and TLS (OpenSSL, bench/tls). Linux
# only until M6.
if(TARGET oneport_tls)
    target_sources(oneport_server PRIVATE h2.hpp h2.cpp)
    target_link_libraries(oneport_server PUBLIC oneport_tls oneport_dep_nghttp2)
endif()
oneport_warnings(oneport_server)

add_executable(oneport main.cpp)
target_link_libraries(oneport PRIVATE oneport_server)
oneport_warnings(oneport)
