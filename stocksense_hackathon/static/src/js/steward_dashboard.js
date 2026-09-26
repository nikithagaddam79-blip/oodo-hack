/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class StockSenseDashboard extends Component {
    static template = "stocksense.StewardDashboard";

    setup() {
        this.rpc = useService("rpc");
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: false,
            isRunningSteward: false,
            selectedExplainItem: null,
            kpis: {
                total_products: 0,
                total_stock: 0,
                pending_ops: 0,
                low_stock_items: 0,
                steward_alerts: 0,
                critical_alerts: 0,
                delayed_ops: 0,
                pending_reviews: 0,
            },
            watchlist: [],
            adjustments: [],
        });

        onWillStart(() => this.fetchData());
    }

    async fetchData() {
        this.state.isLoading = true;
        try {
            const data = await this.rpc("/stocksense/dashboard/data", {});
            if (data.success) {
                this.state.kpis = data.kpis;
                this.state.watchlist = data.watchlist;
                this.state.adjustments = data.adjustments;
            }
        } catch (err) {
            this.notification.add("Failed to load dashboard data.", { type: "danger" });
        } finally {
            this.state.isLoading = false;
        }
    }

    async runStewardNow() {
        this.state.isRunningSteward = true;
        try {
            const res = await this.rpc("/stocksense/steward/run", {});
            if (res.success) {
                this.notification.add("StockSense Steward audit completed successfully.", { type: "success" });
                await this.fetchData();
            }
        } catch (err) {
            this.notification.add("Error running Steward audit.", { type: "danger" });
        } finally {
            this.state.isRunningSteward = false;
        }
    }

    openExplainModal(item) {
        this.state.selectedExplainItem = item;
    }

    closeExplainModal() {
        this.state.selectedExplainItem = null;
    }

    async submitFeedback(itemId, feedbackType) {
        try {
            const method = feedbackType === 'true_positive' ? 'action_feedback_true_positive' : 'action_feedback_false_positive';
            await this.orm.call("stocksense.watchlist.item", method, [[itemId]]);
            this.notification.add("Feedback recorded. Adaptive thresholds updated.", { type: "success" });
            this.closeExplainModal();
            await this.fetchData();
        } catch (err) {
            this.notification.add("Error saving manager feedback.", { type: "danger" });
        }
    }

    async createRecountTask(itemId) {
        try {
            await this.orm.call("stocksense.watchlist.item", "action_create_recount_activity", [[itemId]]);
            this.notification.add("Recount activity scheduled in Odoo.", { type: "success" });
            await this.fetchData();
        } catch (err) {
            this.notification.add("Error scheduling activity.", { type: "danger" });
        }
    }

    async approveAdjustment(adjId) {
        try {
            await this.orm.call("stocksense.adjustment.request", "action_approve", [[adjId]]);
            this.notification.add("Adjustment approved and applied to inventory.", { type: "success" });
            await this.fetchData();
        } catch (err) {
            this.notification.add(err.message || "Approval failed.", { type: "danger" });
        }
    }

    async rejectAdjustment(adjId) {
        try {
            await this.orm.call("stocksense.adjustment.request", "action_reject", [[adjId]]);
            this.notification.add("Adjustment rejected.", { type: "info" });
            await this.fetchData();
        } catch (err) {
            this.notification.add(err.message || "Rejection failed.", { type: "danger" });
        }
    }
}

registry.category("actions").add("stocksense_dashboard", StockSenseDashboard);
