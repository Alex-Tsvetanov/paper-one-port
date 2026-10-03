// The Netty harness of hypotheses.md, Appendix B (CP6 of design/proposal.md): one listener on Netty's
// native epoll transport that tells TLS, h2c and HTTP/1.1 apart by their first bytes, after Netty's
// PortUnificationServerHandler example (example/.../portunification/PortUnificationServerHandler.java
// at netty-4.2.18.Final, Apache License 2.0; design/competitor-survey.md, 2.15), with Netty's
// built-ins: SniHandler for TLS, CleartextHttp2ServerUpgradeHandler for h2c (prior knowledge or
// Upgrade) and HTTP/1.1 with the HTTP codec, HAProxyMessageDecoder on the listener that requires the
// PROXY header, and ReadTimeoutHandler as the detection timer. Every reply is the server's: 200,
// Content-Length 13, "Hello, World!" (hypotheses.md, section 2.1).
//
// What differs from the example, each for the frozen line: the example's gzip and factorial
// protocols are left out (not in Appendix B); TLS goes through SniHandler, not a bare SslHandler; HTTP
// goes to CleartextHttp2ServerUpgradeHandler, so the h2c preface ("PR", which the example's method
// list lacks) is HTTP too; after TLS the decrypted bytes are detected again, as in the example.
//
// Arguments (bench/competitors/netty/cases.args and b3.args, rendered by competitors.py):
//   --port N          the listener
//   --proxy-port N    a second listener that requires the PROXY header (0: none)
//   --timer-s N       ReadTimeoutHandler and SniHandler's handshake timeout, in seconds (0: neither is
//                     configured: ReadTimeoutHandler has no default and is left out; SniHandler keeps
//                     its default, 10 s)
//   --backlog N       ChannelOption.SO_BACKLOG (0: Netty's default, NetUtil.SOMAXCONN)
//   --cert F --key F  the test certificate and key (tests/fixtures/tls)
// Prints "netty: listening <port>" per listener, then one line with the allocators the first
// accepted connection uses. Stops on SIGTERM (the JVM's shutdown hook closes the event loop).
package oneport;

import io.netty.bootstrap.ServerBootstrap;
import io.netty.buffer.ByteBuf;
import io.netty.buffer.Unpooled;
import io.netty.channel.Channel;
import io.netty.channel.ChannelDuplexHandler;
import io.netty.channel.ChannelFutureListener;
import io.netty.channel.ChannelHandler;
import io.netty.channel.ChannelHandlerContext;
import io.netty.channel.ChannelInboundHandlerAdapter;
import io.netty.channel.ChannelInitializer;
import io.netty.channel.ChannelOption;
import io.netty.channel.ChannelPipeline;
import io.netty.channel.EventLoopGroup;
import io.netty.channel.MultiThreadIoEventLoopGroup;
import io.netty.channel.SimpleChannelInboundHandler;
import io.netty.channel.epoll.Epoll;
import io.netty.channel.epoll.EpollIoHandler;
import io.netty.channel.epoll.EpollServerSocketChannel;
import io.netty.handler.codec.ByteToMessageDecoder;
import io.netty.handler.codec.haproxy.HAProxyMessage;
import io.netty.handler.codec.haproxy.HAProxyMessageDecoder;
import io.netty.handler.codec.http.DefaultFullHttpResponse;
import io.netty.handler.codec.http.FullHttpResponse;
import io.netty.handler.codec.http.HttpHeaderNames;
import io.netty.handler.codec.http.HttpHeaderValues;
import io.netty.handler.codec.http.HttpObject;
import io.netty.handler.codec.http.HttpRequest;
import io.netty.handler.codec.http.HttpResponseStatus;
import io.netty.handler.codec.http.HttpServerCodec;
import io.netty.handler.codec.http.HttpServerUpgradeHandler;
import io.netty.handler.codec.http.HttpUtil;
import io.netty.handler.codec.http.HttpVersion;
import io.netty.handler.codec.http2.CleartextHttp2ServerUpgradeHandler;
import io.netty.handler.codec.http2.DefaultHttp2DataFrame;
import io.netty.handler.codec.http2.DefaultHttp2Headers;
import io.netty.handler.codec.http2.DefaultHttp2HeadersFrame;
import io.netty.handler.codec.http2.Http2CodecUtil;
import io.netty.handler.codec.http2.Http2FrameCodec;
import io.netty.handler.codec.http2.Http2FrameCodecBuilder;
import io.netty.handler.codec.http2.Http2FrameStream;
import io.netty.handler.codec.http2.Http2HeadersFrame;
import io.netty.handler.codec.http2.Http2DataFrame;
import io.netty.handler.codec.http2.Http2ServerUpgradeCodec;
import io.netty.handler.ssl.ApplicationProtocolConfig;
import io.netty.handler.ssl.ApplicationProtocolNames;
import io.netty.handler.ssl.SniHandler;
import io.netty.handler.ssl.SslContext;
import io.netty.handler.ssl.SslContextBuilder;
import io.netty.handler.ssl.SslHandler;
import io.netty.handler.ssl.SslProvider;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.util.AsciiString;
import io.netty.util.CharsetUtil;
import io.netty.util.DomainWildcardMappingBuilder;
import io.netty.util.Mapping;
import io.netty.util.ReferenceCountUtil;

