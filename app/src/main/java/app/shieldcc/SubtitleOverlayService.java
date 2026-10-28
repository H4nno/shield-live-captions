package app.shieldcc;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.util.DisplayMetrics;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.Iterator;

public class SubtitleOverlayService extends Service {

    public static final String ACTION_START = "app.shieldcc.action.START";
    public static final String ACTION_STOP = "app.shieldcc.action.STOP";
    public static final String ACTION_TOGGLE = "app.shieldcc.action.TOGGLE";
    public static final String ACTION_SIZE_UP = "app.shieldcc.action.SIZE_UP";
    public static final String ACTION_SIZE_DOWN = "app.shieldcc.action.SIZE_DOWN";
    public static final String ACTION_CYCLE_POSITION = "app.shieldcc.action.CYCLE_POSITION";
    public static final String ACTION_CYCLE_MODE = "app.shieldcc.action.CYCLE_MODE";
    public static final String ACTION_LANG_CYCLE = "app.shieldcc.action.LANG_CYCLE";
    public static final String EXTRA_DEMO = "demo";

    private static final long LINE_TTL_MS = 2500;
    private static final long MIN_DISPLAY_MS = 1200;
    private static final int MAX_LINES = 2;
    private static final long RECONNECT_MAX_MS = 30000;
    private static final String TAG = "shieldcc";

    static volatile boolean running = false;

    private WindowManager windowManager;
    private LinearLayout container;
    private LinearLayout finalsBox;
    private TextView partialView;
    private TextView draftView;
    private View overlay;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Handler demoHandler = new Handler(Looper.getMainLooper());
    private WsClient ws;
    private boolean demo;
    private boolean overlayAdded;
    private boolean demoRunning;
    private String pendingCmd;
    private long reconnectDelayMs = 1000;
    private int demoIdx;
    private final ArrayDeque<Line> lines = new ArrayDeque<>();

    private static class Line {
        final String text;
        final long at;

        Line(String text, long at) {
            this.text = text;
            this.at = at;
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        windowManager = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
        buildViews();
        startInForeground();
        main.post(this::pruneLoop);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null && intent.getAction() != null ? intent.getAction() : ACTION_START;
        if (ACTION_LANG_CYCLE.equals(action)) {
            // one remote gesture: off -> English -> Portuguese -> off
            String state = Prefs.captionCycle(this);
            String next = "en".equals(state) ? "pt" : ("pt".equals(state) ? "off" : "en");
            Prefs.setCaptionCycle(this, next);
            Log.i(TAG, "lang cycle: " + state + " -> " + next);
            if ("off".equals(next)) {
                stopSelf();
                return START_NOT_STICKY;
            }
            pendingCmd = "{\"cmd\":\"caption_lang\",\"value\":\""
                    + ("pt".equals(next) ? "Portuguese" : "English") + "\"}";
            final String cmd = pendingCmd;
            final WsClient w = ws;
            if (w != null) {
                // network I/O is not allowed on the main thread
                Thread sender = new Thread(() -> {
                    if (w.sendText(cmd)) {
                        main.post(() -> {
                            if (cmd.equals(pendingCmd)) pendingCmd = null;
                        });
                    }
                }, "cmd-send");
                sender.setDaemon(true);
                sender.start();
            }
            boolean justStarted = !overlayAdded;
            if (!overlayAdded && Settings.canDrawOverlays(this)) {
                windowManager.addView(overlay, overlayParams());
                overlayAdded = true;
            }
            if (justStarted) {
                stopDemo();
                startSocket();
            }
            onFinal("▶ " + ("pt".equals(next) ? "Portugiesisch" : "English"), "");
            return START_STICKY;
        }
        switch (action) {
            case ACTION_STOP:
                stopSelf();
                return START_NOT_STICKY;
            case ACTION_SIZE_UP:
                Prefs.setFontSp(this, Prefs.fontSp(this) + 3);
                applyFontSize();
                return START_STICKY;
            case ACTION_SIZE_DOWN:
                Prefs.setFontSp(this, Prefs.fontSp(this) - 3);
                applyFontSize();
                return START_STICKY;
            case ACTION_CYCLE_POSITION:
                Prefs.setPosition(this, (Prefs.position(this) + 1) % 3);
                if (overlayAdded) {
                    windowManager.updateViewLayout(overlay, overlayParams());
                }
                return START_STICKY;
            case ACTION_CYCLE_MODE: {
                String cur = Prefs.displayMode(this);
                String next = "both".equals(cur) ? "en" : ("en".equals(cur) ? "de" : "both");
                Prefs.setDisplayMode(this, next);
                synchronized (lines) {
                    lines.clear();
                    renderFinalsLocked();
                    partialView.setVisibility(View.GONE);
                    partialView.setText("");
                }
                updateVisibility();
                Log.i(TAG, "display mode -> " + next);
                return START_STICKY;
            }
            case ACTION_TOGGLE:
                if (overlayAdded) {
                    stopSelf();
                    return START_NOT_STICKY;
                }
                break;
            default:
                break;
        }

        demo = intent != null && intent.getBooleanExtra(EXTRA_DEMO, false);
        Log.i(TAG, "onStartCommand action=" + action + " demo=" + demo + " canDraw=" + Settings.canDrawOverlays(this));
        if (!Settings.canDrawOverlays(this)) {
            Log.e(TAG, "overlay permission missing, stopping");
            stopSelf();
            return START_NOT_STICKY;
        }
        if (!overlayAdded) {
            windowManager.addView(overlay, overlayParams());
            overlayAdded = true;
        }
        if (demo) {
            stopSocket();
            startDemo();
        } else {
            stopDemo();
            startSocket();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        stopSocket();
        stopDemo();
        if (overlayAdded) {
            try {
                windowManager.removeView(overlay);
            } catch (Exception ignored) {
            }
            overlayAdded = false;
        }
        super.onDestroy();
    }

    private void startInForeground() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        NotificationChannel channel = new NotificationChannel(
                "captions", getString(R.string.app_name), NotificationManager.IMPORTANCE_MIN);
        nm.createNotificationChannel(channel);
        Notification n = new Notification.Builder(this, "captions")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle(getString(R.string.app_name))
                .setOngoing(true)
                .build();
        startForeground(1, n);
    }

