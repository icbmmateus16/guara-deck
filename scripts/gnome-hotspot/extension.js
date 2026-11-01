import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import NM from 'gi://NM';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const HotspotToggle = GObject.registerClass(
class HotspotToggle extends QuickSettings.QuickToggle {
    constructor() {
        super({title: 'Hotspot ACESSO', subtitle: 'Desligado',
            iconName: 'network-wireless-hotspot-symbolic', toggleMode: false});
    }
});

export default class HotspotExtension extends Extension {
    enable() {
        this._cancel = new Gio.Cancellable();
        this._indicator = new QuickSettings.SystemIndicator();
        this._toggle = new HotspotToggle();
        this._toggle.reactive = false;
        this._toggle.connect('clicked', () => this._clicked());
        this._indicator.quickSettingsItems.push(this._toggle);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
        NM.Client.new_async(this._cancel, (_source, result) => {
            try {
                const client = NM.Client.new_finish(result);
                if (this._cancel?.is_cancelled() !== false)
                    return;
                this._client = client;
                this._sync();
                this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
                    this._sync();
                    return GLib.SOURCE_CONTINUE;
                });
            } catch (error) {
                if (this._toggle) {
                    this._toggle.subtitle = 'Indisponível';
                    console.error(error);
                }
            }
        });
    }

    _connection() {
        return this._client?.get_connections().find(connection => {
            const wifi = connection.get_setting_wireless();
            const ssid = wifi?.get_ssid();
            return wifi?.get_mode() === 'ap' && ssid &&
                new TextDecoder().decode(ssid.get_data()) === 'ACESSO';
        });
    }

    _active(connection) {
        return this._client.get_active_connections().find(
            active => active.get_uuid() === connection.get_uuid());
    }

    _sync() {
        const connection = this._connection();
        const active = connection && this._active(connection);
        const state = active?.get_state();
        this._toggle.checked = state === NM.ActiveConnectionState.ACTIVATED;
        this._toggle.subtitle = this._busy ? 'Aguarde…' : !connection ? 'Perfil não encontrado' :
            state === NM.ActiveConnectionState.ACTIVATING ? 'Ligando…' :
            state === NM.ActiveConnectionState.DEACTIVATING ? 'Desligando…' :
            this._toggle.checked ? 'Ligado' : 'Desligado';
        this._toggle.reactive = Boolean(connection) && !this._busy &&
            state !== NM.ActiveConnectionState.ACTIVATING &&
            state !== NM.ActiveConnectionState.DEACTIVATING;
    }

    _clicked() {
        const connection = this._connection();
        if (!connection || this._busy)
            return;
        const active = this._active(connection);
        this._busy = true;
        this._sync();
        const finished = (client, result) => {
            try {
                if (active)
                    client.deactivate_connection_finish(result);
                else
                    client.activate_connection_finish(result);
            } catch (error) {
                if (!this._cancel?.is_cancelled())
                    Main.notifyError('Hotspot ACESSO', error.message);
            } finally {
                this._busy = false;
                if (this._toggle)
                    this._sync();
            }
        };
        // Somente este clique pode ativar a rede. enable() apenas observa o estado.
        if (active)
            this._client.deactivate_connection_async(active, this._cancel, finished);
        else
            this._client.activate_connection_async(connection, null, null, this._cancel, finished);
    }

    disable() {
        this._cancel.cancel();
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
        this._toggle.destroy();
        this._indicator.destroy();
        this._toggle = this._indicator = this._client = null;
    }
}
