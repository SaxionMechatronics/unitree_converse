# generated from ament/cmake/core/templates/nameConfig.cmake.in

# prevent multiple inclusion
if(_bob_llm_CONFIG_INCLUDED)
  # ensure to keep the found flag the same
  if(NOT DEFINED bob_llm_FOUND)
    # explicitly set it to FALSE, otherwise CMake will set it to TRUE
    set(bob_llm_FOUND FALSE)
  elseif(NOT bob_llm_FOUND)
    # use separate condition to avoid uninitialized variable warning
    set(bob_llm_FOUND FALSE)
  endif()
  return()
endif()
set(_bob_llm_CONFIG_INCLUDED TRUE)

# output package information
if(NOT bob_llm_FIND_QUIETLY)
  message(STATUS "Found bob_llm: 1.0.3 (${bob_llm_DIR})")
endif()

# warn when using a deprecated package
if(NOT "" STREQUAL "")
  set(_msg "Package 'bob_llm' is deprecated")
  # append custom deprecation text if available
  if(NOT "" STREQUAL "TRUE")
    set(_msg "${_msg} ()")
  endif()
  # optionally quiet the deprecation message
  if(NOT ${bob_llm_DEPRECATED_QUIET})
    message(DEPRECATION "${_msg}")
  endif()
endif()

# flag package as ament-based to distinguish it after being find_package()-ed
set(bob_llm_FOUND_AMENT_PACKAGE TRUE)

# include all config extra files
set(_extras "")
foreach(_extra ${_extras})
  include("${bob_llm_DIR}/${_extra}")
endforeach()
