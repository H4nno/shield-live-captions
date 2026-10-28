package app.shieldcc;

import android.content.Context;
import android.content.SharedPreferences;

public final class Prefs {
    private static final String FILE = "shieldcc";

    private Prefs() {}

    public static SharedPreferences get(Context ctx) {
        return ctx.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public static String host(Context ctx) {
        return get(ctx).getString("host", "192.168.0.0");
    }

    public static int port(Context ctx) {
        return get(ctx).getInt("port", 8799);
    }

    public static void setServer(Context ctx, String host, int port) {
        get(ctx).edit().putString("host", host).putInt("port", port).apply();
    }

    public static float fontSp(Context ctx) {
        return get(ctx).getFloat("fontSp", 28f);
    }

    public static void setFontSp(Context ctx, float sp) {
        get(ctx).edit().putFloat("fontSp", Math.max(16f, Math.min(64f, sp))).apply();
    }

    /** 0 = bottom, 1 = lower third, 2 = top */
    public static int position(Context ctx) {
        return get(ctx).getInt("position", 0);
    }

    public static void setPosition(Context ctx, int pos) {
        get(ctx).edit().putInt("position", Math.max(0, Math.min(2, pos))).apply();
    }

    public static boolean showPartial(Context ctx) {
        return get(ctx).getBoolean("showPartial", true);
    }

    public static void setShowPartial(Context ctx, boolean b) {
        get(ctx).edit().putBoolean("showPartial", b).apply();
    }

    /** display mode: "both" = English finals + German partials, "en" = English only, "de" = German only */
    public static String displayMode(Context ctx) {
        return get(ctx).getString("displayMode", "en");
    }

    public static void setDisplayMode(Context ctx, String mode) {
        if (!"both".equals(mode) && !"en".equals(mode) && !"de".equals(mode)) mode = "both";
        get(ctx).edit().putString("displayMode", mode).apply();
    }

    /** remote language-cycle state: "off" -> "en" -> "pt" -> "off" */
    public static String captionCycle(Context ctx) {
        return get(ctx).getString("captionCycle", "off");
    }

    public static void setCaptionCycle(Context ctx, String s) {
        get(ctx).edit().putString("captionCycle", s).apply();
    }

    // ---- overlay style ----

    public static int fontSpS(Context ctx) { return (int) fontSp(ctx); }

    public static String textColor(Context ctx) {
        return get(ctx).getString("textColor", "#FFFFFF");
    }

    public static String bgColor(Context ctx) {
        return get(ctx).getString("bgColor", "#000000");
    }

    public static int bgAlpha(Context ctx) {
        return get(ctx).getInt("bgAlpha", 70);
    }

    public static int widthPct(Context ctx) {
        return get(ctx).getInt("widthPct", 92);
    }

    public static void setStyle(Context ctx, org.json.JSONObject s) {
        get(ctx).edit()
                .putFloat("fontSp", s.optInt("fontSp", 28))
                .putString("textColor", s.optString("textColor", "#FFFFFF"))
                .putString("bgColor", s.optString("bgColor", "#000000"))
                .putInt("bgAlpha", s.optInt("bgAlpha", 70))
                .putInt("widthPct", s.optInt("widthPct", 92))
                .putInt("position", s.optInt("position", position(ctx)))
                .apply();
    }

    public static boolean autoStart(Context ctx) {
        return get(ctx).getBoolean("autoStart", true);
    }

    public static void setAutoStart(Context ctx, boolean b) {
        get(ctx).edit().putBoolean("autoStart", b).apply();
    }
}
