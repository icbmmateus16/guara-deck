package dev.capi.tablet;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Abre o Guará assim que o tablet termina de ligar. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        // Pelo Home (sem nomear a classe): se o Guará já é a tela inicial, cai na mesma tela
        // em vez de abrir uma segunda cópia por cima.
        Intent open = new Intent(Intent.ACTION_MAIN);
        open.addCategory(Intent.CATEGORY_HOME);
        open.setPackage(context.getPackageName());
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(open);
    }
}
