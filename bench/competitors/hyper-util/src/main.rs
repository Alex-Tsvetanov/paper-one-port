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
//! Prints "hyper-util: listening <port>". SIGTERM ends it (the default action).

use std::convert::Infallible;
use std::net::SocketAddr;

use bytes::Bytes;
use http_body_util::Full;
use hyper::body::Incoming;
use hyper::service::service_fn;
use hyper::{Request, Response};
use hyper_util::rt::{TokioExecutor, TokioIo};
use hyper_util::server::conn::auto::Builder;
use tokio::net::{TcpListener, TcpSocket};

const BODY: &[u8] = b"Hello, World!";

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
    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .enable_all()
        .build()
        .expect("the tokio runtime");
    rt.block_on(serve(port, backlog));
}

async fn serve(port: u16, backlog: u32) {
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
        let (stream, _) = match listener.accept().await {
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