    private WindowManager.LayoutParams overlayParams() {
        DisplayMetrics dm = new DisplayMetrics();
        windowManager.getDefaultDisplay().getRealMetrics(dm);
        int sideMargin = (int) (dm.widthPixels * 0.04f);
        int y;
        switch (Prefs.position(this)) {
            case 1: y = (int) (dm.heightPixels * 0.28f); break;   // lower third
            case 2: y = (int) (dm.heightPixels * 0.88f); break;   // top
            default: y = (int) (dm.heightPixels * 0.055f); break; // bottom
        }
        int width = (int) (dm.widthPixels * Math.min(Math.max(Prefs.widthPct(this), 30), 100) / 100.0);
        WindowManager.LayoutParams p = new WindowManager.LayoutParams(
                width,
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        p.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
        p.y = y;
        return p;
    }

    private void buildViews() {
        container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setGravity(Gravity.CENTER_HORIZONTAL);
        int padH = dp(16);
        int padV = dp(10);
        container.setPadding(padH, padV, padH, padV);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(0xB2000000);
        bg.setCornerRadius(dp(10));
        container.setBackground(bg);

        finalsBox = new LinearLayout(this);
        finalsBox.setOrientation(LinearLayout.VERTICAL);
        finalsBox.setGravity(Gravity.CENTER_HORIZONTAL);

        draftView = makeTextView();
        draftView.setAlpha(0.82f);
        draftView.setVisibility(View.GONE);

        partialView = makeTextView();
        partialView.setTypeface(partialView.getTypeface(), Typeface.ITALIC);
        partialView.setAlpha(0.72f);
        partialView.setVisibility(View.GONE);

        container.addView(finalsBox);
        container.addView(draftView);
        container.addView(partialView);
        overlay = container;
        applyFontSize();
        updateVisibility();
    }

    private void applyStyle() {
        try {
            int textColor = Color.parseColor(Prefs.textColor(this));
            int bgColor = Color.parseColor(Prefs.bgColor(this));
            int alpha = (int) (Math.min(Math.max(Prefs.bgAlpha(this), 0), 100) * 255 / 100.0);
            GradientDrawable bg = new GradientDrawable();
            bg.setColor((alpha << 24) | (bgColor & 0xFFFFFF));
            bg.setCornerRadius(dp(10));
            container.setBackground(bg);
            synchronized (lines) {
                for (int i = 0; i < finalsBox.getChildCount(); i++) {
                    TextView tv = (TextView) finalsBox.getChildAt(i);
                    tv.setTextColor(textColor);
                    tv.setShadowLayer(dp(3), 0, 0, Color.BLACK);
                }
            }
            draftView.setTextColor(textColor);
            partialView.setTextColor(textColor);
            applyFontSize();
            if (overlayAdded) {
                windowManager.updateViewLayout(overlay, overlayParams());
            }
            Log.i(TAG, "style applied");
        } catch (Exception e) {
            Log.w(TAG, "style apply failed: " + e);
        }
    }

    private TextView makeTextView() {
        TextView tv = new TextView(this);
        try {
            tv.setTextColor(Color.parseColor(Prefs.textColor(this)));
        } catch (Exception e) {
            tv.setTextColor(Color.WHITE);
        }
        tv.setGravity(Gravity.CENTER);
        tv.setLineSpacing(dp(2), 1f);
        tv.setShadowLayer(dp(3), 0, 0, Color.BLACK);
        return tv;
    }

    private void applyFontSize() {
        float sp = Prefs.fontSp(this);
        synchronized (lines) {
            for (int i = 0; i < finalsBox.getChildCount(); i++) {
                ((TextView) finalsBox.getChildAt(i)).setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
            }
        }
        draftView.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        partialView.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
    }

    private void updateVisibility() {
        boolean hasContent;
        synchronized (lines) {
            hasContent = !lines.isEmpty()
                    || partialView.getVisibility() == View.VISIBLE
                    || draftView.getVisibility() == View.VISIBLE;
        }
        container.setVisibility(hasContent ? View.VISIBLE : View.INVISIBLE);
    }

    private void pruneLoop() {
        if (!running) return;
        long now = System.currentTimeMillis();
        boolean changed = false;
        synchronized (lines) {
            Iterator<Line> it = lines.iterator();
            while (it.hasNext()) {
                long age = now - it.next().at;
                if (age > LINE_TTL_MS && age > MIN_DISPLAY_MS) {
                    it.remove();
                    changed = true;
                }
            }
            while (lines.size() > MAX_LINES) {
                lines.pollFirst();
                changed = true;
            }
            if (changed) renderFinalsLocked();
        }
        updateVisibility();
        main.postDelayed(this::pruneLoop, 400);
    }

    private int renderedCount = 0;

    private void renderFinalsLocked() {
        finalsBox.removeAllViews();
        for (Line l : lines) {
            TextView tv = makeTextView();
            tv.setText(l.text);
            tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, Prefs.fontSp(this));
            finalsBox.addView(tv);
        }
        if (finalsBox.getChildCount() > renderedCount && renderedCount >= 0) {
            View newest = finalsBox.getChildAt(finalsBox.getChildCount() - 1);
            if (newest != null) {
                newest.setAlpha(0f);
                newest.animate().alpha(1f).setDuration(220).start();
            }
        }
        renderedCount = finalsBox.getChildCount();
    }

