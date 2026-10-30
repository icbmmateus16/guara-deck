#!/system/bin/sh
# Terceira limpeza: o tablet fica só para o Guará (RAM e CPU para o painel).
# Desfazer: sh /sdcard/tc/tc_restore.sh (reativa os apps e os scripts de boot da ROM).
trap "" HUP
D=/sdcard/tc
echo "inicio $(date)"
grep -E "MemFree|^Cached" /proc/meminfo

# Apps já desativados (ou escondidos) cujo processo ficou vivo desde antes da limpeza:
# só um reboot ou um force-stop tira eles da RAM. Desativados, não voltam.
for p in com.google.android.googlequicksearchbox com.google.android.gm \
  com.google.android.marvin.talkback com.wmt.airshow com.android.settings
do
  am force-stop $p && echo "force-stop $p"
done
# sobra dos prints de tela (processo separado do SystemUI). Pelo pidof: no su, o ps é o do
# busybox, com outras colunas. Não usar pm block em app persistente (com.wmt.airshow): o Android
# religa ele, ele quebra em loop e o aviso "parou" fica por cima do painel.
for pid in $(pidof com.android.systemui:screenshot); do
  kill $pid && echo "kill systemui:screenshot $pid"
done

# Scripts de "turbo" da ROM que atrapalham um painel dedicado:
#  06loopy_smoothness_tweak e 09setrenice dão prioridade máxima (-20) ao telefone e à barra do
#  sistema, acima do Guará; 16sqlite_optimize faz VACUUM em todo banco .db a cada boot (boot lento
#  e risco de corromper banco que já está aberto). Sem permissão de execução, o run-parts pula.
mount -o remount,rw /system
for f in 06loopy_smoothness_tweak 09setrenice 16sqlite_optimize; do
  [ -x /system/etc/init.d/$f ] && chmod 644 /system/etc/init.d/$f && echo "init.d $f desligado"
done
mount -o remount,ro /system
grep -q "init.d" $D/tc_restore.sh || \
  echo 'mount -o remount,rw /system; chmod 755 /system/etc/init.d/*; mount -o remount,ro /system' >> $D/tc_restore.sh

# prioridade normal já agora, sem esperar o próximo boot
for p in com.android.phone com.android.systemui; do
  for pid in $(pidof $p); do renice 0 $pid && echo "renice 0 $p"; done
done

echo "fim $(date)"
grep -E "MemFree|^Cached" /proc/meminfo
echo DONE
