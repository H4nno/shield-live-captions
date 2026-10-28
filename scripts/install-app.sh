#!/usr/bin/env bash
# Build + install the overlay app on an Android TV box (e.g. NVIDIA Shield)
# via network adb, and grant the overlay permission without touching the TV UI.
#
# Usage: ./scripts/install-app.sh <TV_BOX_IP>       (adb over TCP must be enabled on the box)
set -euo pipefail

IP="${1:?usage: install-app.sh <tv-box-ip>}"
PKG="app.shieldcc"
APK="$(cd "$(dirname "$0")/.." && pwd)/app/build/outputs/apk/debug/app-debug.apk"

if [[ ! -f "$APK" ]]; then
  echo "APK not found at $APK — build first:  ./gradlew :app:assembleDebug" >&2
  exit 1
fi

adb connect "$IP:5555"
adb -s "$IP:5555" install -r "$APK"
adb -s "$IP:5555" shell appops set "$PKG" SYSTEM_ALERT_WINDOW allow
echo "overlay permission: $(adb -s "$IP:5555" shell appops get "$PKG" SYSTEM_ALERT_WINDOW)"

cat <<EOF

Done. Configure the server address once in the app settings ("Live Captions"
on the launcher), or from adb:

  adb -s $IP:5555 shell "run-as $PKG sh -c 'mkdir -p shared_prefs && cat > shared_prefs/shieldcc.xml <<X
<?xml version=\\"1.0\\" encoding=\\"utf-8\\" standalone=\\"yes\\" ?>
<map>
    <string name=\\"host\\">SERVER_IP</string>
    <int name=\\"port\\" value=\\"8799\\" />
    <boolean name=\\"autoStart\\" value=\\"true\\" />
</map>
X'"

Start captions:
  adb -s $IP:5555 shell am start-foreground-service -n $PKG/.SubtitleOverlayService -a $PKG.action.START
Stop:
  adb -s $IP:5555 shell am start-foreground-service -n $PKG/.SubtitleOverlayService -a $PKG.action.STOP
EOF
