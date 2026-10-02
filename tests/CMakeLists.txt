# The test suite: one CTest entry per (group, case), as in P1's suite. Every entry also runs in each
# sanitizer build (hypotheses.md, section 11).
add_executable(oneport_tests unit_tests.cpp detect_tests.cpp http_tests.cpp apps_tests.cpp clienthello_tests.cpp server_tests.cpp handler_tests.cpp
               relay_tests.cpp case_tests.cpp test_support.hpp harness.hpp)
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

# The detection table, the HTTP/1.1 parser, the handlers' protocol steps and the ClientHello
# reader on the recorded ClientHello: pure, on every platform.
set(ONEPORT_PURE_TESTS
    detect.corpus_splits detect.first_bytes detect.order detect.hc16 detect.http1_methods detect.tls detect.mqtt
    detect.ssh_h2c detect.proxy_v1 detect.proxy_v2 detect.budgets
    http.valid http.grammar http.bad_request http.incomplete http.responses
    apps.smtp_lines apps.smtp_partial_and_limits apps.mqtt_connect_ping_disconnect apps.mqtt_streams_payload
    apps.mqtt_refusals apps.ssh_line apps.http_room clienthello.recorded clienthello.fragments)
foreach(_test IN LISTS ONEPORT_PURE_TESTS)
    add_test(NAME ${_test} COMMAND oneport_tests test ${_test})
    set_tests_properties(${_test} PROPERTIES TIMEOUT 300 LABELS pure)
endforeach()

# The structural test of proposal I21: only the parser and the listener setup read the mode.
add_test(NAME structure.mode_readers
         COMMAND ${CMAKE_COMMAND} -DROOT=${PROJECT_SOURCE_DIR} -P ${CMAKE_CURRENT_SOURCE_DIR}/check_mode_readers.cmake)
set_tests_properties(structure.mode_readers PROPERTIES TIMEOUT 60 LABELS structure)

# The server, its handlers, relay dispatch and the hard cases: Linux, on both backends (each test
# named with its backend last). Elsewhere every case is pending (IOCP is M6).
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(ONEPORT_SERVER_TESTS
        server.http_keepalive.oneport_replay server.http_keepalive.oneport_peek server.http_keepalive.dedicated
        server.dedicated_ports server.dedicated_proxy server.peek_lowat.peek server.peek_lowat.replay
        server.check_byte_wins.replay server.check_byte_wins.peek
        server.two_workers.shared_replay server.two_workers.shared_peek server.two_workers.reuseport_replay
        server.two_workers.reuseport_peek server.flag_matrix server.stop_with_pending)
    # The handlers of I26 over sockets: TLS (I24), h2c, MQTT, SSH, SMTP, and output backpressure.
    set(ONEPORT_HANDLER_TESTS
        handlers.clienthello_live handlers.tls_exchange handlers.tls_h2 handlers.tls_refusals handlers.h2c_streams
        handlers.mqtt_session handlers.ssh_banner_timing handlers.smtp_dialogue handlers.output_backpressure)
    # Relay dispatch, pass-through and stub mode (proposal I17, I18).
    set(ONEPORT_RELAY_TESTS
        relay.exchanges.user_space.replay relay.exchanges.user_space.peek relay.exchanges.splice.replay
        relay.exchanges.splice.peek relay.refused relay.pass_through.replay relay.pass_through.peek relay.stub relay.matrix)
    foreach(_backend IN LISTS ONEPORT_BACKENDS)
        foreach(_test IN LISTS ONEPORT_SERVER_TESTS)
            add_test(NAME ${_test}.${_backend} COMMAND oneport_tests test ${_test}.${_backend})
            set_tests_properties(${_test}.${_backend} PROPERTIES TIMEOUT 300 LABELS "server;${_backend}")
        endforeach()
        add_test(NAME server.binary_smoke.${_backend} COMMAND oneport_tests test server.binary_smoke.${_backend} $<TARGET_FILE:oneport>)
        set_tests_properties(server.binary_smoke.${_backend} PROPERTIES TIMEOUT 120 LABELS "server;${_backend}")
        foreach(_test IN LISTS ONEPORT_HANDLER_TESTS)
            add_test(NAME ${_test}.${_backend} COMMAND oneport_tests test ${_test}.${_backend})
            set_tests_properties(${_test}.${_backend} PROPERTIES TIMEOUT 300 LABELS "handlers;${_backend}")
        endforeach()
        foreach(_test IN LISTS ONEPORT_RELAY_TESTS)
            add_test(NAME ${_test}.${_backend} COMMAND oneport_tests test ${_test}.${_backend})
            set_tests_properties(${_test}.${_backend} PROPERTIES TIMEOUT 300 LABELS "relay;${_backend}")
        endforeach()
        add_test(NAME relay.binary.${_backend} COMMAND oneport_tests test relay.binary.${_backend} $<TARGET_FILE:oneport>)
        set_tests_properties(relay.binary.${_backend} PROPERTIES TIMEOUT 120 LABELS "relay;${_backend}")
    endforeach()
    # Once: the kernel behaviour the peek paths rest on, the TLS context, and what is not served.
    foreach(_test server.kernel_rcvlowat_et server.kernel_rcvlowat_uring server.kernel_uring_recv_select server.not_served)
        add_test(NAME ${_test} COMMAND oneport_tests test ${_test})
        set_tests_properties(${_test} PROPERTIES TIMEOUT 300 LABELS server)
    endforeach()
    add_test(NAME handlers.tls_context COMMAND oneport_tests test handlers.tls_context)
    set_tests_properties(handlers.tls_context PROPERTIES TIMEOUT 300 LABELS handlers)
endif()

# The 25 hard cases of hypotheses.md, Appendix A, on every backend, in both detection modes, with
# in-process and relay dispatch (section 5.2, B1). How much of each frozen outcome an entry
# checks, by label: full, or partial (the detection checked, the rest of the outcome pending).
# Every case is full on Linux since M2b. On Windows the IOCP entries are pending (M6).
set(_partial_cases)
foreach(_n RANGE 1 25)
    if(_n LESS 10)
        set(_id HC0${_n})
    else()
        set(_id HC${_n})
    endif()
    set(_coverage full)
    if(_n IN_LIST _partial_cases)
        set(_coverage partial)
    endif()
    foreach(_mode replay peek)
        if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
            foreach(_backend IN LISTS ONEPORT_BACKENDS)
                foreach(_dispatch inproc relay)
                    set(_name case.${_id}.${_backend}.${_dispatch}.${_mode})
                    add_test(NAME ${_name} COMMAND oneport_tests case ${_n} ${_backend} ${_dispatch} ${_mode})
                    set_tests_properties(${_name} PROPERTIES TIMEOUT 900 LABELS "case;${_backend};${_dispatch};${_coverage}")
                endforeach()
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
    oneport_cli_test(relay_needs_port 2 "--dispatch relay needs --relay-port"
                     --mode one-port --detect replay --dispatch relay --backend io_uring)
else()
    oneport_cli_test(not_served_iocp_workers 3 "not served yet: IOCP with more than one worker" ${_arm} --workers 2)
    oneport_cli_test(relay_refused_iocp 2 "the relay is Linux only" --mode one-port --detect replay --dispatch relay --backend IOCP)
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
