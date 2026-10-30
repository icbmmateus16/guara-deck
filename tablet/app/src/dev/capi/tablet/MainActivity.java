package dev.capi.tablet;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.net.wifi.WifiManager;
import android.os.BatteryManager;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetSocketAddress;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Casca nativa do Guará: tela cheia, tela sempre acesa, brilho controlado pela página
 * e descoberta automática do PC pelo anúncio UDP "CAPI1 <porta>" (porta 47800).
 * A interface em si vem do PC, então dá para atualizá-la sem reinstalar o app.
 */
public class MainActivity extends Activity {
    private static final int DISCOVERY_PORT = 47800;
    private static final String OFFLINE = "file:///android_asset/offline.html";

    /**
     * A única tela viva. Mesmo com singleTask, o Android 4.4 cria uma segunda cópia quando o app é
     * aberto por fora do Home (boot, `am start -n`): ela fica escondida atrás, com o próprio WebView
     * ouvindo os eventos e tocando a mesma fala com atraso. A cópia nova fecha a antiga.
     */
    private static MainActivity current;

    private WebView web;
    private SharedPreferences prefs;
    private final Handler ui = new Handler();
    private String token = "";
    private String host = "";
    private int port = 47801;
    private boolean online = false;
    private volatile boolean running = true;
    private WifiManager.MulticastLock multicast;
    private volatile boolean listening = false;
    private final Object audioLock = new Object();
    private final AtomicInteger playGen = new AtomicInteger(0);
    private AudioTrack activeTrack = null;
    private String lastClipId = "";
    private long lastClipAt = 0;
    private final AtomicInteger ytGen = new AtomicInteger(0);
    private volatile AudioTrack ytTrack = null;
    private volatile boolean ytPaused = false;
    private volatile String activeYtId = "";

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        MainActivity old = current;
        current = this;
        if (old != null && !old.isFinishing()) old.finish();
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);

        prefs = getSharedPreferences("capi", MODE_PRIVATE);
        loadConfig(getIntent());

        web = new WebView(this);
        web.setBackgroundColor(0xFF0E1020);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);  // fontes ficam em cache; o resto o servidor marca no-cache
        web.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        // painel fixo: sem o "esticar" da borda do Android nem barras de rolagem
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, int code, String desc, String url) {
                if (url != null && url.startsWith("http")) showOffline();
            }
        });
        web.addJavascriptInterface(new Bridge(), "CapiNative");
        setContentView(web);

        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        multicast = wifi.createMulticastLock("capi");
        multicast.setReferenceCounted(false);
        multicast.acquire();
        new Thread(new Discovery(), "capi-discovery").start();

        if (host.length() > 0) openPanel(); else showOffline();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (loadConfig(intent)) openPanel();
    }

    /** Config vem do assets/capi.json (gerado no build) e pode ser trocada por extras do Intent. */
    private boolean loadConfig(Intent intent) {
        try {
            InputStream in = getAssets().open("capi.json");
            byte[] buf = new byte[in.available()];
            in.read(buf);
            in.close();
            JSONObject cfg = new JSONObject(new String(buf, "UTF-8"));
            token = cfg.optString("token", "");
            port = cfg.optInt("port", 47801);
            host = cfg.optString("host", "");
        } catch (Exception ignored) {
        }
        host = prefs.getString("host", host);
        port = prefs.getInt("port", port);
        boolean changed = false;
        if (intent != null && intent.hasExtra("host")) {
            host = intent.getStringExtra("host");
            changed = true;
        }
        if (intent != null && intent.hasExtra("token")) {
            token = intent.getStringExtra("token");
            changed = true;
        }
        if (changed) prefs.edit().putString("host", host).apply();
        return changed;
    }

    private String panelUrl() {
        return "http://" + host + ":" + port + "/?t=" + token;
    }

    private void openPanel() {
        online = true;
        stopAudioInternal();
        try { web.evaluateJavascript("if(window.__capiCleanup)window.__capiCleanup()", null); } catch (Exception ignored) {}
        web.clearCache(false);
        web.loadUrl(panelUrl() + "&_=" + System.currentTimeMillis());
    }

    private void showOffline() {
        if (!online && OFFLINE.equals(web.getUrl())) return;
        online = false;
        web.loadUrl(OFFLINE);
        ui.removeCallbacks(retry);
        ui.postDelayed(retry, 6000);
    }

    private final Runnable retry = new Runnable() {
        @Override
        public void run() {
            if (!online && host.length() > 0) openPanel();
        }
    };

    /** O PC anuncia "CAPI1 <porta>" em broadcast; se o IP dele mudar, o painel segue junto. */
    private class Discovery implements Runnable {
        @Override
        public void run() {
            DatagramSocket sock = null;
            byte[] buf = new byte[64];
            while (running) {
                try {
                    if (sock == null) {
                        sock = new DatagramSocket(null);
                        sock.setReuseAddress(true);
                        sock.bind(new InetSocketAddress(DISCOVERY_PORT));
                    }
                    DatagramPacket p = new DatagramPacket(buf, buf.length);
                    sock.receive(p);
                    String[] msg = new String(p.getData(), 0, p.getLength(), "UTF-8").trim().split(" ");
                    if (msg.length != 2 || !"CAPI1".equals(msg[0])) continue;
                    final String newHost = p.getAddress().getHostAddress();
                    final int newPort = Integer.parseInt(msg[1]);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            boolean moved = !newHost.equals(host) || newPort != port;
                            if (moved) {
                                host = newHost;
                                port = newPort;
                                prefs.edit().putString("host", host).putInt("port", port).apply();
                            }
                            if (moved || !online) openPanel();
                        }
                    });
                } catch (Exception e) {
                    if (sock != null) sock.close();
                    sock = null;
                    try { Thread.sleep(3000); } catch (InterruptedException ignored) { }
                }
            }
        }
    }

    /** Métodos que a página chama via window.CapiNative. */
    private class Bridge {
        @JavascriptInterface
        public void setBrightness(final float level) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    WindowManager.LayoutParams lp = getWindow().getAttributes();
                    lp.screenBrightness = Math.max(0.01f, Math.min(1f, level));
                    getWindow().setAttributes(lp);
                }
            });
        }

        @JavascriptInterface
        public String battery() {
            Intent b = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (b == null) return "";
            int level = b.getIntExtra(BatteryManager.EXTRA_LEVEL, 0);
            int scale = b.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
            int plugged = b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
            return (level * 100 / Math.max(1, scale)) + "," + (plugged != 0 ? 1 : 0);
        }

        @JavascriptInterface
        public void lost() {
            ui.post(new Runnable() {
                @Override
                public void run() { online = false; }  // o próximo anúncio do PC recarrega o painel
            });
        }

        @JavascriptInterface
        public String version() { return "5"; }

        @JavascriptInterface
        public void listen() {
            if (listening) return;
            stopAudioInternal();
            listening = true;
            new Thread(new Recorder(), "capi-mic").start();
        }

        @JavascriptInterface
        public void stopListen() { listening = false; }

        @JavascriptInterface
        public void playWav(final String clipId) {
            if (clipId == null || clipId.length() == 0 || current != MainActivity.this) return;
            long now = System.currentTimeMillis();
            synchronized (audioLock) {
                if (clipId.equals(lastClipId) && now - lastClipAt < 8000) return;
                lastClipId = clipId;
                lastClipAt = now;
            }
            stopAudioInternal();
            final int gen = playGen.get();
            new Thread(new WavPlayer(clipId, gen), "capi-tts").start();
        }

        @JavascriptInterface
        public void stopAudio() {
            stopAudioInternal();
        }

        @JavascriptInterface
        public void playYt(final String vid) {
            if (vid == null || vid.length() == 0) return;
            if (vid.equals(activeYtId) && ytTrack != null) {
                ytPaused = false;
                return;
            }
            stopYtInternal();
            activeYtId = vid;
            ytPaused = false;
            final int gen = ytGen.get();
            new Thread(new YtStreamPlayer(vid, gen), "capi-yt").start();
        }

        @JavascriptInterface
        public void pauseYt(final boolean pause) {
            ytPaused = pause;
        }

        @JavascriptInterface
        public void stopYt() {
            stopYtInternal();
        }

        @JavascriptInterface
        public void menu() {
            ui.post(new Runnable() {
                @Override
                public void run() { showMenu(); }
            });
        }

        @JavascriptInterface
        public void reload() {
            ui.post(new Runnable() {
                @Override
                public void run() { openPanel(); }
            });
        }
    }

    private void stopYtInternal() {
        ytGen.incrementAndGet();
        activeYtId = "";
        ytPaused = false;
        AudioTrack t = ytTrack;
        ytTrack = null;
        if (t != null) {
            try { t.pause(); t.flush(); t.stop(); } catch (Exception ignored) {}
            try { t.release(); } catch (Exception ignored) {}
        }
    }

    /** Stream de áudio do YouTube convertido em PCM 24 kHz no PC, tocado direto no tablet. */
    private class YtStreamPlayer implements Runnable {
        private final String vid;
        private final int gen;

        YtStreamPlayer(String vid, int gen) {
            this.vid = vid;
            this.gen = gen;
        }

        @Override
        public void run() {
            HttpURLConnection c = null;
            AudioTrack track = null;
            boolean naturalEnd = false;
            try {
                int rate = 24000;
                int minBuf = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
                track = new AudioTrack(AudioManager.STREAM_MUSIC, rate, AudioFormat.CHANNEL_OUT_MONO,
                        AudioFormat.ENCODING_PCM_16BIT, Math.max(minBuf * 4, 24576), AudioTrack.MODE_STREAM);
                if (ytGen.get() != gen) { track.release(); return; }
                ytTrack = track;

                String url = "http://" + host + ":" + port + "/api/yt/pcm/" + vid + ".raw?t=" + token;
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(15000);
                c.setReadTimeout(20000);
                if (c.getResponseCode() != 200) return;

                InputStream in = c.getInputStream();
                byte[] buf = new byte[4096];
                boolean started = false;
                boolean wasDucked = false;
                int n;
                while (ytGen.get() == gen && running) {
                    if (ytPaused || listening) {
                        if (started) { try { track.pause(); } catch (Exception ignored) {} started = false; }
                        try { Thread.sleep(80); } catch (InterruptedException ignored) { break; }
                        continue;
                    }
                    n = in.read(buf);
                    if (n < 0) { naturalEnd = true; break; }
                    if (n == 0) continue;
                    if (!started) { track.play(); started = true; }
                    boolean duck = (activeTrack != null);
                    if (duck != wasDucked) {
                        float v = duck ? 0.16f : 1.0f;
                        try { track.setStereoVolume(v, v); } catch (Exception ignored) {}
                        wasDucked = duck;
                    }
                    track.write(buf, 0, n - (n & 1));
                }
                in.close();
            } catch (Exception ignored) {
            } finally {
                if (c != null) c.disconnect();
                if (ytTrack == track) ytTrack = null;
                if (track != null) {
                    try { track.stop(); } catch (Exception ignored) {}
                    try { track.release(); } catch (Exception ignored) {}
                }
                if (naturalEnd && ytGen.get() == gen && running) {
                    activeYtId = "";
                    js("window.CapiVoice&&CapiVoice.ytEnded('" + vid + "')");
                }
            }
        }
    }

    private void stopAudioInternal() {
        playGen.incrementAndGet();
        synchronized (audioLock) {
            if (activeTrack != null) {
                try { activeTrack.pause(); activeTrack.flush(); activeTrack.stop(); } catch (Exception ignored) {}
                try { activeTrack.release(); } catch (Exception ignored) {}
                activeTrack = null;
            }
        }
    }

    /**
     * Toca a fala do Guará direto em um único AudioTrack PCM nativo (evita o FFPlayer bugado
     * do Android 4.4 e impede fisicamente duas vozes sobrepostas ao mesmo tempo).
     */
    private class WavPlayer implements Runnable {
        private final String clipId;
        private final int gen;

        WavPlayer(String clipId, int gen) {
            this.clipId = clipId;
            this.gen = gen;
        }

        @Override
        public void run() {
            byte[] wav = null;
            HttpURLConnection c = null;
            try {
                String url = "http://" + host + ":" + port + "/api/say/" + clipId + ".wav?t=" + token;
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(4000);
                c.setReadTimeout(10000);
                if (c.getResponseCode() != 200) return;
                InputStream in = c.getInputStream();
                ByteArrayOutputStream out = new ByteArrayOutputStream(96 * 1024);
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    if (playGen.get() != gen) { in.close(); return; }
                    out.write(buf, 0, n);
                }
                in.close();
                wav = out.toByteArray();
            } catch (Exception e) {
                return;
            } finally {
                if (c != null) c.disconnect();
            }
            if (wav == null || wav.length <= 44 || playGen.get() != gen) return;

            int rate = 24000;
            int channels = 1;
            int dataOff = 44;
            int dataLen = wav.length - 44;
            int pos = 12;
            while (pos + 8 <= wav.length) {
                int c0 = wav[pos] & 0xff, c1 = wav[pos + 1] & 0xff, c2 = wav[pos + 2] & 0xff, c3 = wav[pos + 3] & 0xff;
                int sz = (wav[pos + 4] & 0xff) | ((wav[pos + 5] & 0xff) << 8) | ((wav[pos + 6] & 0xff) << 16) | ((wav[pos + 7] & 0xff) << 24);
                if (sz < 0) break;
                if (c0 == 'f' && c1 == 'm' && c2 == 't' && c3 == ' ' && pos + 16 <= wav.length) {
                    channels = (wav[pos + 10] & 0xff) | ((wav[pos + 11] & 0xff) << 8);
                    rate = (wav[pos + 12] & 0xff) | ((wav[pos + 13] & 0xff) << 8) | ((wav[pos + 14] & 0xff) << 16) | ((wav[pos + 15] & 0xff) << 24);
                } else if (c0 == 'd' && c1 == 'a' && c2 == 't' && c3 == 'a') {
                    dataOff = pos + 8;
                    dataLen = Math.min(sz, wav.length - dataOff);
                    break;
                }
                pos += 8 + sz + (sz & 1);
            }
            if (rate < 8000 || rate > 48000) rate = 24000;

            int chCfg = channels == 2 ? AudioFormat.CHANNEL_OUT_STEREO : AudioFormat.CHANNEL_OUT_MONO;
            int minBuf = AudioTrack.getMinBufferSize(rate, chCfg, AudioFormat.ENCODING_PCM_16BIT);
            int bufSize = Math.max(minBuf * 2, 8192);
            AudioTrack track = null;
            try {
                track = new AudioTrack(AudioManager.STREAM_MUSIC, rate, chCfg, AudioFormat.ENCODING_PCM_16BIT, bufSize, AudioTrack.MODE_STREAM);
                synchronized (audioLock) {
                    if (playGen.get() != gen) { track.release(); return; }
                    activeTrack = track;
                }
                track.play();
                js("window.CapiVoice&&CapiVoice.playState('playing','" + clipId + "')");
                int end = dataOff + dataLen;
                int cur = dataOff;
                while (cur < end && playGen.get() == gen && running) {
                    int chunk = Math.min(4096, end - cur);
                    int w = track.write(wav, cur, chunk);
                    if (w <= 0) break;
                    cur += w;
                }
                long drainMs = (bufSize * 1000L) / Math.max(1, rate * channels * 2) + 60;
                long drainEnd = System.currentTimeMillis() + drainMs;
                while (playGen.get() == gen && running && System.currentTimeMillis() < drainEnd) {
                    try { Thread.sleep(25); } catch (InterruptedException ignored) { break; }
                }
            } catch (Exception ignored) {
            } finally {
                synchronized (audioLock) {
                    if (activeTrack == track) activeTrack = null;
                }
                if (track != null) {
                    try { track.stop(); } catch (Exception ignored) {}
                    try { track.release(); } catch (Exception ignored) {}
                }
                if (playGen.get() == gen) {
                    js("window.CapiVoice&&CapiVoice.playState('ended','" + clipId + "')");
                }
            }
        }
    }

    private void js(final String code) {
        ui.post(new Runnable() {
            @Override
            public void run() { web.evaluateJavascript(code, null); }
        });
    }

    /**
     * Grava 16 kHz mono e para sozinho depois de 2 s de silêncio. Dois limiares calibrados pelo
     * ruído da sala nos primeiros 400 ms: um mais alto para perceber que você começou a falar e
     * outro bem mais baixo para entender que continua falando (fim de frase, pausa para pensar).
     */
    private class Recorder implements Runnable {
        private static final int RATE = 16000;

        @Override
        public void run() {
            int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            AudioRecord rec = null;
            ByteArrayOutputStream pcm = new ByteArrayOutputStream();
            boolean spoke = false;
            try {
                rec = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE,
                        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(min, RATE) * 2);
                rec.startRecording();
                js("CapiVoice.state('ouvindo')");
                short[] buf = new short[RATE / 10];          // blocos de 100 ms
                byte[] bytes = new byte[buf.length * 2];
                long start = System.currentTimeMillis(), lastVoice = start;
                double noise = 0, startTh = 800, keepTh = 450;
                int blocks = 0;
                while (listening) {
                    int n = rec.read(buf, 0, buf.length);
                    if (n <= 0) continue;
                    double sum = 0;
                    for (int i = 0; i < n; i++) {
                        sum += buf[i] * (double) buf[i];
                        bytes[i * 2] = (byte) (buf[i] & 0xff);
                        bytes[i * 2 + 1] = (byte) ((buf[i] >> 8) & 0xff);
                    }
                    pcm.write(bytes, 0, n * 2);
                    double rms = Math.sqrt(sum / n);
                    long now = System.currentTimeMillis();
                    if (++blocks <= 4) {
                        noise += rms / 4;
                        if (blocks == 4) {
                            startTh = Math.max(450, noise * 2.2);
                            keepTh = Math.max(260, noise * 1.4);
                        }
                    } else {
                        if (rms > startTh) spoke = true;
                        if (spoke && rms > keepTh) lastVoice = now;   // ainda falando, mesmo baixinho
                    }
                    js("CapiVoice.level(" + Math.min(9, (int) (rms / startTh * 4)) + ")");
                    if (spoke && now - lastVoice > 2000) break;   // 2 s de silêncio: terminou
                    if (!spoke && now - start > 8000) break;      // ninguém falou
                    if (now - start > 30000) break;               // limite de segurança
                }
            } catch (Exception e) {
                js("CapiVoice.state('erro')");
                listening = false;
                return;
            } finally {
                if (rec != null) {
                    try { rec.stop(); } catch (Exception ignored) { }
                    rec.release();
                }
            }
            listening = false;
            if (!spoke) {
                js("CapiVoice.state('nada')");
                return;
            }
            js("CapiVoice.state('enviando')");
            try {
                byte[] wav = wav(pcm.toByteArray());
                HttpURLConnection c = (HttpURLConnection) new URL(panelUrl().replace("/?t=", "/api/voice?t=")).openConnection();
                c.setDoOutput(true);
                c.setConnectTimeout(5000);
                c.setReadTimeout(15000);
                c.setRequestMethod("POST");
                c.setRequestProperty("Content-Type", "audio/wav");
                c.setFixedLengthStreamingMode(wav.length);
                OutputStream out = c.getOutputStream();
                out.write(wav);
                out.close();
                int code = c.getResponseCode();
                c.disconnect();
                js("CapiVoice.state('" + (code == 200 ? "enviado" : "erro") + "')");
            } catch (Exception e) {
                js("CapiVoice.state('erro')");
            }
        }

        private byte[] wav(byte[] pcm) {
            ByteArrayOutputStream out = new ByteArrayOutputStream(pcm.length + 44);
            int byteRate = RATE * 2;
            writeStr(out, "RIFF"); writeInt(out, 36 + pcm.length); writeStr(out, "WAVE");
            writeStr(out, "fmt "); writeInt(out, 16); writeShort(out, 1); writeShort(out, 1);
            writeInt(out, RATE); writeInt(out, byteRate); writeShort(out, 2); writeShort(out, 16);
            writeStr(out, "data"); writeInt(out, pcm.length);
            out.write(pcm, 0, pcm.length);
            return out.toByteArray();
        }

        private void writeStr(ByteArrayOutputStream o, String s) {
            for (int i = 0; i < s.length(); i++) o.write(s.charAt(i));
        }

        private void writeInt(ByteArrayOutputStream o, int v) {
            o.write(v & 0xff); o.write((v >> 8) & 0xff); o.write((v >> 16) & 0xff); o.write((v >> 24) & 0xff);
        }

        private void writeShort(ByteArrayOutputStream o, int v) {
            o.write(v & 0xff); o.write((v >> 8) & 0xff);
        }
    }

    private void showMenu() {
        final String[] items = {"Recarregar o painel", "Configurar Wi-Fi", "Configurações do Android", "Sair do Guará"};
        new AlertDialog.Builder(this, AlertDialog.THEME_HOLO_DARK)
                .setTitle("Guará · " + host)
                .setItems(items, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        if (which == 0) openPanel();
                        else if (which == 1) startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS));
                        else if (which == 2) startActivity(new Intent(Settings.ACTION_SETTINGS));
                        else finish();
                    }
                })
                .show();
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }

    @Override
    protected void onResume() {
        super.onResume();
        immersive();
        web.onResume();
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) immersive();
    }

    @Override
    public void onBackPressed() {
        // painel dedicado: o botão Voltar não fecha o Guará (segure o relógio 3 s para o menu)
    }

    @Override
    protected void onDestroy() {
        if (current == this) current = null;
        running = false;
        stopAudioInternal();
        stopYtInternal();
        if (multicast != null && multicast.isHeld()) multicast.release();
        web.destroy();
        super.onDestroy();
    }
}
