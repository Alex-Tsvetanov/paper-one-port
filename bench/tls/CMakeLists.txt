# oneport_tls: the TLS settings of hypotheses.md, section 2.1 (proposal I24), shared by the server,
# opcase and, later, opgen, so that "the same settings in the server, the backend and the
# generator" holds by construction; the server's BIO; and the test certificate and key.
#
# The test certificate and its key are files in tests/fixtures/tls, embedded here at configure time
# (test_material.cpp.in), so the binary needs no path and no flag. The generated file lies in the
# build tree outside _deps, so the sanitizer gate hashes it too.
set(_fix "${PROJECT_SOURCE_DIR}/tests/fixtures/tls")
foreach(_name test-cert.pem test-key.pem)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_fix}/${_name}")
endforeach()
file(READ "${_fix}/test-cert.pem" ONEPORT_TEST_CERT_PEM)
file(READ "${_fix}/test-key.pem" ONEPORT_TEST_KEY_PEM)
configure_file(test_material.cpp.in "${CMAKE_CURRENT_BINARY_DIR}/generated/test_material.cpp" @ONLY)

add_library(oneport_tls STATIC tls.cpp tls.hpp "${CMAKE_CURRENT_BINARY_DIR}/generated/test_material.cpp")
target_include_directories(oneport_tls PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(oneport_tls PUBLIC oneport_dep_ssl)
oneport_warnings(oneport_tls)
