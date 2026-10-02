# P3: oneport, the paper's own one-port server (design/proposal.md, section 2), and its tests.
# The generators opgen and opcase and the holder ophold join this project in later milestones.
#
#   -DONEPORT_SANITIZER=...    address+undefined, thread or memory with clang on Linux;
#                              address with MSVC on Windows (hypotheses.md, section 11)
#   -DONEPORT_MSAN_LIBCXX=DIR  prefix of an MSan-instrumented libc++ (memory only)
#
# The repository root is the project root, so every first-party file lies under the CMake home
# directory and counts in the inputs hash of the sanitizer gate (bench/gate_lib.py).
# The sanitizer block is derived from paper-wake-defect's CMakeLists.txt at commit 0af1ac4,
# same author.
cmake_minimum_required(VERSION 3.25)
project(oneport LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Every pinned third-party input; the records gate hashes this file (bench/gate_lib.py).
include(${CMAKE_CURRENT_SOURCE_DIR}/bench/cmake/pins.cmake)

set(ONEPORT_SANITIZER "" CACHE STRING "address+undefined, thread, memory (clang, Linux); address (MSVC, Windows)")
set(ONEPORT_MSAN_LIBCXX "$ENV{HOME}/opt/libcxx-msan-gcc" CACHE PATH "Prefix of an MSan-instrumented libc++")

# The backends this platform compiles. Recorded in the cache, where the sanitizer gate can read it.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(ONEPORT_BACKENDS "epoll;io_uring" CACHE INTERNAL "Backends compiled on this platform")
elseif(WIN32)
    set(ONEPORT_BACKENDS "IOCP" CACHE INTERNAL "Backends compiled on this platform")
else()
    message(FATAL_ERROR "oneport has backends for Linux and Windows only")
endif()

# Sanitizers apply to every target, so the whole of each binary is instrumented.
if(ONEPORT_SANITIZER)
    if(WIN32)
        # One compiler on W, because the gate matches the compiler; clang-cl is not used
        # (hypotheses.md, section 11).
        if(NOT CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
            message(FATAL_ERROR "on Windows the sanitizer records use MSVC, not ${CMAKE_CXX_COMPILER_ID}")
        endif()
        if(NOT ONEPORT_SANITIZER STREQUAL "address")
            message(FATAL_ERROR "on Windows ONEPORT_SANITIZER can only be address")
        endif()
        add_compile_options(/fsanitize=address /Zi)
        add_link_options(/INCREMENTAL:NO /DEBUG)
    else()
        string(REPLACE "+" "," _san "${ONEPORT_SANITIZER}")
        add_compile_options(-fsanitize=${_san} -fno-omit-frame-pointer -fno-sanitize-recover=all -g)
        add_link_options(-fsanitize=${_san})
        if(_san MATCHES "memory")
            if(NOT EXISTS "${ONEPORT_MSAN_LIBCXX}/include/c++/v1")
                message(FATAL_ERROR "ONEPORT_SANITIZER=memory needs an instrumented libc++; "
                                    "none at ONEPORT_MSAN_LIBCXX=${ONEPORT_MSAN_LIBCXX}")
            endif()
            add_compile_options(-fsanitize-memory-track-origins=2 -stdlib=libc++
                                "-isystem${ONEPORT_MSAN_LIBCXX}/include/c++/v1")
            add_link_options(-stdlib=libc++ "-L${ONEPORT_MSAN_LIBCXX}/lib"
                             "-Wl,-rpath,${ONEPORT_MSAN_LIBCXX}/lib" -lc++abi)
        endif()
    endif()
    message(STATUS "oneport: sanitizer ${ONEPORT_SANITIZER}")
endif()

function(oneport_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra)
    endif()
endfunction()

find_package(Threads REQUIRED)

add_subdirectory(bench/loop)
add_subdirectory(bench/server)
message(STATUS "oneport: backends ${ONEPORT_BACKENDS}")

enable_testing()
add_subdirectory(tests)
