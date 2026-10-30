#!/system/bin/sh
# Limpeza "modo dedicado" do tablet Genesis (Android 4.4, root).
# Roda no próprio tablet via su, sobrevive à queda do cabo USB.
# Desfazer: sh /sdcard/tc/tc_restore.sh (reativa tudo que foi desativado).
trap "" HUP

D=/sdcard/tc
mkdir -p $D
echo "inicio $(date)"

# ADB por Wi-Fi permanente (porta 5555): o cabo deste tablet é instável e nem carrega.
# Para voltar ao ADB por USB: su -c 'setprop persist.adb.tcp.port ""; stop adbd; start adbd'
svc wifi enable
setprop persist.adb.tcp.port 5555
setprop service.adb.tcp.port 5555
stop adbd
start adbd

pm list packages -s > $D/system_before.txt
pm list packages -3 > $D/user_before.txt
pm list packages -d > $D/disabled_before.txt

has() { grep -q "^package:$1\$" $D/system_before.txt $D/user_before.txt; }

# Apps de terceiros sem utilidade num painel dedicado: desinstalar (libera RAM e espaço).
for p in \
  com.ram.memory.booster.cpu.saver com.oasisfeng.greenify cm.aptoide.pt \
  com.facebook.lite com.facebook.mlite com.instagram.lite com.twitter.android.lite \
  com.pinterest.twa com.amazon.avod.thirdpartyclient com.wb.goog.scribblenauts3 \
  com.google.android.apps.docs com.google.android.apps.books com.google.android.apps.translate \
  com.google.android.apps.adm com.estrongs.android.pop ph.spacedesk.beta \
  com.opera.mini.native com.awedea.nyx
do
  has $p && echo "uninstall $p: $(pm uninstall $p 2>&1)"
done

# YouTube veio como app de sistema com atualização: remove a atualização e desativa abaixo.
has com.google.android.youtube && echo "uninstall-updates youtube: $(pm uninstall com.google.android.youtube 2>&1)"

# Apps de sistema: desativar (reversível com pm enable, dados preservados).
: > $D/disabled_by_tc.txt
for p in \
  com.google.android.gms com.google.android.gsf com.google.android.gsf.login \
  com.android.vending com.google.android.googlequicksearchbox com.google.android.gm \
  com.google.android.youtube com.google.android.partnersetup com.google.android.feedback \
  com.google.android.syncadapters.calendar com.google.android.syncadapters.contacts \
  com.google.android.backuptransport com.google.android.onetimeinitializer \
  com.google.android.music com.google.android.videos com.google.android.talk \
  com.google.android.apps.plus com.google.android.apps.maps com.google.android.street \
  com.google.android.apps.magazines com.google.android.play.games com.google.android.keep \
  com.google.android.apps.photos com.google.android.tts com.google.android.marvin.talkback \
  com.google.android.ears com.google.android.apps.genie.geniewidget com.google.android.voicesearch \
  com.google.android.apps.books com.google.android.apps.docs \
  com.android.chrome com.android.email com.android.exchange com.android.calendar \
  com.android.gallery3d com.android.music com.android.videoeditor com.android.quicksearchbox \
  com.android.galaxy4 com.android.magicsmoke com.android.noisefield com.android.phasebeam \
  com.android.musicvis com.android.wallpaper com.android.dreams.basic com.android.dreams.phototable \
  com.wmt.airshow org.telegram.messenger
do
  if has $p; then
    r=$(pm disable $p 2>&1)
    echo "disable $p: $r"
    case "$r" in *disabled*) echo $p >> $D/disabled_by_tc.txt ;; esac
  fi
done

cat > $D/tc_restore.sh <<'EOF'
#!/system/bin/sh
for p in $(cat /sdcard/tc/disabled_by_tc.txt); do pm enable $p; done
EOF

pm trim-caches 64G
am kill-all

# Ajustes para painel sempre ligado.
settings put system screen_brightness_mode 0
settings put system screen_brightness 255
settings put global stay_on_while_plugged_in 3
settings put global wifi_sleep_policy 2
settings put global window_animation_scale 0
settings put global transition_animation_scale 0
settings put global animator_duration_scale 0

# Governor "conservative" sobe a frequência devagar e deixa o toque travado.
g=/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors
for gov in interactive ondemand; do
  if grep -q $gov $g 2>/dev/null; then
    for c in /sys/devices/system/cpu/cpu[0-9]*; do echo $gov > $c/cpufreq/scaling_governor; done
    echo "governor=$gov"; break
  fi
done

svc wifi enable
echo "fim $(date)"
grep -E "MemFree|^Cached" /proc/meminfo
echo DONE