    // ---- events from socket / demo ----

    private void clearAll() {
        Log.d(TAG, "clearAll");
        synchronized (lines) {
            lines.clear();
            renderFinalsLocked();
            draftView.setVisibility(View.GONE);
            draftView.setText("");
            partialView.setVisibility(View.GONE);
            partialView.setText("");
        }
        updateVisibility();
    }

    private void onPartial(String text) {
        Log.d(TAG, "onPartial: " + text);
        String mode = Prefs.displayMode(this);
        boolean showPartials = Prefs.showPartial(this) && !"en".equals(mode);
        synchronized (lines) {
            if (text == null || text.isEmpty() || !showPartials) {
                partialView.setVisibility(View.GONE);
                partialView.setText("");
            } else {
                partialView.setText(text);
                partialView.setVisibility(View.VISIBLE);
            }
        }
        updateVisibility();
    }

    private void onDraftEn(String text) {
        Log.d(TAG, "onDraftEn: " + text);
        String mode = Prefs.displayMode(this);
        synchronized (lines) {
            if (text == null || text.isEmpty() || "de".equals(mode)) {
                draftView.setVisibility(View.GONE);
                draftView.setText("");
            } else {
                draftView.setText(text);
                draftView.setVisibility(View.VISIBLE);
            }
        }
        updateVisibility();
    }

