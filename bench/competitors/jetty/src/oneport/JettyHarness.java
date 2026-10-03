// The Jetty harness of hypotheses.md, Appendix B (CP7 of design/proposal.md): one ServerConnector
// whose first ConnectionFactory is a DetectorConnectionFactory over SslConnectionFactory and
// ProxyConnectionFactory, then HTTP/1.1 with the h2c upgrade (HTTP2CServerConnectionFactory), as the
// Jetty 12.1 programming guide's I/O architecture section describes ("Choosing ConnectionFactory via
// Bytes Detection"; design/competitor-survey.md, 2.16). Every reply is the server's: 200,
// Content-Length 13, "Hello, World!" (hypotheses.md, section 2.1).
//
// Bytes that neither detector recognises go to the next factory in the connector's list, HTTP/1.1,
// which upgrades to h2c on the preface or on an Upgrade header. Both detected protocols wrap HTTP/1.1
// too: TLS (SslConnectionFactory's next protocol) and the PROXY header (ProxyConnectionFactory's).
// So PROXY is optional on this listener by Jetty's design (survey 2.16).
//
// Arguments (bench/competitors/jetty/cases.args and b3.args, rendered by competitors.py):
//   --port N          the listener
//   --proxy-port N    a second listener with the same factories, for the PROXY cases (0: none)
//   --idle-ms N       the connector's idle timeout (0: Jetty's default, 30000 ms)
//   --accept-queue N  acceptQueueSize (0: the platform's default)
//   --cert F --key F  the test certificate and key (tests/fixtures/tls), PEM, the key PKCS#8
// Prints "jetty: listening <port>" per listener. Stops on SIGTERM (Server's stop at shutdown).
package oneport;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;
import java.io.ByteArrayInputStream;

import org.eclipse.jetty.http.HttpHeader;
import org.eclipse.jetty.http2.server.HTTP2CServerConnectionFactory;
import org.eclipse.jetty.server.DetectorConnectionFactory;
import org.eclipse.jetty.server.Handler;
import org.eclipse.jetty.server.HttpConfiguration;
import org.eclipse.jetty.server.HttpConnectionFactory;
import org.eclipse.jetty.server.ProxyConnectionFactory;
import org.eclipse.jetty.server.Request;
import org.eclipse.jetty.server.Response;
import org.eclipse.jetty.server.Server;
import org.eclipse.jetty.server.ServerConnector;
import org.eclipse.jetty.server.SslConnectionFactory;
import org.eclipse.jetty.util.Callback;
import org.eclipse.jetty.util.ssl.SslContextFactory;

public final class JettyHarness {
    static final byte[] BODY = "Hello, World!".getBytes(StandardCharsets.US_ASCII);
    static final char[] STORE_PASSWORD = "test-material".toCharArray();  // an in-memory store of the test key

    record Options(int port, int proxyPort, long idleMs, int acceptQueue, Path cert, Path key) {
        static Options parse(String[] args) {
            int port = 0, proxyPort = 0, acceptQueue = 0;
            long idleMs = 0;
            Path cert = null, key = null;
            for (int i = 0; i + 1 < args.length; i += 2) {
                switch (args[i]) {
                    case "--port" -> port = Integer.parseInt(args[i + 1]);
                    case "--proxy-port" -> proxyPort = Integer.parseInt(args[i + 1]);
                    case "--idle-ms" -> idleMs = Long.parseLong(args[i + 1]);
                    case "--accept-queue" -> acceptQueue = Integer.parseInt(args[i + 1]);
                    case "--cert" -> cert = Path.of(args[i + 1]);
                    case "--key" -> key = Path.of(args[i + 1]);
                    default -> throw new IllegalArgumentException("unknown argument " + args[i]);
                }
            }
            if (args.length % 2 != 0 || port <= 0 || cert == null || key == null) {
                throw new IllegalArgumentException("usage: --port N [--proxy-port N] [--idle-ms N] [--accept-queue N] --cert F --key F");
            }
            return new Options(port, proxyPort, idleMs, acceptQueue, cert, key);
        }
    }

