pub mod core;

use crate::core::{Core, MAX_REQUEST_BYTES};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::Path;
use std::ptr;
use std::slice;
use std::str;
use std::sync::Mutex;

pub const ABI_VERSION: u32 = 1;
const MAX_PATH_BYTES: usize = 32 * 1024;

#[repr(i32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FfiStatus {
    Ok = 0,
    NullPointer = 1,
    InvalidArgument = 2,
    InvalidUtf8 = 3,
    OpenFailed = 4,
    BufferTooSmall = 5,
    Internal = 6,
    Panic = 7,
}

pub struct ProbeHandle {
    state: Mutex<HandleState>,
}

struct HandleState {
    core: Core,
    pending: Option<PendingResponse>,
}

struct PendingResponse {
    request: Vec<u8>,
    response: Vec<u8>,
}

#[unsafe(no_mangle)]
pub extern "C" fn nabla_core_probe_abi_version() -> u32 {
    ABI_VERSION
}

#[unsafe(no_mangle)]
pub extern "C" fn nabla_core_probe_max_request_bytes() -> usize {
    MAX_REQUEST_BYTES
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn nabla_core_probe_open(
    path: *const u8,
    path_len: usize,
    out_handle: *mut *mut ProbeHandle,
) -> i32 {
    ffi_guard(|| {
        if out_handle.is_null() {
            return FfiStatus::NullPointer as i32;
        }
        // SAFETY: out_handle was checked for null and the caller contract requires
        // writable storage for one pointer.
        unsafe {
            *out_handle = ptr::null_mut();
        }

        if path_len == 0 || path_len > MAX_PATH_BYTES {
            return FfiStatus::InvalidArgument as i32;
        }
        if path.is_null() {
            return FfiStatus::NullPointer as i32;
        }

        // SAFETY: path is non-null and the caller contract guarantees path_len
        // readable bytes for the duration of this call.
        let path_bytes = unsafe { slice::from_raw_parts(path, path_len) };
        let path_text = match str::from_utf8(path_bytes) {
            Ok(value) => value,
            Err(_) => return FfiStatus::InvalidUtf8 as i32,
        };

        let core = match Core::open(Path::new(path_text)) {
            Ok(core) => core,
            Err(_) => return FfiStatus::OpenFailed as i32,
        };
        let handle = Box::new(ProbeHandle {
            state: Mutex::new(HandleState {
                core,
                pending: None,
            }),
        });
        // SAFETY: out_handle is writable as established above. Ownership of the
        // Box transfers to the caller until exactly one close call.
        unsafe {
            *out_handle = Box::into_raw(handle);
        }
        FfiStatus::Ok as i32
    })
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn nabla_core_probe_execute(
    handle: *mut ProbeHandle,
    request: *const u8,
    request_len: usize,
    output: *mut u8,
    output_capacity: usize,
    out_len: *mut usize,
) -> i32 {
    ffi_guard(|| {
        if out_len.is_null() || handle.is_null() {
            return FfiStatus::NullPointer as i32;
        }
        // SAFETY: out_len is non-null and the caller contract requires writable
        // storage for one usize.
        unsafe {
            *out_len = 0;
        }

        if request_len > 0 && request.is_null() {
            return FfiStatus::NullPointer as i32;
        }
        if request_len > MAX_REQUEST_BYTES {
            return FfiStatus::InvalidArgument as i32;
        }
        if output_capacity > 0 && output.is_null() {
            return FfiStatus::NullPointer as i32;
        }
        let request_bytes = if request_len == 0 {
            &[]
        } else {
            // SAFETY: request is non-null for a non-zero length and the caller
            // contract guarantees request_len readable bytes.
            unsafe { slice::from_raw_parts(request, request_len) }
        };

        // SAFETY: handle is non-null and must originate from nabla_core_probe_open.
        let handle = unsafe { &*handle };
        let mut state = match handle.state.lock() {
            Ok(guard) => guard,
            // The panic probe intentionally poisons this mutex. Recovery of the
            // contained Core demonstrates that the FFI process remains usable.
            Err(poisoned) => poisoned.into_inner(),
        };
        if let Some(pending) = state.pending.as_ref() {
            if pending.request != request_bytes {
                return FfiStatus::InvalidArgument as i32;
            }
            // SAFETY: out_len is writable as established above.
            unsafe {
                *out_len = pending.response.len();
            }
            if output_capacity < pending.response.len() {
                return FfiStatus::BufferTooSmall as i32;
            }
            if !pending.response.is_empty() {
                // SAFETY: output is non-null, output_capacity is large enough,
                // and the source and destination do not overlap.
                unsafe {
                    ptr::copy_nonoverlapping(
                        pending.response.as_ptr(),
                        output,
                        pending.response.len(),
                    );
                }
            }
            state.pending = None;
            return FfiStatus::Ok as i32;
        }

        let response = state.core.execute_json(request_bytes);

        // SAFETY: out_len is writable as established above.
        unsafe {
            *out_len = response.len();
        }
        if output_capacity < response.len() {
            state.pending = Some(PendingResponse {
                request: request_bytes.to_vec(),
                response,
            });
            return FfiStatus::BufferTooSmall as i32;
        }

        if !response.is_empty() {
            // SAFETY: output is non-null, output_capacity is large enough, and
            // the source and destination do not overlap by the caller contract.
            unsafe {
                ptr::copy_nonoverlapping(response.as_ptr(), output, response.len());
            }
        }
        FfiStatus::Ok as i32
    })
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn nabla_core_probe_close(handle: *mut ProbeHandle) -> i32 {
    ffi_guard(|| {
        if handle.is_null() {
            return FfiStatus::NullPointer as i32;
        }
        // SAFETY: handle must be a live pointer returned by open and close must be
        // called exactly once. Reconstructing the Box releases its resources.
        unsafe {
            drop(Box::from_raw(handle));
        }
        FfiStatus::Ok as i32
    })
}

fn ffi_guard(operation: impl FnOnce() -> i32) -> i32 {
    match catch_unwind(AssertUnwindSafe(operation)) {
        Ok(status) => status,
        Err(_) => FfiStatus::Panic as i32,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(1);

    struct TempDatabase {
        path: PathBuf,
    }

    impl TempDatabase {
        fn new() -> Self {
            let unique = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "nabla-core-portability-ffi-{}-{unique}.sqlite3",
                std::process::id()
            ));
            Self { path }
        }
    }

    impl Drop for TempDatabase {
        fn drop(&mut self) {
            for suffix in ["", "-wal", "-shm"] {
                let candidate = PathBuf::from(format!("{}{suffix}", self.path.display()));
                let _ = fs::remove_file(candidate);
            }
        }
    }

    unsafe fn execute_via_ffi(handle: *mut ProbeHandle, request: &[u8]) -> (i32, Vec<u8>) {
        let mut required = 0usize;
        // SAFETY: the handle and request are live for the duration of the call.
        let sizing = unsafe {
            nabla_core_probe_execute(
                handle,
                request.as_ptr(),
                request.len(),
                ptr::null_mut(),
                0,
                &mut required,
            )
        };
        if sizing != FfiStatus::BufferTooSmall as i32 {
            return (sizing, Vec::new());
        }

        let mut output = vec![0u8; required];
        // SAFETY: output has exactly the capacity reported by the sizing call.
        let status = unsafe {
            nabla_core_probe_execute(
                handle,
                request.as_ptr(),
                request.len(),
                output.as_mut_ptr(),
                output.len(),
                &mut required,
            )
        };
        output.truncate(required);
        (status, output)
    }

    #[test]
    fn ffi_reports_version_nulls_and_buffer_requirements() {
        assert_eq!(nabla_core_probe_abi_version(), ABI_VERSION);
        assert_eq!(nabla_core_probe_max_request_bytes(), MAX_REQUEST_BYTES);

        let database = TempDatabase::new();
        let path = database.path.to_string_lossy();
        let mut handle: *mut ProbeHandle = ptr::null_mut();

        // SAFETY: these calls deliberately exercise documented null validation.
        unsafe {
            assert_eq!(
                nabla_core_probe_open(path.as_ptr(), path.len(), ptr::null_mut()),
                FfiStatus::NullPointer as i32
            );
            assert_eq!(
                nabla_core_probe_open(ptr::null(), 1, &mut handle),
                FfiStatus::NullPointer as i32
            );
            assert_eq!(
                nabla_core_probe_open(path.as_ptr(), path.len(), &mut handle),
                FfiStatus::Ok as i32
            );
            assert!(!handle.is_null());

            let mut required = 0usize;
            assert_eq!(
                nabla_core_probe_execute(
                    ptr::null_mut(),
                    ptr::null(),
                    0,
                    ptr::null_mut(),
                    0,
                    &mut required,
                ),
                FfiStatus::NullPointer as i32
            );
            assert_eq!(
                nabla_core_probe_execute(handle, ptr::null(), 1, ptr::null_mut(), 0, &mut required,),
                FfiStatus::NullPointer as i32
            );
            let oversized = vec![b'x'; MAX_REQUEST_BYTES + 1];
            assert_eq!(
                nabla_core_probe_execute(
                    handle,
                    oversized.as_ptr(),
                    oversized.len(),
                    ptr::null_mut(),
                    0,
                    &mut required,
                ),
                FfiStatus::InvalidArgument as i32
            );
            assert_eq!(required, 0);

            let request = br#"{"op":"inspect"}"#;
            assert_eq!(
                nabla_core_probe_execute(
                    handle,
                    request.as_ptr(),
                    request.len(),
                    ptr::null_mut(),
                    0,
                    &mut required,
                ),
                FfiStatus::BufferTooSmall as i32
            );
            assert!(required > 0);

            let interleaved = br#"{"op":"integrity"}"#;
            let mut interleaved_len = usize::MAX;
            assert_eq!(
                nabla_core_probe_execute(
                    handle,
                    interleaved.as_ptr(),
                    interleaved.len(),
                    ptr::null_mut(),
                    0,
                    &mut interleaved_len,
                ),
                FfiStatus::InvalidArgument as i32
            );
            assert_eq!(interleaved_len, 0);

            let mut undersized = vec![0u8; required - 1];
            assert_eq!(
                nabla_core_probe_execute(
                    handle,
                    request.as_ptr(),
                    request.len(),
                    undersized.as_mut_ptr(),
                    undersized.len(),
                    &mut required,
                ),
                FfiStatus::BufferTooSmall as i32
            );

            let mut exact = vec![0u8; required];
            assert_eq!(
                nabla_core_probe_execute(
                    handle,
                    request.as_ptr(),
                    request.len(),
                    exact.as_mut_ptr(),
                    exact.len(),
                    &mut required,
                ),
                FfiStatus::Ok as i32
            );

            let dummy = 0u8;
            assert_eq!(
                nabla_core_probe_execute(
                    handle,
                    &dummy,
                    usize::MAX,
                    ptr::null_mut(),
                    0,
                    &mut required,
                ),
                FfiStatus::InvalidArgument as i32
            );
            assert_eq!(required, 0);

            assert_eq!(
                nabla_core_probe_close(ptr::null_mut()),
                FfiStatus::NullPointer as i32
            );
            assert_eq!(nabla_core_probe_close(handle), FfiStatus::Ok as i32);
        }
    }

    #[test]
    fn ffi_executes_the_shared_core_contract() {
        let database = TempDatabase::new();
        let path = database.path.to_string_lossy();
        let mut handle: *mut ProbeHandle = ptr::null_mut();

        // SAFETY: handle storage and path bytes are valid for the calls.
        unsafe {
            assert_eq!(
                nabla_core_probe_open(path.as_ptr(), path.len(), &mut handle),
                FfiStatus::Ok as i32
            );
            let request =
                br#"{"op":"apply","request_id":"ffi-1","fact_id":"fact-1","value":"alpha"}"#;
            let (status, output) = execute_via_ffi(handle, request);
            assert_eq!(status, FfiStatus::Ok as i32);
            let response: Value = serde_json::from_slice(&output).unwrap();
            assert_eq!(response["code"], "APPLIED");

            let (_, replay_output) = execute_via_ffi(handle, request);
            let replay: Value = serde_json::from_slice(&replay_output).unwrap();
            assert_eq!(replay["code"], "REPLAYED");

            assert_eq!(nabla_core_probe_close(handle), FfiStatus::Ok as i32);
        }
    }

    #[test]
    fn ffi_contains_panics_without_unwinding_or_losing_the_handle() {
        let database = TempDatabase::new();
        let path = database.path.to_string_lossy();
        let mut handle: *mut ProbeHandle = ptr::null_mut();

        // SAFETY: handle storage and path bytes are valid for the calls.
        unsafe {
            assert_eq!(
                nabla_core_probe_open(path.as_ptr(), path.len(), &mut handle),
                FfiStatus::Ok as i32
            );

            let panic_request = br#"{"op":"panic_probe"}"#;
            let mut output_len = usize::MAX;
            assert_eq!(
                nabla_core_probe_execute(
                    handle,
                    panic_request.as_ptr(),
                    panic_request.len(),
                    ptr::null_mut(),
                    0,
                    &mut output_len,
                ),
                FfiStatus::Panic as i32
            );
            assert_eq!(output_len, 0);

            let (status, output) = execute_via_ffi(handle, br#"{"op":"integrity"}"#);
            assert_eq!(status, FfiStatus::Ok as i32);
            let response: Value = serde_json::from_slice(&output).unwrap();
            assert_eq!(response["integrity"], "ok");

            assert_eq!(nabla_core_probe_close(handle), FfiStatus::Ok as i32);
        }
    }
}