    private void onFinalAmend(String text) {
        Log.d(TAG, "onFinalAmend: " + text);
        if (text == null || text.isEmpty()) return;
        synchronized (lines) {
            if (!lines.isEmpty()) lines.pollLast();
        }
        onFinal(text, "");
    }

    private void onFinal(String text, String original) {
        Log.d(TAG, "onFinal: " + text);
        if (text == null || text.isEmpty()) return;
        String mode = Prefs.displayMode(this);
        String display;
        if ("de".equals(mode) && original != null && !original.isEmpty()) {
            display = original;
        } else {
            display = text;
        }
        synchronized (lines) {
            lines.addLast(new Line(display, System.currentTimeMillis()));
            while (lines.size() > MAX_LINES) lines.pollFirst();
            renderFinalsLocked();
            draftView.setVisibility(View.GONE);
            draftView.setText("");
            partialView.setVisibility(View.GONE);
            partialView.setText("");
        }
        updateVisibility();
    }

    private void handleJson(String msg) {
        try {
            JSONObject o = new JSONObject(msg);
            String type = o.optString("type", "");
            if ("style".equals(type)) {
                org.json.JSONObject s = o.optJSONObject("style");
                if (s != null) {
                    Prefs.setStyle(this, s);
                    applyStyle();
                }
            } else if ("status".equals(type)) {
                org.json.JSONObject s = o.optJSONObject("style");
                if (s != null) {
                    Prefs.setStyle(this, s);
                    applyStyle();
                }
            } else if ("partial".equals(type)) {
                onPartial(o.optString("text", ""));
            } else if ("partial_en".equals(type)) {
                onDraftEn(o.optString("text", ""));
            } else if ("final".equals(type)) {
                onFinal(o.optString("text", ""), o.optString("original", ""));
            } else if ("final_amend".equals(type)) {
                onFinalAmend(o.optString("text", ""));
            } else if ("clear".equals(type)) {
                clearAll();
            }
        } catch (Exception ignored) {
        }
    }

    // ---- live socket ----

    private void startSocket() {
        if (ws != null) return;
        connectSocket();
    }

    private void connectSocket() {
        if (!running || demo) return;
        String host = Prefs.host(this);
        int port = Prefs.port(this);
        ws = new WsClient(host, port, "/ws", new WsClient.Listener() {
            @Override
            public void onOpen() {
                reconnectDelayMs = 1000;
                if (pendingCmd != null) {
                    if (ws.sendText(pendingCmd)) pendingCmd = null;
                }
            }

            @Override
            public void onText(String message) {
                main.post(() -> {
                    if (running && !demo) handleJson(message);
                });
            }

            @Override
            public void onClosed(Exception cause) {
                main.post(() -> {
                    ws = null;
                    onPartial(null);
                    if (running && !demo) {
                        long delay = reconnectDelayMs;
                        reconnectDelayMs = Math.min(reconnectDelayMs * 2, RECONNECT_MAX_MS);
                        main.postDelayed(() -> {
                            if (running && !demo && ws == null) connectSocket();
                        }, delay);
                    }
                });
            }
        });
        ws.connect();
    }

    private void stopSocket() {
        WsClient s = ws;
        ws = null;
        if (s != null) s.close();
    }

    // ---- demo mode ----

    private static final String[][] DEMO_LINES = {
            {"Guten Abend, meine Damen und Herren.", "Good evening, ladies and gentlemen."},
            {"Hast du das gesehen, gerade eben?", "Did you see that, just now?"},
            {"Ich glaube, wir sollten hier bleiben.", "I think we should stay here."},
            {"Das kann doch nicht wahr sein.", "That can't be true."},
            {"Lass uns morgen ganz früh losfahren.", "Let's leave very early tomorrow."},
    };

    private void startDemo() {
        if (demoRunning) return;
        demoRunning = true;
        demoTick();
    }

    private void stopDemo() {
        demoRunning = false;
        demoHandler.removeCallbacksAndMessages(null);
    }

    private void demoTick() {
        if (!running || !demo || !demoRunning) return;
        String[] pair = DEMO_LINES[demoIdx % DEMO_LINES.length];
        demoIdx++;
        onPartial(pair[0]);
        demoHandler.postDelayed(() -> {
            if (running && demo && demoRunning) onFinal(pair[1], pair[0]);
        }, 900);
        demoHandler.postDelayed(this::demoTick, 3600);
    }

    private int dp(int v) {
        return (int) TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }
}
