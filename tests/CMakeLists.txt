# The test suite: one CTest entry per (group, case), as in P1's suite. Every entry also runs in each
# sanitizer build (hypotheses.md, section 11).
add_executable(oneport_tests unit_tests.cpp detect_tests.cpp http_tests.cpp server_tests.cpp case_tests.cpp
               test_support.hpp harness.hpp)
target_link_libraries(oneport_tests PRIVATE oneport_server oneport_loop opcase)
oneport_warnings(oneport_tests)

set(ONEPORT_FLAG_TESTS
    arms required spellings unknown duplicates missing_value defaults options numbers combinations platform
    dedicated_echoes help print_config)
foreach(_test IN LISTS ONEPORT_FLAG_TESTS)
    add_test(NAME flags.${_test} COMMAND oneport_tests flags ${_test})
    set_tests_properties(flags.${_test} PROPERTIES TIMEOUT 60 LABELS flags)
endforeach()

set(ONEPORT_LOOP_TESTS
    construct bounded_wait zero_wait stop_wakes_blocked stop_before_start stop_is_sticky start_twice_refused
    wait_before_start_refused negative_bound_refused)
foreach(_backend IN LISTS ONEPORT_BACKENDS)
    foreach(_test IN LISTS ONEPORT_LOOP_TESTS)
        add_test(NAME loop.${_backend}.${_test} COMMAND oneport_tests loop ${_backend} ${_test})
        set_tests_properties(loop.${_backend}.${_test} PROPERTIES TIMEOUT 60 LABELS "loop;${_backend}")
    endforeach()
endforeach()

# The detection table and the HTTP/1.1 parser: pure, on every platform.
set(ONEPORT_PURE_TESTS
    detect.corpus_splits detect.first_bytes detect.order detect.hc16 detect.http1_methods detect.tls detect.mqtt
    detect.ssh_h2c detect.proxy_v1 detect.proxy_v2 detect.budgets
    http.valid http.grammar http.bad_request http.incomplete http.responses)
foreach(_test IN LISTS ONEPORT_PURE_TESTS)
    add_test(NAME ${_test} COMMAND oneport_tests test ${_test})
    set_tests_properties(${_test} PROPERTIES TIMEOUT 300 LABELS pure)
endforeach()

# The structural test of proposal I21: only the parser and the listener setup read the mode.
add_test(NAME structure.mode_readers
         COMMAND ${CMAKE_COMMAND} -DROOT=${PROJECT_SOURCE_DIR} -P ${CMAKE_CURRENT_SOURCE_DIR}/check_mode_readers.cmake)
set_tests_properties(structure.mode_readers PROPERTIES TIMEOUT 60 LABELS structure)

# The server on epoll and the hard cases: Linux. Elsewhere every case is pending (IOCP is M6).
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(ONEPORT_SERVER_TESTS
        server.http_keepalive.oneport_replay server.http_keepalive.oneport_peek server.http_keepalive.dedicated
        server.dedicated_ports server.dedicated_proxy server.peek_lowat.peek server.peek_lowat.replay
        server.kernel_rcvlowat_et server.check_byte_wins.replay server.check_byte_wins.peek
        server.two_workers.shared_replay server.two_workers.shared_peek server.two_workers.reuseport_replay
        server.two_workers.reuseport_peek server.flag_matrix server.stop_with_pending server.not_served)
    foreach(_test IN LISTS ONEPORT_SERVER_TESTS)
        add_test(NAME ${_test} COMMAND oneport_tests test ${_test})
        set_tests_properties(${_test} PROPERTIES TIMEOUT 300 LABELS server)
    endforeach()
    add_test(NAME server.binary_smoke COMMAND oneport_tests test server.binary_smoke $<TARGET_FILE:oneport>)
    set_tests_properties(server.binary_smoke PROPERTIES TIMEOUT 120 LABELS server)
endif()

