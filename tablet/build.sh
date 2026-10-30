#!/usr/bin/env bash
# Compila o app do tablet (Android 4.4+) sem Gradle: aapt2 + javac + d8 + apksigner.
# Uso: tablet/build.sh            -> gera tablet/build/capi.apk
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
BT="$SDK/build-tools/34.0.0"
JAR="$SDK/platforms/android-34/android.jar"
export JAVA_HOME="${JAVA_HOME:-$HOME/Android/jdk-17}"
export PATH="$JAVA_HOME/bin:$PATH"

APP="$HERE/app"
OUT="$HERE/build"
rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex" "$OUT/assets"

# Config embutida: token e porta do servidor + IP atual do PC (o app acha o PC sozinho se mudar).
python3 - "$ROOT/server/config.json" "$OUT/assets/capi.json" <<'EOF'
import json, socket, sys
cfg = json.load(open(sys.argv[1]))
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("192.168.0.1", 9))
json.dump({"token": cfg["token"], "port": cfg.get("port", 47801), "host": s.getsockname()[0]}, open(sys.argv[2], "w"))
EOF
cp "$APP/assets/"* "$OUT/assets/"

"$BT/aapt2" compile --dir "$APP/res" -o "$OUT/res.zip"
"$BT/aapt2" link -I "$JAR" --manifest "$APP/AndroidManifest.xml" -A "$OUT/assets" \
  --min-sdk-version 19 --target-sdk-version 19 --version-code 1 --version-name 1.0 \
  --java "$OUT/gen" -o "$OUT/base.apk" "$OUT/res.zip"

# o caminho do projeto tem espaços ("Área de trabalho"): lista de fontes vai num arquivo de argumentos
find "$APP/src" "$OUT/gen" -name '*.java' | sed 's/.*/"&"/' > "$OUT/sources.txt"
javac -nowarn -Xlint:-options -source 8 -target 8 -encoding UTF-8 -bootclasspath "$JAR" -classpath "$JAR" \
  -d "$OUT/classes" @"$OUT/sources.txt"
jar cf "$OUT/classes.jar" -C "$OUT/classes" .

"$BT/d8" --min-api 19 --lib "$JAR" --output "$OUT/dex" "$OUT/classes.jar"

cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -u "$OUT/unsigned.apk" classes.dex)
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

KS="$HERE/capi-debug.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -storepass android -keypass android -alias capi \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Capi" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --min-sdk-version 19 --out "$OUT/capi.apk" "$OUT/aligned.apk"

echo "OK: $OUT/capi.apk ($(du -h "$OUT/capi.apk" | cut -f1))"
