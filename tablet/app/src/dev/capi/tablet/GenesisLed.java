package dev.capi.tablet;

import java.io.FileOutputStream;
import java.io.IOException;

/**
 * Luz da logo Genesis, atrás do tablet. O LED só acende ou apaga (testado em 01/11: brilho 1 a 254 acende
 * igual a 255), então o meio-termo vem do gatilho "timer" do kernel piscando rápido demais para o olho (PWM).
 * Com HZ=300 um tique dura 3,3 ms: os níveis abaixo ficam entre 60 e 150 Hz e não tremem.
 *
 * O root entra uma vez só, ao abrir o app: liga o gatilho timer e dá ao app os arquivos delay_on/delay_off.
 * Depois esta thread desenha as animações a ~33 quadros/s e só escreve quando o nível muda (o laço antigo
 * de shell como root ocupava ~23% de um núcleo). Nada vindo da página vira comando de shell.
 */
final class GenesisLed implements Runnable {
    private static final String LED = "/sys/class/leds/genesis-led";

    // {delay_on, delay_off} em ms; o kernel arredonda para cima em tiques de 3,3 ms (3→1, 6→2, 10→3, 13→4).
    // Não há "apagado": sem root, sair do timer não teria volta. O piso de 20% já é bem mais fraco.
    private static final int[][] LADDER = {
            {3, 13}, {3, 10}, {3, 6}, {6, 10}, {3, 3}, {10, 6}, {6, 3}, {10, 3}, {13, 3}, {3, 0},
    };
    private static final float[] DUTY = {0.20f, 0.25f, 0.33f, 0.40f, 0.50f, 0.60f, 0.67f, 0.75f, 0.80f, 1f};
    private static final float[] SEEN = new float[DUTY.length];   // o olho vê o brilho ~ duty^0,45
    static {
        for (int i = 0; i < DUTY.length; i++) SEEN[i] = (float) Math.pow(DUTY[i], 0.45);
    }
    private static final float LO = SEEN[0], HI = 1f;

    private final Thread worker;
    private final int uid;
    private volatile boolean running = true;
    private String mode = "idle";
    private int level;
    private long updated;
    private String event;
    private long eventAt;

    GenesisLed(int uid) {
        this.uid = uid;
        worker = new Thread(this, "guara-logo");
        worker.setDaemon(true);
        worker.start();
    }

    /** Estado contínuo vindo da página: idle, listening, thinking, speaking, attention ou sleep; level 0-9. */
    synchronized void update(String next, int volume) {
        if (!("idle".equals(next) || "listening".equals(next) || "thinking".equals(next)
                || "speaking".equals(next) || "attention".equals(next) || "sleep".equals(next))) return;
        mode = next;
        level = Math.max(0, Math.min(9, volume));
        updated = System.nanoTime();
    }

    /** Efeito curto por cima do estado: wake, notify, done ou error. */
    synchronized void event(String name) {
        if (!("wake".equals(name) || "notify".equals(name) || "done".equals(name) || "error".equals(name))) return;
        event = name;
        eventAt = System.nanoTime();
    }

    void close() {
        running = false;
        worker.interrupt();
    }

    private static void write(String name, int value) throws IOException {
        FileOutputStream out = new FileOutputStream(LED + "/" + name);
        try {
            out.write(Integer.toString(value).getBytes("US-ASCII"));
        } finally {
            out.close();
        }
    }

    private void apply(int index) throws IOException {
        write("delay_on", LADDER[index][0]);      // nesta ordem: ir para "acesa" (delay_off 0) por último
        write("delay_off", LADDER[index][1]);
    }

    /** Uma vez por abertura do app: gatilho timer aceso e os dois arquivos de ritmo com dono = este app. */
    private boolean setup() throws Exception {
        String files = LED + "/delay_on " + LED + "/delay_off";
        String cmd = "L=" + LED + "; [ -w $L/trigger ] || exit 1; echo 1 > $L/enable; "
                + "echo timer > $L/trigger; echo 3 > $L/delay_on; echo 0 > $L/delay_off; "
                + "/bin/busybox chown " + uid + ":" + uid + " " + files + " || chmod 666 " + files;
        Process su = new ProcessBuilder("su", "-c", cmd).redirectErrorStream(true).start();
        su.getOutputStream().close();
        for (int i = 0; i < 100; i++) {           // o Superuser antigo pode demorar a responder: até 10 s
            try {
                su.exitValue();
                break;
            } catch (IllegalThreadStateException stillRunning) {
                Thread.sleep(100);
            }
        }
        su.destroy();
        return new java.io.File(LED + "/delay_on").canWrite() && new java.io.File(LED + "/delay_off").canWrite();
    }