# The 25 hard cases of hypotheses.md, Appendix A. How much of each frozen outcome M1 checks, by
# label: full; stub (detection and timing checked, the exchange is an M1 stub handler's until M2);
# partial (the detection checked, the rest of the outcome pending M2). Every case also has entries
# for the dispatch modes and backends M1 does not serve, marked pending with the reason.
set(_stub_cases 1 2 3 5 7 15)
set(_partial_cases 20)
foreach(_n RANGE 1 25)
    if(_n LESS 10)
        set(_id HC0${_n})
    else()
        set(_id HC${_n})
    endif()
    set(_coverage full)
    if(_n IN_LIST _stub_cases)
        set(_coverage stub)
    elseif(_n IN_LIST _partial_cases)
        set(_coverage partial)
    endif()
    foreach(_mode replay peek)
        if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
            add_test(NAME case.${_id}.epoll.inproc.${_mode} COMMAND oneport_tests case ${_n} ${_mode})
            set_tests_properties(case.${_id}.epoll.inproc.${_mode} PROPERTIES TIMEOUT 600 LABELS "case;epoll;${_coverage}")
            add_test(NAME case.${_id}.epoll.relay.${_mode} COMMAND oneport_tests pending ${_id}.epoll.relay.${_mode} pending M2: relay dispatch)
            set_tests_properties(case.${_id}.epoll.relay.${_mode} PROPERTIES SKIP_RETURN_CODE 77 LABELS "case;pending")
            foreach(_dispatch inproc relay)
                add_test(NAME case.${_id}.io_uring.${_dispatch}.${_mode}
                         COMMAND oneport_tests pending ${_id}.io_uring.${_dispatch}.${_mode} pending M2: the io_uring backend)
                set_tests_properties(case.${_id}.io_uring.${_dispatch}.${_mode} PROPERTIES SKIP_RETURN_CODE 77 LABELS "case;pending")
            endforeach()
        elseif(WIN32)
            add_test(NAME case.${_id}.IOCP.inproc.${_mode} COMMAND oneport_tests pending ${_id}.IOCP.inproc.${_mode} pending M6: the IOCP backend)
            set_tests_properties(case.${_id}.IOCP.inproc.${_mode} PROPERTIES SKIP_RETURN_CODE 77 LABELS "case;pending")
        endif()
    endforeach()
endforeach()

# The binary's command line: its exit code and output, through run_expect.cmake. The arm uses
# the first backend this platform compiles.
list(GET ONEPORT_BACKENDS 0 _first_backend)
set(_arm --mode one-port --detect replay --dispatch inproc --backend ${_first_backend})
function(oneport_cli_test name expect_exit expect_output)
    list(JOIN ARGN "|" _words)
    add_test(NAME cli.${name}
             COMMAND ${CMAKE_COMMAND} "-DCOMMAND=$<TARGET_FILE:oneport>|${_words}" "-DEXPECT_EXIT=${expect_exit}"
                     "-DEXPECT_OUTPUT=${expect_output}" -P ${CMAKE_CURRENT_SOURCE_DIR}/run_expect.cmake)
    set_tests_properties(cli.${name} PROPERTIES TIMEOUT 60 LABELS cli)
endfunction()
oneport_cli_test(print_config 0 "detect replay.+dispatch inproc.+backend ${_first_backend}" ${_arm} --print-config)
oneport_cli_test(usage_error 2 "missing --detect, --dispatch, --backend" --mode one-port)
oneport_cli_test(help 0 "usage: oneport" --help)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    oneport_cli_test(not_served_io_uring 3 "not served in M1: the io_uring backend is M2"
                     --mode one-port --detect replay --dispatch inproc --backend io_uring)
    oneport_cli_test(not_served_relay 3 "not served in M1: relay dispatch is M2"
                     --mode one-port --detect replay --dispatch relay --backend epoll)
    oneport_cli_test(not_served_stub 3 "not served in M1: stub mode"
                     --mode stub --detect replay --dispatch inproc --backend epoll)
else()
    oneport_cli_test(not_served_iocp 3 "not served in M1: the IOCP backend is M6" ${_arm})
endif()

# The records gate and the record writer (bench/), when a Python 3 interpreter is found.
find_package(Python3 COMPONENTS Interpreter)
if(Python3_FOUND)
    foreach(_script test_gates test_record_writers)
        add_test(NAME gate.${_script} COMMAND ${Python3_EXECUTABLE} ${PROJECT_SOURCE_DIR}/bench/${_script}.py)
        set_tests_properties(gate.${_script} PROPERTIES TIMEOUT 120 LABELS gate)
    endforeach()
else()
    message(STATUS "oneport: no Python 3, so the gate tests are not registered")
endif()
