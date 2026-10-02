# oneport: the flag parser as a library (the tests link it), and the server binary.
add_library(oneport_config STATIC config.cpp config.hpp)
target_include_directories(oneport_config PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
oneport_warnings(oneport_config)

add_executable(oneport main.cpp)
target_link_libraries(oneport PRIVATE oneport_config oneport_loop)
oneport_warnings(oneport)
