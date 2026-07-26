#ifndef NABLA_CORE_PROBE_H
#define NABLA_CORE_PROBE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct NablaCoreProbeHandle NablaCoreProbeHandle;

enum NablaCoreProbeStatus {
  NABLA_CORE_PROBE_OK = 0,
  NABLA_CORE_PROBE_NULL_POINTER = 1,
  NABLA_CORE_PROBE_INVALID_ARGUMENT = 2,
  NABLA_CORE_PROBE_INVALID_UTF8 = 3,
  NABLA_CORE_PROBE_OPEN_FAILED = 4,
  NABLA_CORE_PROBE_BUFFER_TOO_SMALL = 5,
  NABLA_CORE_PROBE_INTERNAL = 6,
  NABLA_CORE_PROBE_PANIC = 7
};

uint32_t nabla_core_probe_abi_version(void);
size_t nabla_core_probe_max_request_bytes(void);

/* path is an untrusted, non-empty UTF-8 byte string. out_handle receives one
 * opaque handle owned by the caller on NABLA_CORE_PROBE_OK. Calls on a handle
 * are serialized internally; close must run exactly once and must not race
 * execute. */
int32_t nabla_core_probe_open(const uint8_t *path,
                              size_t path_len,
                              NablaCoreProbeHandle **out_handle);

int32_t nabla_core_probe_execute(NablaCoreProbeHandle *handle,
                                 const uint8_t *request,
                                 size_t request_len,
                                 uint8_t *output,
                                 size_t output_capacity,
                                 size_t *out_len);

/* Requests larger than nabla_core_probe_max_request_bytes() are rejected with
 * NABLA_CORE_PROBE_INVALID_ARGUMENT before any request-sized allocation. */
/* Each handle permits one outstanding BUFFER_TOO_SMALL response. The caller
 * must retry that same request until it succeeds before issuing another
 * request; an interleaved request returns NABLA_CORE_PROBE_INVALID_ARGUMENT. */

int32_t nabla_core_probe_close(NablaCoreProbeHandle *handle);

#ifdef __cplusplus
}
#endif

#endif