    public static void main(String[] args) throws Exception {
        Options o = Options.parse(args);
        Server server = new Server();
        server.setStopAtShutdown(true);
        addConnector(server, o, o.port());
        if (o.proxyPort() > 0) {
            addConnector(server, o, o.proxyPort());
        }
        server.setHandler(new Hello());
        server.start();
        System.out.println("jetty: listening " + o.port());
        if (o.proxyPort() > 0) {
            System.out.println("jetty: listening " + o.proxyPort() + " (the same factories, for the PROXY cases)");
        }
        System.out.flush();
        server.join();
    }

    static void addConnector(Server server, Options o, int port) throws Exception {
        HttpConfiguration httpConfig = new HttpConfiguration();
        HttpConnectionFactory http11 = new HttpConnectionFactory(httpConfig);
        HTTP2CServerConnectionFactory h2c = new HTTP2CServerConnectionFactory(httpConfig);
        SslConnectionFactory tls = new SslConnectionFactory(sslContextFactory(o), http11.getProtocol());
        ProxyConnectionFactory proxy = new ProxyConnectionFactory(http11.getProtocol());
        DetectorConnectionFactory detector = new DetectorConnectionFactory(tls, proxy);
        ServerConnector connector = new ServerConnector(server, detector, http11, h2c);
        connector.setHost("127.0.0.1");
        connector.setPort(port);
        if (o.idleMs() > 0) {
            connector.setIdleTimeout(o.idleMs());
        }
        if (o.acceptQueue() > 0) {
            connector.setAcceptQueueSize(o.acceptQueue());
        }
        server.addConnector(connector);
    }

    /** TLS: the test certificate; TLS 1.3 and TLS_AES_128_GCM_SHA256 as the server's (section 2.1);
     *  the group and signature scheme by the JSSE properties of bench/competitors/jvm.args. */
    static SslContextFactory.Server sslContextFactory(Options o) throws Exception {
        CertificateFactory cf = CertificateFactory.getInstance("X.509");
        Certificate cert = cf.generateCertificate(new ByteArrayInputStream(pemBlock(o.cert(), "CERTIFICATE")));
        PrivateKey key = KeyFactory.getInstance("EC").generatePrivate(new PKCS8EncodedKeySpec(pemBlock(o.key(), "PRIVATE KEY")));
        KeyStore ks = KeyStore.getInstance("PKCS12");
        ks.load(null, null);
        ks.setKeyEntry("oneport.test", key, STORE_PASSWORD, new Certificate[] {cert});
        SslContextFactory.Server f = new SslContextFactory.Server();
        f.setKeyStore(ks);
        f.setKeyStorePassword(new String(STORE_PASSWORD));
        f.setIncludeProtocols("TLSv1.3");
        f.setIncludeCipherSuites("TLS_AES_128_GCM_SHA256");
        return f;
    }

    /** The DER bytes of the first PEM block of a type; the fixtures carry text before it. */
    static byte[] pemBlock(Path file, String type) throws IOException {
        String text = Files.readString(file, StandardCharsets.US_ASCII);
        String begin = "-----BEGIN " + type + "-----", end = "-----END " + type + "-----";
        int b = text.indexOf(begin), e = text.indexOf(end);
        if (b < 0 || e < b) {
            throw new IOException("no " + type + " block in " + file);
        }
        return Base64.getMimeDecoder().decode(text.substring(b + begin.length(), e));
    }

    /** 200 with the 13-byte body to every request. */
    static final class Hello extends Handler.Abstract.NonBlocking {
        @Override
        public boolean handle(Request request, Response response, Callback callback) {
            response.setStatus(200);
            response.getHeaders().put(HttpHeader.CONTENT_LENGTH, BODY.length);
            response.write(true, ByteBuffer.wrap(BODY), callback);
            return true;
        }
    }
}
