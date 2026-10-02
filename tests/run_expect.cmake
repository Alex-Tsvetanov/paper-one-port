# Runs one command and checks its exit code and its output, for the command-line tests of oneport.
#
#   cmake "-DCOMMAND=program|word|..." -DEXPECT_EXIT=N "-DEXPECT_OUTPUT=REGEX" -P run_expect.cmake
#
# COMMAND separates its words with '|'. The output matched is standard output and standard error
# together. Fails (exit 1) on another exit code or an output that does not match.
string(REPLACE "|" ";" _command "${COMMAND}")
execute_process(COMMAND ${_command} RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)
set(_all "${_out}${_err}")
message("exit ${_rc}\n${_all}")
if(NOT "${_rc}" STREQUAL "${EXPECT_EXIT}")
    message(FATAL_ERROR "exit ${_rc}, expected ${EXPECT_EXIT}")
endif()
if(NOT _all MATCHES "${EXPECT_OUTPUT}")
    message(FATAL_ERROR "the output does not match '${EXPECT_OUTPUT}'")
endif()
