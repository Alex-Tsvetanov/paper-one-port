//! The hyper-util harness of hypotheses.md, Appendix B (CP9 of design/proposal.md):
//! `server::conn::auto` on a tokio runtime with one worker thread, HTTP/1.1 and h2c (prior
//! knowledge) told apart by the first 24 bytes; no detection timer, none added (hyper-util has none;
//! design/competitor-survey.md, 2.12). Every reply is the server's: 200, Content-Length 13,
//! "Hello, World!" (hypotheses.md, section 2.1).
//!
//! Arguments (bench/competitors/hyper-util/cases.args and b3.args, rendered by competitors.py):
//!   --port N      the listener
//!   --backlog N   listen through tokio's TcpSocket::listen with this backlog (0: TcpListener::bind,
//!                 tokio's default backlog of 1024)
//! Prints "hyper-util: listening <port>".
//!
//! SIGTERM, which every runner sends to stop a system (bench/competitors/competitors.py, stop),
//! ends the harness by a normal exit (M7): its handler writes one byte to a socket pair, the accept
//! loop sees it and returns, the runtime is dropped (its tasks, the connections among them, are
//! dropped and its threads joined), "hyper-util: stopped by SIGTERM" is printed and main returns,
//! so the sanitizers' exit checks run (LeakSanitizer's at exit under -Zsanitizer=address). The
//! default action ended the process before them. The handler is installed with glibc's signal(2)
//! and writes with write(2), both declared here: std links glibc already, so no crate is added.

use std::convert::Infallible;
use std::net::SocketAddr;
use std::os::raw::{c_int, c_void};
use std::os::unix::io::AsRawFd;
use std::os::unix::net::UnixStream as StdUnixStream;
use std::sync::atomic::{AtomicI32, Ordering};

use bytes::Bytes;
use http_body_util::Full;
use hyper::body::Incoming;
use hyper::service::service_fn;
use hyper::{Request, Response};
use hyper_util::rt::{TokioExecutor, TokioIo};
use hyper_util::server::conn::auto::Builder;
use tokio::net::{TcpListener, TcpSocket, UnixStream};

const BODY: &[u8] = b"Hello, World!";

/// SIGTERM's number on Linux (include/uapi/asm-generic/signal.h), the only platform it runs on.
const SIGTERM: c_int = 15;
/// signal(2)'s error return, SIG_ERR, as an address.
const SIG_ERR: usize = usize::MAX;

/// The write end of the socket pair the SIGTERM handler writes to; -1 while there is none.
static TERM_FD: AtomicI32 = AtomicI32::new(-1);

extern "C" {
    fn signal(signum: c_int, handler: usize) -> usize;
    fn write(fd: c_int, buf: *const c_void, count: usize) -> isize;
}

/// The SIGTERM handler: one byte to the socket pair, nothing else.
extern "C" fn on_term(_: c_int) {
    let fd = TERM_FD.load(Ordering::Relaxed);
    if fd >= 0 {
        let byte = 1u8;
        // SAFETY: write(2) is async-signal-safe, `fd` is the open write end of the pair (it is
        // closed only after TERM_FD is set back to -1), and `byte` lives for the call.
        unsafe { write(fd, (&byte as *const u8).cast::<c_void>(), 1) };
    }
}

fn usage() -> ! {
    eprintln!("usage: oneport-hyper-util --port N [--backlog N]");
    std::process::exit(2);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (mut port, mut backlog) = (0u16, 0u32);
    if args.len() % 2 != 0 {
        usage();
    }
    for pair in args.chunks(2) {
        match pair[0].as_str() {
            "--port" => port = pair[1].parse().unwrap_or_else(|_| usage()),
            "--backlog" => backlog = pair[1].parse().unwrap_or_else(|_| usage()),
            _ => usage(),
        }
    }
    if port == 0 {
        usage();
    }
    let (term_rx, term_tx) = StdUnixStream::pair().expect("the SIGTERM socket pair");
    term_rx.set_nonblocking(true).expect("the SIGTERM socket pair: non-blocking");
    TERM_FD.store(term_tx.as_raw_fd(), Ordering::Relaxed);
    let handler: extern "C" fn(c_int) = on_term;
    // SAFETY: on_term only loads an atomic and calls write(2), both async-signal-safe.
    if unsafe { signal(SIGTERM, handler as usize) } == SIG_ERR {
        eprintln!("hyper-util: signal(SIGTERM) failed");
        std::process::exit(1);
    }
    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .enable_all()
        .build()
        .expect("the tokio runtime");
    rt.block_on(serve(port, backlog, term_rx));
    drop(rt);
    TERM_FD.store(-1, Ordering::Relaxed);
    drop(term_tx);
    println!("hyper-util: stopped by SIGTERM");
}

async fn serve(port: u16, backlog: u32, term: StdUnixStream) {
    let term = UnixStream::from_std(term).expect("the SIGTERM socket pair in the runtime");
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = if backlog > 0 {
        let s = TcpSocket::new_v4().expect("socket");
        // As TcpListener::bind does on Unix (mio sets SO_REUSEADDR), so only the backlog differs.
        s.set_reuseaddr(true).expect("SO_REUSEADDR");
        s.bind(addr).expect("bind");
        s.listen(backlog).expect("listen")
    } else {
        TcpListener::bind(addr).await.expect("bind")
    };
    println!("hyper-util: listening {port} (backlog {})", if backlog > 0 { backlog.to_string() } else { "tokio's default".into() });
    loop {
        let accepted = tokio::select! {
            a = listener.accept() => a,
            _ = term.readable() => return,  // SIGTERM (on_term)
        };
        let (stream, _) = match accepted {
            Ok(x) => x,
            Err(_) => continue,
        };
        tokio::spawn(async move {
            let _ = Builder::new(TokioExecutor::new())
                .serve_connection(TokioIo::new(stream), service_fn(hello))
                .await;
        });
    }
}

async fn hello(_: Request<Incoming>) -> Result<Response<Full<Bytes>>, Infallible> {
    Ok(Response::new(Full::new(Bytes::from_static(BODY))))
}