import java.io.File;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public final class NettyHarness {
    static final byte[] BODY = "Hello, World!".getBytes(CharsetUtil.US_ASCII);
    static final AtomicBoolean PRINTED = new AtomicBoolean();

    record Options(int port, int proxyPort, int timerS, int backlog, File cert, File key) {
        static Options parse(String[] args) {
            int port = 0, proxyPort = 0, timerS = 0, backlog = 0;
            File cert = null, key = null;
            for (int i = 0; i + 1 < args.length; i += 2) {
                switch (args[i]) {
                    case "--port" -> port = Integer.parseInt(args[i + 1]);
                    case "--proxy-port" -> proxyPort = Integer.parseInt(args[i + 1]);
                    case "--timer-s" -> timerS = Integer.parseInt(args[i + 1]);
                    case "--backlog" -> backlog = Integer.parseInt(args[i + 1]);
                    case "--cert" -> cert = new File(args[i + 1]);
                    case "--key" -> key = new File(args[i + 1]);
                    default -> throw new IllegalArgumentException("unknown argument " + args[i]);
                }
            }
            if (args.length % 2 != 0 || port <= 0 || cert == null || key == null) {
                throw new IllegalArgumentException("usage: --port N [--proxy-port N] [--timer-s N] [--backlog N] --cert F --key F");
            }
            return new Options(port, proxyPort, timerS, backlog, cert, key);
        }
    }

    public static void main(String[] args) throws Exception {
        Options o = Options.parse(args);
        // The native transport or nothing: ensureAvailability throws if Netty's epoll library cannot
        // load, so the harness never runs on another transport (Appendix B: "the native epoll
        // transport").
        Epoll.ensureAvailability();
        // TLS: the test certificate; TLS 1.3 and TLS_AES_128_GCM_SHA256 as the server's (section 2.1);
        // the group and signature scheme by the JSSE properties in bench/competitors/jvm.args; ALPN
        // offers h2 and http/1.1. The JDK's provider: netty-tcnative is not among the pinned artifacts.
        SslContext ssl = SslContextBuilder.forServer(o.cert(), o.key())
                .sslProvider(SslProvider.JDK)
                .protocols("TLSv1.3")
                .ciphers(List.of("TLS_AES_128_GCM_SHA256"))
                .applicationProtocolConfig(new ApplicationProtocolConfig(
                        ApplicationProtocolConfig.Protocol.ALPN,
                        ApplicationProtocolConfig.SelectorFailureBehavior.NO_ADVERTISE,
                        ApplicationProtocolConfig.SelectedListenerFailureBehavior.ACCEPT,
                        ApplicationProtocolNames.HTTP_2, ApplicationProtocolNames.HTTP_1_1))
                .build();
        Mapping<String, SslContext> sni = new DomainWildcardMappingBuilder<>(ssl).add("oneport.test", ssl).build();
        // One event loop thread, the server's core count (Appendix B: "in B3 every competitor gets the
        // server's core count"); the accepting and the connections share it.
        EventLoopGroup group = new MultiThreadIoEventLoopGroup(1, EpollIoHandler.newFactory());
        try {
            Channel plain = bind(group, o, o.port(), false, sni);
            System.out.println("netty: listening " + o.port());
            Channel proxied = null;
            if (o.proxyPort() > 0) {
                proxied = bind(group, o, o.proxyPort(), true, sni);
                System.out.println("netty: listening " + o.proxyPort() + " (PROXY required)");
            }
            System.out.flush();
            Runtime.getRuntime().addShutdownHook(new Thread(() -> group.shutdownGracefully(0, 2, TimeUnit.SECONDS).syncUninterruptibly()));
            plain.closeFuture().sync();
            if (proxied != null) {
                proxied.closeFuture().sync();
            }
        } finally {
            group.shutdownGracefully(0, 2, TimeUnit.SECONDS);
        }
    }

    static Channel bind(EventLoopGroup group, Options o, int port, boolean proxy, Mapping<String, SslContext> sni) throws InterruptedException {
        ServerBootstrap b = new ServerBootstrap().group(group).channel(EpollServerSocketChannel.class);
        if (o.backlog() > 0) {
            b.option(ChannelOption.SO_BACKLOG, o.backlog());
        }
        b.childHandler(new ChannelInitializer<Channel>() {
            @Override
            protected void initChannel(Channel ch) {
                if (PRINTED.compareAndSet(false, true)) {
                    System.out.println("netty: first connection: allocator " + ch.config().getAllocator().getClass().getName()
                            + ", receive allocator " + ch.config().getRecvByteBufAllocator().getClass().getName());
                    System.out.flush();
                }
                ChannelPipeline p = ch.pipeline();
                if (o.timerS() > 0) {
                    p.addLast("timeout", new ReadTimeoutHandler(o.timerS()));
                }
                if (proxy) {
                    p.addLast("proxy", new HAProxyMessageDecoder());
                    p.addLast("proxy-message", new ProxyMessage());
                }
                p.addLast("detect", new Detect(sni, o.timerS(), true));
                p.addLast("close-on-error", new CloseOnError());
            }
        });
        return b.bind("127.0.0.1", port).sync().channel();
    }

    /** The decoded PROXY header: consumed and released; the bytes after it go on to detection. */
    static final class ProxyMessage extends ChannelInboundHandlerAdapter {
        @Override
        public void channelRead(ChannelHandlerContext ctx, Object msg) {
            if (msg instanceof HAProxyMessage m) {
                m.release();
                ctx.pipeline().remove(this);
                return;
            }
            ctx.fireChannelRead(msg);
        }
    }

    /** Last in every pipeline: an exception (a malformed PROXY header, a TLS alert) closes. */
    static final class CloseOnError extends ChannelInboundHandlerAdapter {
        @Override
        public void exceptionCaught(ChannelHandlerContext ctx, Throwable cause) {
            ctx.close();
        }
    }

    /** The example's detection: five bytes, read without consuming them. */
    static final class Detect extends ByteToMessageDecoder {
        private final Mapping<String, SslContext> sni;
        private final int timerS;
        private final boolean detectTls;

        Detect(Mapping<String, SslContext> sni, int timerS, boolean detectTls) {
            this.sni = sni;
            this.timerS = timerS;
            this.detectTls = detectTls;
        }

        @Override
        protected void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) {
            if (in.readableBytes() < 5) {
                return;
            }
            ChannelPipeline p = ctx.pipeline();
            if (detectTls && SslHandler.isEncrypted(in, false)) {
                // SniHandler reads the whole ClientHello, picks the context by SNI and replaces
                // itself with the SslHandler it makes, whose handshake timeout it sets to its own
                // (SniHandler.newSslHandler at netty-4.2.18.Final); the decrypted bytes are detected
                // again, as in the example.
                SniHandler h = timerS > 0 ? new SniHandler(sni, TimeUnit.SECONDS.toMillis(timerS)) : new SniHandler(sni);
                p.addAfter(ctx.name(), "sni", h);
                p.addAfter("sni", "detect-decrypted", new Detect(sni, timerS, false));
            } else if (isHttp(in.getUnsignedByte(in.readerIndex()), in.getUnsignedByte(in.readerIndex() + 1))) {
                http(p, ctx.name());
            } else {
                in.clear();
                ctx.close();
                return;
            }
            p.remove(this);
        }

        /** The example's nine methods, and "PR", the h2c preface's start. */
        static boolean isHttp(int m1, int m2) {
            return m1 == 'G' && m2 == 'E' || m1 == 'P' && m2 == 'O' || m1 == 'P' && m2 == 'U' || m1 == 'H' && m2 == 'E'
                    || m1 == 'O' && m2 == 'P' || m1 == 'P' && m2 == 'A' || m1 == 'D' && m2 == 'E' || m1 == 'T' && m2 == 'R'
                    || m1 == 'C' && m2 == 'O' || m1 == 'P' && m2 == 'R';
        }
    }

    /** HTTP/1.1 with the h2c upgrade and h2c by prior knowledge (the Netty example Http2ServerInitializer's
     *  clear-text pipeline). */
    static void http(ChannelPipeline p, String after) {
        HttpServerCodec codec = new HttpServerCodec();
        HttpServerUpgradeHandler upgrade = new HttpServerUpgradeHandler(codec, protocol ->
                AsciiString.contentEquals(Http2CodecUtil.HTTP_UPGRADE_PROTOCOL_NAME, protocol)
                        ? new Http2ServerUpgradeCodec(h2Codec(), new H2Hello()) : null);
        ChannelHandler priorKnowledge = new ChannelInitializer<Channel>() {
            @Override
            protected void initChannel(Channel ch) {
                ch.pipeline().addAfter(ch.pipeline().context(this).name(), "h2", h2Codec());
                ch.pipeline().addAfter("h2", "h2-hello", new H2Hello());
            }
        };
        // The reply handler first: CleartextHttp2ServerUpgradeHandler replaces itself when it is added
        // (with the HTTP codec, the upgrade handler and its prior-knowledge check), so it goes in
        // between, after the reply handler is in place.
        p.addAfter(after, "http1-hello", new Http1Hello());
        p.addAfter(after, "h2c", new CleartextHttp2ServerUpgradeHandler(codec, upgrade, priorKnowledge));
    }

    static Http2FrameCodec h2Codec() {
        return Http2FrameCodecBuilder.forServer().build();
    }

    /** HTTP/1.1: 200 with the 13-byte body to every request; closes after it unless kept alive. */
    static final class Http1Hello extends SimpleChannelInboundHandler<HttpObject> {
        @Override
        protected void channelRead0(ChannelHandlerContext ctx, HttpObject msg) {
            if (!(msg instanceof HttpRequest req)) {
                return;
            }
            boolean keepAlive = HttpUtil.isKeepAlive(req);
            FullHttpResponse res = new DefaultFullHttpResponse(HttpVersion.HTTP_1_1, HttpResponseStatus.OK, Unpooled.wrappedBuffer(BODY));
            res.headers().set(HttpHeaderNames.CONTENT_LENGTH, BODY.length);
            if (!keepAlive) {
                res.headers().set(HttpHeaderNames.CONNECTION, HttpHeaderValues.CLOSE);
                ctx.writeAndFlush(res).addListener(ChannelFutureListener.CLOSE);
            } else {
                ctx.writeAndFlush(res);
            }
        }
    }

    /** h2: on a request's end, HEADERS (:status 200, content-length 13) and DATA with END_STREAM. */
    static final class H2Hello extends ChannelDuplexHandler {
        @Override
        public void channelRead(ChannelHandlerContext ctx, Object msg) {
            try {
                if (msg instanceof Http2HeadersFrame h && h.isEndStream()) {
                    reply(ctx, h.stream());
                } else if (msg instanceof Http2DataFrame d && d.isEndStream()) {
                    reply(ctx, d.stream());
                }
            } finally {
                ReferenceCountUtil.release(msg);
            }
        }

        private static void reply(ChannelHandlerContext ctx, Http2FrameStream stream) {
            DefaultHttp2Headers headers = new DefaultHttp2Headers();
            headers.status("200");
            headers.setInt(HttpHeaderNames.CONTENT_LENGTH, BODY.length);
            ctx.write(new DefaultHttp2HeadersFrame(headers).stream(stream));
            ctx.writeAndFlush(new DefaultHttp2DataFrame(Unpooled.wrappedBuffer(BODY), true).stream(stream));
        }
    }
}
