# oneport: the flag parser, the detection table (the tests link them) and the server binary.
add_library(oneport_config STATIC config.cpp config.hpp)
target_include_directories(oneport_config PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
oneport_warnings(oneport_config)

# The detection table is header-only and pure (detect.hpp); detect_checks.cpp compiles the
# compile-time checks of its corpus (detect_corpus.hpp), so a table that breaks one does not build.
add_library(oneport_server STATIC detect.hpp detect_corpus.hpp detect_checks.cpp)
target_include_directories(oneport_server PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(oneport_server PUBLIC oneport_config)
oneport_warnings(oneport_server)

add_executable(oneport main.cpp)
target_link_libraries(oneport PRIVATE oneport_config oneport_loop)
oneport_warnings(oneport)