    private static float wave(double t, double period) {         // 0..1..0 suave
        return (float) (0.5 - 0.5 * Math.cos(2 * Math.PI * t / period));
    }

    private static float between(float a, float b, float x) {
        return a + (b - a) * Math.max(0f, Math.min(1f, x));
    }

    private float target(String m, int lvl, double t) {
        if ("listening".equals(m)) {                              // respira e acende mais com a sua voz
            return Math.max(between(0.62f, 0.9f, wave(t, 1.6)), between(LO, HI, lvl / 6f));
        }
        if ("thinking".equals(m)) return between(LO, HI, wave(t, 0.9));
        if ("speaking".equals(m)) return between(LO, HI, (float) Math.pow(lvl / 9.0, 0.8));
        if ("attention".equals(m)) {                              // batida de coração: tum-tum... pausa
            double p = t % 1.4;
            float beat = p < 0.36 ? (float) Math.abs(Math.sin(Math.PI * p / 0.18)) : 0f;
            return between(0.55f, HI, beat);
        }
        if ("sleep".equals(m)) return between(LO, 0.72f, wave(t, 6.0));
        return HI;                                                // parado: acesa como a original
    }

    /** Efeitos curtos medidos em mergulhos a partir do aceso; null quando acabou. */
    private static Float eventCurve(String name, double e) {
        double dur, period;
        if ("wake".equals(name)) { dur = 0.6; period = 0.3; }        // duas piscadinhas: "te ouvi"
        else if ("notify".equals(name)) { dur = 1.8; period = 0.6; } // três ondas suaves
        else if ("done".equals(name)) { dur = 1.4; period = 1.4; }   // uma onda lenta
        else { dur = 0.9; period = 0.3; }                            // erro: três tremidas
        if (e >= dur) return null;
        float dip = (float) Math.pow(Math.sin(Math.PI * e / period), 2);
        return between(HI, LO, dip);
    }

    private static int nearest(float seen) {
        int best = 0;
        for (int i = 1; i < SEEN.length; i++) {
            if (Math.abs(SEEN[i] - seen) < Math.abs(SEEN[best] - seen)) best = i;
        }
        return best;
    }

    @Override public void run() {
        if (!new java.io.File(LED).exists()) return;              // outro aparelho: o painel segue sem a luz
        int shown = -1;
        try {
            if (!setup()) {
                android.util.Log.w("GuaraLogo", "sem permissão para controlar a luz da logo");
                return;
            }
            long start = System.nanoTime();
            float cur = HI;
            while (running) {
                long now = System.nanoTime();
                String m, ev;
                int lvl;
                long evAt;
                synchronized (this) {
                    // página parou, desconectou ou travou: volta a acesa em até quatro segundos
                    m = now - updated > 4000000000L ? "idle" : mode;
                    lvl = level;
                    ev = event;
                    evAt = eventAt;
                }
                double t = (now - start) / 1e9;
                Float fx = ev == null ? null : eventCurve(ev, (now - evAt) / 1e9);
                if (fx == null && ev != null) {
                    synchronized (this) {
                        if (eventAt == evAt) event = null;
                    }
                }
                float goal = fx != null ? fx : target(m, lvl, t);
                // nada de corte seco: sobe rápido e desce devagar (fala), as outras transições deslizam
                float k = "speaking".equals(m) && fx == null ? (goal > cur ? 0.6f : 0.25f) : 0.35f;
                cur += (goal - cur) * k;
                int index = nearest(cur);
                if (index != shown) {
                    apply(index);
                    shown = index;
                }
                Thread.sleep(30);
            }
        } catch (InterruptedException closing) {
            // app fechando
        } catch (Exception error) {
            if (running) android.util.Log.w("GuaraLogo", "luz da logo indisponível", error);
        } finally {
            try {
                if (shown >= 0) apply(LADDER.length - 1);         // fica acesa, como a luz original
            } catch (Exception ignored) { }
        }
    }
}
