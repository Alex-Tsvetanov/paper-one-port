# opgen, the load generator (hypotheses.md, section 2.4; proposal I30, I33): churn and keep-alive,
# closed and open loop, per protocol, on the event loop of bench/loop and the TLS settings of
# bench/tls. A library (the tests run it in-process against the server) and the binary the window
# runner starts. The engine is Linux only until M6 names its Windows backend; the command line and
# the report build everywhere.
add_library(opgen_core STATIC opgen.hpp hpack.hpp opgen.cpp options.cpp)
target_include_directories(opgen_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(opgen_core PUBLIC oneport_loop opcase)
# The engine needs TLS and Linux: since M6a, W has the TLS libraries too, and the engine is not
# built there.
if(TARGET oneport_tls AND CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_sources(opgen_core PRIVATE exchange.hpp exchange.cpp worker.hpp worker.cpp parse.cpp)
    target_link_libraries(opgen_core PUBLIC oneport_tls)
endif()
oneport_warnings(opgen_core)

add_executable(opgen main.cpp)
target_link_libraries(opgen PRIVATE opgen_core)
oneport_warnings(opgen)
