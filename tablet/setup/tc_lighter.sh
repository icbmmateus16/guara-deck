#!/system/bin/sh
# Segunda limpeza: o tablet vira só o painel do Capi (o Capi passa a ser a tela inicial).
# Desfazer: sh /sdcard/tc/tc_restore.sh (reativa tudo de disabled_by_tc.txt).
trap "" HUP
D=/sdcard/tc
echo "inicio $(date)"

for p in eu.thedarken.sdm eu.thedarken.wl; do
  echo "uninstall $p: $(pm uninstall $p 2>&1)"
done

for p in \
  com.android.calculator2 com.android.camera2 com.android.contacts com.android.deskclock \
  com.android.musicfx com.android.onetimeinitializer com.android.printspooler \
  com.android.providers.downloads.ui com.android.smspush com.android.wallpapercropper \
  com.google.android.apps.cloudprint com.google.android.apps.uploader com.google.android.backup \
  com.google.android.syncadapters.bookmarks com.svox.pico com.wmt.myrecorder com.wmt.snapshot \
  jp.co.omronsoft.openwnn com.teslacoilsw.launcher
do
  r=$(pm disable $p 2>&1)
  echo "disable $p: $r"
  case "$r" in *disabled*) echo $p >> $D/disabled_by_tc.txt ;; esac
done

# Fuso sem o horário de verão que o Android de 2014 ainda acha que existe no Brasil.
setprop persist.sys.timezone America/Bahia
service call alarm 3 s16 America/Bahia > /dev/null

am kill-all
echo "fim $(date)"
grep -E "MemFree|^Cached" /proc/meminfo
echo DONE
