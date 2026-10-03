# opcase, the case generator (hypotheses.md, section 2.4; proposal I30, I33): the hard cases of
# Appendix A as scripts of writes and gaps, their expected outcomes, and the client that runs
# them, with a live TLS client on the settings of bench/tls. It is a library the test suite runs
# in-process against the server.
#
# The recorded ClientHello (proposal I18) is tests/fixtures/tls/clienthello.hex, embedded at
# configure time (clienthello_hex.cpp.in); record_clienthello, built on Linux, made it.
set(_hex "${PROJECT_SOURCE_DIR}/tests/fixtures/tls/clienthello.hex")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_hex}")
if(EXISTS "${_hex}")
    file(READ "${_hex}" ONEPORT_CLIENTHELLO_HEX)
else()
    # Before the recording exists; recorded_client_hello() then throws, and its tests fail.
    set(ONEPORT_CLIENTHELLO_HEX "")
    message(STATUS "oneport: tests/fixtures/tls/clienthello.hex is not recorded yet")
endif()
configure_file(clienthello_hex.cpp.in "${CMAKE_CURRENT_BINARY_DIR}/generated/clienthello_hex.cpp" @ONLY)

add_library(opcase STATIC cases.cpp cases.hpp fixtures.cpp fixtures.hpp script.cpp script.hpp run_cases.cpp run_cases.hpp
            "${CMAKE_CURRENT_BINARY_DIR}/generated/clienthello_hex.cpp")
target_include_directories(opcase PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(opcase PUBLIC oneport_server)
oneport_warnings(opcase)

if(TARGET oneport_tls)
    target_link_libraries(opcase PUBLIC oneport_tls)
    target_compile_definitions(opcase PUBLIC ONEPORT_HAVE_TLS=1)
    # Prints the ClientHello an OpenSSL client writes with the settings of bench/tls, as the
    # fixture's text (run once on L; the output is tests/fixtures/tls/clienthello.hex).
    if(NOT WIN32)  # the recording was made on L; W uses the fixture (M6a)
    add_executable(record_clienthello record_clienthello.cpp)
    target_link_libraries(record_clienthello PRIVATE oneport_tls)
    oneport_warnings(record_clienthello)
    endif()
endif()

# The programs of the windows (Linux): opcase's WL7 openings and probe, and ophold, the holder
# that measures the kernel's per-socket baseline (WL7, K_BASE).
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    add_executable(opcase_bin opcase_main.cpp)
    set_target_properties(opcase_bin PROPERTIES OUTPUT_NAME opcase)
    target_link_libraries(opcase_bin PRIVATE opcase)
    oneport_warnings(opcase_bin)
    add_executable(ophold ophold.cpp)
    target_link_libraries(ophold PRIVATE Threads::Threads)
    oneport_warnings(ophold)
endif()
