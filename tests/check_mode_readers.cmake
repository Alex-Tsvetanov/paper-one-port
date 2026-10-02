# The structural test of design/proposal.md I21: the mode is read once, at startup, by the
# listener setup, so the handlers cannot differ between one-port and dedicated mode. Fails if any
# source file under bench/ other than the flag parser (config.hpp, config.cpp) and the listener
# setup (listeners.cpp) reads a member called `mode` (Config::mode), as `.mode` or `->mode`.
#
#   cmake -DROOT=<repository root> -P check_mode_readers.cmake
if(NOT ROOT)
    message(FATAL_ERROR "ROOT is not set")
endif()
set(_allowed
    "${ROOT}/bench/server/config.hpp"
    "${ROOT}/bench/server/config.cpp"
    "${ROOT}/bench/server/listeners.cpp")
file(GLOB_RECURSE _sources "${ROOT}/bench/*.cpp" "${ROOT}/bench/*.hpp" "${ROOT}/bench/*.h")
set(_readers "")
set(_checked 0)
foreach(_f IN LISTS _sources)
    list(FIND _allowed "${_f}" _i)
    if(NOT _i EQUAL -1)
        continue()
    endif()
    math(EXPR _checked "${_checked} + 1")
    file(STRINGS "${_f}" _lines REGEX "(\\.|->)mode([^A-Za-z0-9_]|$)")
    if(_lines)
        list(APPEND _readers "${_f}")
    endif()
endforeach()
# The allowed listener setup must itself read it, or the test checks nothing.
file(STRINGS "${ROOT}/bench/server/listeners.cpp" _setup REGEX "config\\.mode")
if(NOT _setup)
    message(FATAL_ERROR "listeners.cpp does not read config.mode: the structural test is stale")
endif()
if(_readers)
    message(FATAL_ERROR "Config::mode is read outside the parser and the listener setup: ${_readers}")
endif()
message("PASS: structure.mode_readers: ${_checked} files under bench/ read no mode")
