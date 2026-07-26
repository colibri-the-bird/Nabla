use nabla_core_portability_probe::core::{
    Core, MAX_REQUEST_BYTES, encode_response, panic_contained_response, request_too_large_response,
};
use std::env;
use std::ffi::OsString;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::PathBuf;

enum BoundedLine {
    Eof,
    Line(Vec<u8>),
    TooLong,
}

fn main() {
    if let Err(message) = run() {
        eprintln!(
            "{{\"status\":\"error\",\"code\":\"SERVICE_START_FAILED\",\"message\":{}}}",
            serde_json::to_string(&message).unwrap_or_else(|_| "\"startup failed\"".into())
        );
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let database_path = parse_database_path(env::args_os().skip(1))?;
    let mut core = Core::open(&database_path)
        .map_err(|_| "unable to open the probe SQLite database".to_string())?;

    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = BufReader::new(stdin.lock());
    let mut output = BufWriter::new(stdout.lock());

    loop {
        let response = match read_bounded_line(&mut input, MAX_REQUEST_BYTES)
            .map_err(|_| "failed to read service input".to_string())?
        {
            BoundedLine::Eof => break,
            BoundedLine::TooLong => encode_response(&request_too_large_response()),
            BoundedLine::Line(line) => {
                match catch_unwind(AssertUnwindSafe(|| core.execute_service_json(&line))) {
                    Ok(response) => response,
                    Err(_) => encode_response(&panic_contained_response()),
                }
            }
        };
        output
            .write_all(&response)
            .and_then(|_| output.write_all(b"\n"))
            .and_then(|_| output.flush())
            .map_err(|_| "failed to write service output".to_string())?;
    }
    Ok(())
}

fn parse_database_path(mut args: impl Iterator<Item = OsString>) -> Result<PathBuf, String> {
    match (args.next(), args.next(), args.next()) {
        (Some(flag), Some(path), None) if flag == "--db" => Ok(PathBuf::from(path)),
        _ => Err("usage: nabla-core-probe-service --db <sqlite-path>".into()),
    }
}

fn read_bounded_line(reader: &mut impl BufRead, max_bytes: usize) -> io::Result<BoundedLine> {
    let mut line = Vec::with_capacity(max_bytes.min(4096));
    let mut too_long = false;
    let mut saw_bytes = false;

    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return if !saw_bytes {
                Ok(BoundedLine::Eof)
            } else if too_long {
                Ok(BoundedLine::TooLong)
            } else {
                if line.last() == Some(&b'\r') {
                    line.pop();
                }
                Ok(BoundedLine::Line(line))
            };
        }

        saw_bytes = true;
        let newline = available.iter().position(|byte| *byte == b'\n');
        let chunk_len = newline.unwrap_or(available.len());

        if !too_long {
            if line.len() + chunk_len > max_bytes {
                too_long = true;
            } else {
                line.extend_from_slice(&available[..chunk_len]);
            }
        }

        let consumed = chunk_len + usize::from(newline.is_some());
        reader.consume(consumed);

        if newline.is_some() {
            return if too_long {
                Ok(BoundedLine::TooLong)
            } else {
                if line.last() == Some(&b'\r') {
                    line.pop();
                }
                Ok(BoundedLine::Line(line))
            };
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn bounded_reader_returns_individual_lines() {
        let mut input = Cursor::new(b"one\r\ntwo\nthree".to_vec());
        match read_bounded_line(&mut input, 8).unwrap() {
            BoundedLine::Line(line) => assert_eq!(line, b"one"),
            _ => panic!("expected first line"),
        }
        match read_bounded_line(&mut input, 8).unwrap() {
            BoundedLine::Line(line) => assert_eq!(line, b"two"),
            _ => panic!("expected second line"),
        }
        match read_bounded_line(&mut input, 8).unwrap() {
            BoundedLine::Line(line) => assert_eq!(line, b"three"),
            _ => panic!("expected final line"),
        }
        assert!(matches!(
            read_bounded_line(&mut input, 8).unwrap(),
            BoundedLine::Eof
        ));
    }

    #[test]
    fn oversized_line_is_drained_before_the_next_request() {
        let mut input = Cursor::new(b"123456789\nok\n".to_vec());
        assert!(matches!(
            read_bounded_line(&mut input, 8).unwrap(),
            BoundedLine::TooLong
        ));
        match read_bounded_line(&mut input, 8).unwrap() {
            BoundedLine::Line(line) => assert_eq!(line, b"ok"),
            _ => panic!("expected the request after the oversized line"),
        }
    }
}
