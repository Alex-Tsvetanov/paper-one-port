# P3: oneport, the paper's own one-port server (design/proposal.md, section 2), the case generator
# opcase and the holder ophold (bench/cases), the load generator opgen (bench/gen), and the tests.
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

# The pinned third-party C libraries, OpenSSL and nghttp2 (bench/cmake/pins.cmake), built by
# bench/third_party/build_deps.sh into ONEPORT_OPT, one prefix per flavour: release for builds
# without a sanitizer, and asan, tsan or msan with the sanitizer of this build (proposal Z3).
# Linux only in M2; Windows builds them in M6. ONEPORT_OPENSSL_ROOT and ONEPORT_NGHTTP2_ROOT
# override the prefixes; the prefixes used are kept in the cache (ONEPORT_*_USED).
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(ONEPORT_OPT "$ENV{HOME}/opt" CACHE PATH "Where build_deps.sh installed the third-party libraries")
    set(ONEPORT_OPENSSL_ROOT "" CACHE PATH "Overrides the OpenSSL prefix")
    set(ONEPORT_NGHTTP2_ROOT "" CACHE PATH "Overrides the nghttp2 prefix")
    if(ONEPORT_SANITIZER STREQUAL "")
        set(_flavour release)
    elseif(ONEPORT_SANITIZER STREQUAL "address+undefined" OR ONEPORT_SANITIZER STREQUAL "address")
        set(_flavour asan)
    elseif(ONEPORT_SANITIZER STREQUAL "thread")
        set(_flavour tsan)
    elseif(ONEPORT_SANITIZER STREQUAL "memory")
        set(_flavour msan)
    else()
        message(FATAL_ERROR "no third-party flavour for ONEPORT_SANITIZER=${ONEPORT_SANITIZER}")
    endif()
    set(_ossl "${ONEPORT_OPT}/openssl-${ONEPORT_OPENSSL_VERSION}-${_flavour}")
    if(ONEPORT_OPENSSL_ROOT)
        set(_ossl "${ONEPORT_OPENSSL_ROOT}")
    endif()
    set(_ng "${ONEPORT_OPT}/nghttp2-${ONEPORT_NGHTTP2_VERSION}-${_flavour}")
    if(ONEPORT_NGHTTP2_ROOT)
        set(_ng "${ONEPORT_NGHTTP2_ROOT}")
    endif()
    foreach(_lib "${_ossl}/lib/libssl.a" "${_ossl}/lib/libcrypto.a" "${_ng}/lib/libnghttp2.a")
        if(NOT EXISTS "${_lib}")
            message(FATAL_ERROR "missing ${_lib}: run bench/third_party/build_deps.sh ${_flavour}")
        endif()
    endforeach()
    set(ONEPORT_OPENSSL_USED "${_ossl}" CACHE INTERNAL "The OpenSSL prefix this build links")
    set(ONEPORT_NGHTTP2_USED "${_ng}" CACHE INTERNAL "The nghttp2 prefix this build links")
    add_library(oneport_dep_crypto STATIC IMPORTED)
    set_target_properties(oneport_dep_crypto PROPERTIES IMPORTED_LOCATION "${_ossl}/lib/libcrypto.a"
                          INTERFACE_INCLUDE_DIRECTORIES "${_ossl}/include"
                          INTERFACE_LINK_LIBRARIES "Threads::Threads;${CMAKE_DL_LIBS}")
    add_library(oneport_dep_ssl STATIC IMPORTED)
    set_target_properties(oneport_dep_ssl PROPERTIES IMPORTED_LOCATION "${_ossl}/lib/libssl.a"
                          INTERFACE_INCLUDE_DIRECTORIES "${_ossl}/include"
                          INTERFACE_LINK_LIBRARIES oneport_dep_crypto)
    add_library(oneport_dep_nghttp2 STATIC IMPORTED)
    set_target_properties(oneport_dep_nghttp2 PROPERTIES IMPORTED_LOCATION "${_ng}/lib/libnghttp2.a"
                          INTERFACE_INCLUDE_DIRECTORIES "${_ng}/include")
    message(STATUS "oneport: OpenSSL ${_ossl}; nghttp2 ${_ng}")
    add_subdirectory(bench/tls)
