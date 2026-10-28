package app.shieldcc;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class ToggleReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent != null ? intent.getAction() : null;
        if (action == null) return;
        Intent svc;
        switch (action) {
            case "app.shieldcc.action.TOGGLE":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_TOGGLE);
                break;
            case "app.shieldcc.action.SHOW":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_START);
                break;
            case "app.shieldcc.action.HIDE":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_STOP);
                break;
            case "app.shieldcc.action.SIZE_UP":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_SIZE_UP);
                break;
            case "app.shieldcc.action.SIZE_DOWN":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_SIZE_DOWN);
                break;
            case "app.shieldcc.action.DEMO":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_START)
                        .putExtra(SubtitleOverlayService.EXTRA_DEMO, true);
                break;
            case "app.shieldcc.action.MODE":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_CYCLE_MODE);
                break;
            case "app.shieldcc.action.LANG_CYCLE":
                svc = new Intent(context, SubtitleOverlayService.class)
                        .setAction(SubtitleOverlayService.ACTION_LANG_CYCLE);
                break;
            default:
                return;
        }
        context.startForegroundService(svc);
    }
}
