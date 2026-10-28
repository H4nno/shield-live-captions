package app.shieldcc;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {

    private EditText hostEdit;
    private EditText portEdit;
    private SeekBar fontSeek;
    private Spinner positionSpin;
    private Spinner modeSpin;
    private Switch partialSwitch;
    private Switch autoStartSwitch;
    private TextView overlayState;
    private TextView fontLabel;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(32), dp(28), dp(32), dp(40));
        scroll.addView(root, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = label(getString(R.string.app_name), 30, true);
        root.addView(title);
        root.addView(sub("Live captions overlay — German audio in, English text out"));
        root.addView(spacer(20));

        root.addView(label("Server (Spark box)", 20, false));
        LinearLayout hostRow = new LinearLayout(this);
        hostRow.setOrientation(LinearLayout.HORIZONTAL);
        hostEdit = new EditText(this);
        hostEdit.setText(Prefs.host(this));
        hostEdit.setHint("192.168.x.x");
        hostEdit.setTextSize(22);
        hostEdit.setSingleLine();
        portEdit = new EditText(this);
        portEdit.setText(String.valueOf(Prefs.port(this)));
        portEdit.setTextSize(22);
        portEdit.setSingleLine();
        portEdit.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        portEdit.setEms(5);
        LinearLayout.LayoutParams hp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 3f);
        LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        hostRow.addView(hostEdit, hp);
        hostRow.addView(portEdit, pp);
        root.addView(hostRow);
        root.addView(spacer(16));

        fontLabel = label("Font size: " + (int) Prefs.fontSp(this) + " sp", 20, false);
        root.addView(fontLabel);
        fontSeek = new SeekBar(this);
        fontSeek.setMax(48); // 16..64
        fontSeek.setProgress((int) Prefs.fontSp(this) - 16);
        fontSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar sb, int v, boolean fromUser) {
                Prefs.setFontSp(MainActivity.this, v + 16);
                fontLabel.setText("Font size: " + (v + 16) + " sp");
            }
            @Override public void onStartTrackingTouch(SeekBar sb) {}
            @Override public void onStopTrackingTouch(SeekBar sb) {}
        });
        root.addView(fontSeek);
        root.addView(spacer(16));

        root.addView(label("Position", 20, false));
        positionSpin = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item,
                new String[]{"Bottom", "Lower third", "Top"});
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        positionSpin.setAdapter(adapter);
        positionSpin.setSelection(Prefs.position(this));
        root.addView(positionSpin);
        root.addView(spacer(16));

        root.addView(label("Display", 20, false));
        modeSpin = new Spinner(this);
        String curMode = Prefs.displayMode(this);
        ArrayAdapter<String> modeAdapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item,
                new String[]{"English + German partials", "English only", "German only"});
        modeAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        modeSpin.setAdapter(modeAdapter);
        modeSpin.setSelection("en".equals(curMode) ? 1 : ("de".equals(curMode) ? 2 : 0));
        root.addView(modeSpin);
        root.addView(spacer(16));

        partialSwitch = new Switch(this);
        partialSwitch.setText("Show live partials (German interim text)");
        partialSwitch.setTextSize(20);
        partialSwitch.setChecked(Prefs.showPartial(this));
        partialSwitch.setOnCheckedChangeListener((b, v) -> Prefs.setShowPartial(MainActivity.this, v));
        root.addView(partialSwitch);
        root.addView(spacer(10));

        autoStartSwitch = new Switch(this);
        autoStartSwitch.setText("Start automatically on boot");
        autoStartSwitch.setTextSize(20);
        autoStartSwitch.setChecked(Prefs.autoStart(this));
        autoStartSwitch.setOnCheckedChangeListener((b, v) -> Prefs.setAutoStart(MainActivity.this, v));
        root.addView(autoStartSwitch);
        root.addView(spacer(24));

        overlayState = sub("");
        root.addView(overlayState);
        root.addView(spacer(12));

        Button save = bigButton("Save server settings");
        save.setOnClickListener(v -> {
            String host = hostEdit.getText().toString().trim();
            String portStr = portEdit.getText().toString().trim();
            int port;
            try {
                port = Integer.parseInt(portStr);
            } catch (NumberFormatException e) {
                port = 8765;
            }
            Prefs.setServer(MainActivity.this, host, port);
            Toast.makeText(MainActivity.this, "Saved", Toast.LENGTH_SHORT).show();
        });
        root.addView(save);
        root.addView(spacer(12));

        Button grant = bigButton("Grant overlay permission…");
        grant.setOnClickListener(v -> {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
            } catch (Exception e) {
                Toast.makeText(MainActivity.this,
                        "Not available on this TV — use: adb shell appops set "
                                + getPackageName() + " SYSTEM_ALERT_WINDOW allow",
                        Toast.LENGTH_LONG).show();
            }
        });
        root.addView(grant);
        root.addView(spacer(12));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        Button start = bigButton("Start live");
        start.setOnClickListener(v -> startServiceAction(SubtitleOverlayService.ACTION_START, false));
        Button demo = bigButton("Demo");
        demo.setOnClickListener(v -> startServiceAction(SubtitleOverlayService.ACTION_START, true));
        Button stop = bigButton("Stop");
        stop.setOnClickListener(v -> startServiceAction(SubtitleOverlayService.ACTION_STOP, false));
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        row.addView(start, bp);
        row.addView(demo, bp);
        row.addView(stop, bp);
        root.addView(row);

        setContentView(scroll);
        positionSpin.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(android.widget.AdapterView<?> p, View v, int pos, long id) {
                Prefs.setPosition(MainActivity.this, pos);
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> p) {}
        });
        modeSpin.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(android.widget.AdapterView<?> p, View v, int pos, long id) {
                Prefs.setDisplayMode(MainActivity.this, pos == 1 ? "en" : (pos == 2 ? "de" : "both"));
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> p) {}
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        boolean ok = Settings.canDrawOverlays(this);
        overlayState.setText(ok
                ? "Overlay permission: granted ✓"
                : "Overlay permission MISSING. Run on your computer:\nadb shell appops set "
                        + getPackageName() + " SYSTEM_ALERT_WINDOW allow");
    }

    private void startServiceAction(String action, boolean demo) {
        saveServer();
        Intent svc = new Intent(this, SubtitleOverlayService.class)
                .setAction(action)
                .putExtra(SubtitleOverlayService.EXTRA_DEMO, demo);
        startForegroundService(svc);
    }

    private void saveServer() {
        String host = hostEdit.getText().toString().trim();
        int port;
        try {
            port = Integer.parseInt(portEdit.getText().toString().trim());
        } catch (NumberFormatException e) {
            port = 8765;
        }
        Prefs.setServer(this, host, port);
    }

    private TextView label(String text, float sp, boolean bold) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(sp);
        if (bold) tv.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        return tv;
    }

    private TextView sub(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(16);
        tv.setAlpha(0.65f);
        return tv;
    }

    private View spacer(int h) {
        View v = new View(this);
        v.setLayoutParams(new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(h)));
        return v;
    }

    private Button bigButton(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextSize(18);
        b.setAllCaps(false);
        b.setGravity(Gravity.CENTER);
        return b;
    }

    private int dp(int v) {
        return (int) android.util.TypedValue.applyDimension(
                android.util.TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }
}
