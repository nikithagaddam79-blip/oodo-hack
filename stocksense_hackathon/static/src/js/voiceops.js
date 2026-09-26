/** @odoo-module **/

import { Component, useState, onWillDestroy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class VoiceOpsModal extends Component {
    static template = "stocksense.VoiceOpsModal";
    static props = {
        state: Object,
        closeModal: Function,
    };

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.state = this.props.state;
        this.recognition = null;

        this.initSpeechRecognition();

        onWillDestroy(() => {
            if (this.recognition && this.state.isListening) {
                this.recognition.stop();
            }
        });
    }

    initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            this.recognition = new SpeechRecognition();
            this.recognition.continuous = false;
            this.recognition.interimResults = false;
            this.recognition.lang = "en-US";

            this.recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                this.state.transcript = transcript;
                this.state.isListening = false;
                this.processInput();
            };

            this.recognition.onerror = (event) => {
                this.state.isListening = false;
                this.notification.add(`Microphone notice: ${event.error || 'Speech stopped'}. You can type directly.`, {
                    type: "warning",
                });
            };

            this.recognition.onend = () => {
                this.state.isListening = false;
            };
        }
    }

    toggleSpeechRecognition() {
        if (!this.recognition) {
            this.notification.add("Web Speech API not supported in this browser. Please type your command.", {
                type: "warning",
            });
            return;
        }

        if (this.state.isListening) {
            this.recognition.stop();
            this.state.isListening = false;
        } else {
            this.state.isListening = true;
            this.state.transcript = "";
            try {
                this.recognition.start();
            } catch (e) {
                this.state.isListening = false;
            }
        }
    }

    applySuggestion(text) {
        this.state.transcript = text;
        this.processInput();
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && this.state.transcript.trim()) {
            this.processInput();
        }
    }

    async processInput() {
        if (!this.state.transcript.trim()) return;

        this.state.isProcessing = true;
        try {
            const res = await this.rpc("/voiceops/process", {
                speech_text: this.state.transcript.trim(),
            });

            this.state.isProcessing = false;
            if (!res.success) {
                const errMsg = res.errors ? res.errors.join(" ") : res.error;
                this.state.step = "result";
                this.state.resultSuccess = false;
                this.state.resultMessage = errMsg || "Could not understand command.";
                return;
            }

            const action = res.action;
            const resolved = res.resolved;

            // Direct non-mutating query
            if (action === "query_stock") {
                const execRes = await this.rpc("/voiceops/execute", {
                    payload: { action: "query_stock", resolved: resolved },
                });
                this.state.step = "result";
                this.state.resultSuccess = true;
                const breakdown = (execRes.location_breakdown || []).join("\n• ");
                this.state.resultMessage = `${execRes.message}\n\n• ${breakdown}`;
                return;
            } else if (action === "explain_alert") {
                const execRes = await this.rpc("/voiceops/execute", {
                    payload: { action: "explain_alert", resolved: resolved },
                });
                this.state.step = "result";
                this.state.resultSuccess = true;
                this.state.resultMessage = execRes.message || "Alert breakdown retrieved.";
                return;
            } else if (action === "run_steward") {
                const execRes = await this.rpc("/voiceops/execute", {
                    payload: { action: "run_steward", resolved: resolved },
                });
                this.state.step = "result";
                this.state.resultSuccess = true;
                this.state.resultMessage = execRes.message;
                return;
            }

            // Require Confirmation Stage
            this.state.step = "confirm";
            this.state.pendingPayload = { action: action, resolved: resolved };
            this.state.isAnomalous = Boolean(res.is_anomalous);
            this.state.riskScore = res.risk_score || 0;
            this.state.severity = res.severity || "normal";
            this.state.zScore = res.z_score || 0;
            this.state.explanation = res.explanation || "";
            this.state.evidence = res.evidence || "";
            this.state.recommendedAction = res.recommended_action || "";

            if (action === "receive") {
                this.state.actionTitle = `Receive ${resolved.quantity} units of ${resolved.product_name}`;
                this.state.actionDetails = `From Vendor: ${resolved.partner_name || 'Vendor'}`;
            } else if (action === "internal_transfer") {
                this.state.actionTitle = `Transfer ${resolved.quantity} units of ${resolved.product_name}`;
                this.state.actionDetails = `From ${resolved.source_location_name || 'Stock'} to ${resolved.destination_location_name}`;
            } else if (action === "adjust") {
                const sign = resolved.quantity < 0 ? "" : "+";
                this.state.actionTitle = `Adjust ${resolved.product_name} by ${sign}${resolved.quantity} units`;
                this.state.actionDetails = `Location: ${resolved.location_name || 'Warehouse Stock'} | Reason: ${resolved.reason || 'None specified'}`;
            } else if (action === "create_task") {
                this.state.actionTitle = `Schedule Physical Recount Task`;
                this.state.actionDetails = `Target: ${resolved.target_display || 'Location'}`;
            }

        } catch (err) {
            this.state.isProcessing = false;
            this.state.step = "result";
            this.state.resultSuccess = false;
            this.state.resultMessage = err.message || "Server communication error.";
        }
    }

    async executeOperation() {
        if (!this.state.pendingPayload) return;

        this.state.isProcessing = true;
        try {
            const res = await this.rpc("/voiceops/execute", {
                payload: this.state.pendingPayload,
            });
            this.state.isProcessing = false;
            this.state.step = "result";
            this.state.resultSuccess = res.success;
            this.state.resultMessage = res.message || (res.success ? "Operation successfully executed." : res.error);
        } catch (err) {
            this.state.isProcessing = false;
            this.state.step = "result";
            this.state.resultSuccess = false;
            this.state.resultMessage = err.message || "Failed to execute operation.";
        }
    }

    cancelConfirmation() {
        this.resetToInput();
    }

    resetToInput() {
        this.state.step = "input";
        this.state.transcript = "";
        this.state.pendingPayload = null;
        this.state.isAnomalous = false;
    }

    closeModal() {
        this.props.closeModal();
    }
}

export class VoiceOpsSystray extends Component {
    static template = "stocksense.VoiceOpsSystray";
    static components = { VoiceOpsModal };

    setup() {
        this.state = useState({
            isOpen: false,
            isListening: false,
            isProcessing: false,
            step: "input", // input | confirm | result
            transcript: "",
            pendingPayload: null,
            isAnomalous: false,
            riskScore: 0,
            severity: "normal",
            zScore: 0,
            explanation: "",
            evidence: "",
            recommendedAction: "",
            actionTitle: "",
            actionDetails: "",
            resultSuccess: false,
            resultMessage: "",
        });
    }

    openVoiceOps() {
        this.state.isOpen = true;
        this.state.step = "input";
        this.state.transcript = "";
        this.state.resultMessage = "";
    }

    closeModal() {
        this.state.isOpen = false;
        this.state.isListening = false;
    }
}

// Register into Systray
registry.category("systray").add("stocksense.VoiceOps", { Component: VoiceOpsSystray }, { sequence: 25 });
