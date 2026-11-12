/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const actionRegistry = registry.category("actions");

export async function einvoiceGetLocationAction(env, action) {
    const context = action.context || {};
    const params = action.params || {};

    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            env.services.notification.add(_t("Geolocation is not supported by this browser/device."), { type: "danger" });
            resolve(false);
            return;
        }

        navigator.geolocation.getCurrentPosition(
            async (position) => {
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;

                const newContext = {
                    ...context,
                    geo_fencing_latitude: lat,
                    geo_fencing_longitude: lon,
                };

                // We don't need next_action, we rely on next_method

                // Call the next action/wizard (which will be a server action or window action)
                // We'll invoke the backend method that expects this context.
                if (params.next_method && params.res_model && params.res_id) {
                    try {
                        const result = await env.services.orm.call(
                            params.res_model,
                            params.next_method,
                            [[params.res_id]],
                            { context: newContext }
                        );
                        if (result) {
                            await env.services.action.doAction(result);
                        }
                        resolve(result);
                    } catch (error) {
                        let errMsg = _t("Error communicating with server.");
                        if (error && error.data && error.data.message) {
                            errMsg = error.data.message;
                        } else if (error && error.message) {
                            errMsg = error.message;
                        }
                        env.services.notification.add(errMsg, { type: "danger" });
                        resolve(false);
                    }
                } else {
                    env.services.notification.add(
                        `Missing parameters. res_model: ${params.res_model}, next_method: ${params.next_method}, res_id: ${params.res_id}`, 
                        { type: "danger" }
                    );
                    resolve(false);
                }
            },
            (error) => {
                let msg = _t("Failed to get location.");
                if (error.code === error.PERMISSION_DENIED) {
                    msg = _t("Location permission denied. Cannot proceed.");
                }
                env.services.notification.add(msg, { type: "danger" });
                resolve(false);
            },
            {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 0
            }
        );
    });
}

actionRegistry.add("einvoice_get_location", einvoiceGetLocationAction);
