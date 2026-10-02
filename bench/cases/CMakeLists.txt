# opcase, the case generator (hypotheses.md, section 2.4; proposal I30, I33): the hard cases of
# Appendix A as scripts of writes and gaps, their expected outcomes, and the client that runs
# them. In M1 it is a library the test suite runs in-process against the server.
add_library(opcase STATIC cases.cpp cases.hpp fixtures.cpp fixtures.hpp script.cpp script.hpp)
target_include_directories(opcase PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(opcase PUBLIC oneport_server)
oneport_warnings(opcase)
