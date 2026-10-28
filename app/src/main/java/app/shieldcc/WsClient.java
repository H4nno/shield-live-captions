package app.shieldcc;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * Minimal RFC 6455 WebSocket client for a plain LAN text stream.
 * Supports text/binary/continuation frames, ping/pong and close; no TLS, no extensions.
 */
public class WsClient {

    public interface Listener {
        void onOpen();
        void onText(String message);
        void onClosed(Exception cause);
    }

    private final String host;
    private final int port;
    private final String path;
    private final Listener listener;
    private final SecureRandom random = new SecureRandom();

    private Socket socket;
    private volatile boolean userClosed = false;
    private Thread thread;

    public WsClient(String host, int port, String path, Listener listener) {
        this.host = host;
        this.port = port;
        this.path = path;
        this.listener = listener;
    }

    public void connect() {
        userClosed = false;
        thread = new Thread(this::run, "shieldcc-ws");
        thread.setDaemon(true);
        thread.start();
    }

    /** Send a text message (must be called after a successful connect). */
    public boolean sendText(String message) {
        try {
            Socket s = socket;
            if (s == null || s.isClosed()) {
                android.util.Log.w("shieldcc", "sendText: socket not open");
                return false;
            }
            sendFrame(s.getOutputStream(), 0x1, message.getBytes(StandardCharsets.UTF_8));
            android.util.Log.i("shieldcc", "sendText ok: " + message);
            return true;
        } catch (Exception e) {
            android.util.Log.w("shieldcc", "sendText failed: " + e);
            return false;
        }
    }

    public void close() {
        userClosed = true;
        try {
            Socket s = socket;
            if (s != null) s.close();
        } catch (IOException ignored) {
        }
    }

    private void run() {
        try {
            android.util.Log.d("shieldcc", "ws connect " + host + ":" + port);
            socket = new Socket();
            socket.connect(new InetSocketAddress(host, port), 4000);
            socket.setTcpNoDelay(true);
            InputStream in = socket.getInputStream();
            OutputStream out = socket.getOutputStream();
            handshake(in, out);
            android.util.Log.i("shieldcc", "ws open " + host + ":" + port);
            listener.onOpen();
            readLoop(in, out);
            listener.onClosed(null);
        } catch (Exception e) {
            if (!userClosed) {
                android.util.Log.w("shieldcc", "ws closed: " + e);
                listener.onClosed(e);
            }
        }
    }

    private void handshake(InputStream in, OutputStream out) throws IOException {
        byte[] keyBytes = new byte[16];
        random.nextBytes(keyBytes);
        String key = Base64.getEncoder().encodeToString(keyBytes);
        String req = "GET " + path + " HTTP/1.1\r\n"
                + "Host: " + host + ":" + port + "\r\n"
                + "Upgrade: websocket\r\n"
                + "Connection: Upgrade\r\n"
                + "Sec-WebSocket-Key: " + key + "\r\n"
                + "Sec-WebSocket-Version: 13\r\n\r\n";
        out.write(req.getBytes(StandardCharsets.US_ASCII));
        out.flush();

        ByteArrayOutputStream head = new ByteArrayOutputStream();
        int[] tail = {0, 0, 0, 0};
        while (true) {
            int b = in.read();
            if (b == -1) throw new IOException("EOF during handshake");
            head.write(b);
            tail[0] = tail[1];
            tail[1] = tail[2];
            tail[2] = tail[3];
            tail[3] = b;
            if (tail[0] == '\r' && tail[1] == '\n' && tail[2] == '\r' && tail[3] == '\n') break;
        }
        String status = new String(head.toByteArray(), StandardCharsets.US_ASCII);
        if (!status.contains(" 101 ")) {
            throw new IOException("WebSocket handshake rejected: "
                    + status.split("\r\n", 2)[0]);
        }
    }

    private void readLoop(InputStream in, OutputStream out) throws IOException {
        ByteArrayOutputStream message = new ByteArrayOutputStream();
        int messageOpcode = -1;
        while (!userClosed) {
            int b1 = in.read();
            if (b1 == -1) return;
            boolean fin = (b1 & 0x80) != 0;
            int opcode = b1 & 0x0f;

            int b2 = in.read();
            if (b2 == -1) return;
            boolean masked = (b2 & 0x80) != 0;
            long len = b2 & 0x7f;
            if (len == 126) {
                len = readU16(in);
            } else if (len == 127) {
                len = readU64(in);
            }
            if (len > 64L * 1024 * 1024) throw new IOException("Frame too large: " + len);

            byte[] mask = null;
            if (masked) {
                mask = new byte[4];
                readFully(in, mask);
            }
            byte[] payload = new byte[(int) len];
            readFully(in, payload);
            if (masked) {
                for (int i = 0; i < payload.length; i++) {
                    payload[i] ^= mask[i & 3];
                }
            }

            switch (opcode) {
                case 0x0: // continuation
                    message.write(payload);
                    if (fin) {
                        if (messageOpcode == 0x1) {
                            listener.onText(new String(message.toByteArray(), StandardCharsets.UTF_8));
                        }
                        message.reset();
                        messageOpcode = -1;
                    }
                    break;
                case 0x1: // text
                case 0x2: // binary
                    if (messageOpcode == -1) {
                        messageOpcode = opcode;
                        message.reset();
                    }
                    message.write(payload);
                    if (fin) {
                        if (messageOpcode == 0x1) {
                            listener.onText(new String(message.toByteArray(), StandardCharsets.UTF_8));
                        }
                        message.reset();
                        messageOpcode = -1;
                    }
                    break;
                case 0x8: // close
                    sendFrame(out, 0x8, payload);
                    return;
                case 0x9: // ping -> pong
                    sendFrame(out, 0xA, payload);
                    break;
                case 0xA: // pong
                    break;
                default:
                    throw new IOException("Unknown opcode: " + opcode);
            }
        }
    }

    private void sendFrame(OutputStream out, int opcode, byte[] payload) throws IOException {
        ByteArrayOutputStream frame = new ByteArrayOutputStream();
        frame.write(0x80 | opcode);
        int len = payload.length;
        if (len < 126) {
            frame.write(0x80 | len);
        } else if (len <= 0xffff) {
            frame.write(0x80 | 126);
            frame.write((len >>> 8) & 0xff);
            frame.write(len & 0xff);
        } else {
            frame.write(0x80 | 127);
            for (int i = 7; i >= 0; i--) {
                frame.write((int) ((long) len >>> (8 * i)) & 0xff);
            }
        }
        byte[] mask = new byte[4];
        random.nextBytes(mask);
        frame.write(mask);
        for (int i = 0; i < len; i++) {
            frame.write(payload[i] ^ mask[i & 3]);
        }
        out.write(frame.toByteArray());
        out.flush();
    }

    private static long readU16(InputStream in) throws IOException {
        int hi = in.read();
        int lo = in.read();
        if (hi == -1 || lo == -1) throw new IOException("EOF in length");
        return (hi << 8) | lo;
    }

    private static long readU64(InputStream in) throws IOException {
        long v = 0;
        for (int i = 0; i < 8; i++) {
            int b = in.read();
            if (b == -1) throw new IOException("EOF in length");
            v = (v << 8) | b;
        }
        return v;
    }

    private static void readFully(InputStream in, byte[] buf) throws IOException {
        int off = 0;
        while (off < buf.length) {
            int n = in.read(buf, off, buf.length - off);
            if (n == -1) throw new IOException("EOF in payload");
            off += n;
        }
    }
}