elseif(WIN32)
    # M6a: the same libraries on W, built by bench/third_party/build_deps.ps1 with MSVC into
    # %USERPROFILE%/opt, one prefix per flavour: release for builds without a sanitizer, asan with
    # ONEPORT_SANITIZER=address. Static libraries; OpenSSL's need the Windows system libraries its
    # Configure names (ws2_32, gdi32, advapi32, crypt32, user32), and nghttp2's headers need
    # NGHTTP2_STATICLIB to declare a static library.
    file(TO_CMAKE_PATH "$ENV{USERPROFILE}/opt" _default_opt)
    set(ONEPORT_OPT "${_default_opt}" CACHE PATH "Where build_deps.ps1 installed the third-party libraries")
    set(ONEPORT_OPENSSL_ROOT "" CACHE PATH "Overrides the OpenSSL prefix")
    set(ONEPORT_NGHTTP2_ROOT "" CACHE PATH "Overrides the nghttp2 prefix")
    if(ONEPORT_SANITIZER STREQUAL "")
        set(_flavour release)
    elseif(ONEPORT_SANITIZER STREQUAL "address")
        set(_flavour asan)
    else()
        message(FATAL_ERROR "no third-party flavour for ONEPORT_SANITIZER=${ONEPORT_SANITIZER} on Windows")
    endif()
    set(_ossl "${ONEPORT_OPT}/openssl-${ONEPORT_OPENSSL_VERSION}-${_flavour}")
    if(ONEPORT_OPENSSL_ROOT)
        set(_ossl "${ONEPORT_OPENSSL_ROOT}")
    endif()
    set(_ng "${ONEPORT_OPT}/nghttp2-${ONEPORT_NGHTTP2_VERSION}-${_flavour}")
    if(ONEPORT_NGHTTP2_ROOT)
        set(_ng "${ONEPORT_NGHTTP2_ROOT}")
    endif()
    foreach(_lib "${_ossl}/lib/libssl.lib" "${_ossl}/lib/libcrypto.lib" "${_ng}/lib/nghttp2.lib")
        if(NOT EXISTS "${_lib}")
            message(FATAL_ERROR "missing ${_lib}: run bench/third_party/build_deps.ps1 ${_flavour}")
        endif()
    endforeach()
    set(ONEPORT_OPENSSL_USED "${_ossl}" CACHE INTERNAL "The OpenSSL prefix this build links")
    set(ONEPORT_NGHTTP2_USED "${_ng}" CACHE INTERNAL "The nghttp2 prefix this build links")
    add_library(oneport_dep_crypto STATIC IMPORTED)
    set_target_properties(oneport_dep_crypto PROPERTIES IMPORTED_LOCATION "${_ossl}/lib/libcrypto.lib"
                          INTERFACE_INCLUDE_DIRECTORIES "${_ossl}/include"
                          INTERFACE_LINK_LIBRARIES "ws2_32;gdi32;advapi32;crypt32;user32")
    add_library(oneport_dep_ssl STATIC IMPORTED)
    set_target_properties(oneport_dep_ssl PROPERTIES IMPORTED_LOCATION "${_ossl}/lib/libssl.lib"
                          INTERFACE_INCLUDE_DIRECTORIES "${_ossl}/include"
                          INTERFACE_LINK_LIBRARIES oneport_dep_crypto)
    add_library(oneport_dep_nghttp2 STATIC IMPORTED)
    set_target_properties(oneport_dep_nghttp2 PROPERTIES IMPORTED_LOCATION "${_ng}/lib/nghttp2.lib"
                          INTERFACE_INCLUDE_DIRECTORIES "${_ng}/include"
                          INTERFACE_COMPILE_DEFINITIONS NGHTTP2_STATICLIB)
    message(STATUS "oneport: OpenSSL ${_ossl}; nghttp2 ${_ng}")
    add_subdirectory(bench/tls)
endif()

add_subdirectory(bench/loop)
add_subdirectory(bench/server)
add_subdirectory(bench/cases)
add_subdirectory(bench/gen)
message(STATUS "oneport: backends ${ONEPORT_BACKENDS}")

enable_testing()
add_subdirectory(tests)
