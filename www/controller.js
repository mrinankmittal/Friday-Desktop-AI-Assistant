$(document).ready(function () {
    
    // Display Speak Message
    eel.expose(DisplayMessage)
    function DisplayMessage(message) {
        const siriMessage = document.getElementById("siri-message");

        if (siriMessage) {
            siriMessage.textContent = String(message);
        }

        // A new line means a new utterance, so give the orb a fresh cadence.
        if (window.FridayOrb) {
            window.FridayOrb.reseed();
            window.FridayOrb.pulse(0.6);
        }

        // Eel requires an explicit serializable return value. Returning
        // undefined causes its Python message handler to raise KeyError.
        return null;
    }

    // Called when the voice session ends. The orb never leaves the screen, so
    // this only has to settle it back to idle.
    eel.expose(ShowHood)
    function ShowHood() {
        if (window.FridayOrb) {
            window.FridayOrb.setState("idle");
        }
        const modal = document.getElementById("confirmModal");
        if (modal) {
            modal.hidden = true;
        }
        return null;
    }

    eel.expose(ShowConfirm)
    function ShowConfirm(prompt) {
        const modal = document.getElementById("confirmModal");
        const text = document.getElementById("confirmPrompt");
        if (!modal || !text) {
            return null;
        }
        text.textContent = String(prompt || "Send this?");
        modal.hidden = false;
        return null;
    }

    eel.expose(HideConfirm)
    function HideConfirm() {
        const modal = document.getElementById("confirmModal");
        if (modal) {
            modal.hidden = true;
        }
        return null;
    }

    eel.expose(senderText);

    function senderText(message) {
        appendMessage(message, "sender_message", "justify-content-end");
    }

    eel.expose(receiverText);

    function receiverText(message) {
        appendMessage(message, "receiver_message", "justify-content-start");
    }

    function appendMessage(message, messageClass, alignmentClass) {
        const text = String(message ?? "").trim();
        if (!text) return;

        const chatBox = document.getElementById("chat-canvas-body");
        if (!chatBox) return;

        const row = document.createElement("div");
        row.className = `row ${alignmentClass} mb-4`;

        const wrapper = document.createElement("div");
        wrapper.className = "width-size";

        const bubble = document.createElement("div");
        bubble.className = messageClass;
        bubble.textContent = text; // safer than innerHTML

        wrapper.appendChild(bubble);
        row.appendChild(wrapper);
        chatBox.appendChild(row);

        chatBox.scrollTop = chatBox.scrollHeight;
    }

    const settingsCanvas = document.getElementById("settingsCanvas");
    if (settingsCanvas) {
        settingsCanvas.addEventListener("shown.bs.offcanvas", function () {
            refreshSettings();
        });
    }

    const logCanvas = document.getElementById("logCanvas");
    if (logCanvas) {
        logCanvas.addEventListener("shown.bs.offcanvas", function () {
            refreshEventLog();
        });
    }

    async function refreshSettings() {
        const memoryList = document.getElementById("memory-list");
        const documentList = document.getElementById("document-list");
        const noteList = document.getElementById("note-list");
        const reminderList = document.getElementById("reminder-list");
        const integrationList = document.getElementById("integration-list");
        const allowList = document.getElementById("allow-list");
        const auditList = document.getElementById("audit-list");
        if (!memoryList || !documentList) {
            return;
        }

        try {
            const memories = await eel.memory_list()();
            renderMemoryRows(memoryList, memories, "No memories yet.");
            const documents = await eel.document_list()();
            renderDocumentRows(documentList, documents, "No documents indexed yet.");
            if (noteList) {
                const notes = await eel.note_list()();
                renderNoteRows(noteList, notes, "No notes yet.");
            }
            if (reminderList) {
                const reminders = await eel.reminder_list()();
                renderReminderRows(reminderList, reminders, "No reminders yet.");
            }
            if (integrationList) {
                const integrations = await eel.integration_list()();
                renderIntegrationRows(integrationList, integrations, "No integrations connected.");
            }
            if (allowList) {
                const folders = await eel.allow_path_list()();
                renderAllowRows(allowList, folders, "No folders allowed.");
            }
            if (auditList) {
                const rows = await eel.audit_list()();
                renderAuditRows(auditList, rows, "No recent activity.");
            }
        } catch (error) {
            console.error("Unable to load memories:", error);
            memoryList.textContent = "Could not load memories.";
        }
    }

    function renderMemoryRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";

            const body = document.createElement("div");
            body.className = "settings-row-body";

            const meta = document.createElement("div");
            meta.className = "settings-row-meta";
            meta.textContent = "Memory " + String(item.id);

            const content = document.createElement("div");
            content.className = "settings-row-text";
            content.textContent = String(item.content || "");

            body.appendChild(meta);
            body.appendChild(content);

            const button = document.createElement("button");
            button.type = "button";
            button.className = "settings-delete";
            button.textContent = "Delete";
            button.addEventListener("click", async function () {
                try {
                    await eel.memory_delete(item.id)();
                    refreshSettings();
                } catch (error) {
                    console.error("Unable to delete memory:", error);
                }
            });

            row.appendChild(body);
            row.appendChild(button);
            container.appendChild(row);
        });
    }

    function renderDocumentRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";

            const body = document.createElement("div");
            body.className = "settings-row-body";

            const meta = document.createElement("div");
            meta.className = "settings-row-meta";
            meta.textContent = String(item.title || "document") + " · " + String(item.chunks || 0) + " chunks";

            const content = document.createElement("div");
            content.className = "settings-row-text";
            content.textContent = String(item.path || "");

            body.appendChild(meta);
            body.appendChild(content);

            const button = document.createElement("button");
            button.type = "button";
            button.className = "settings-delete";
            button.textContent = "Delete";
            button.addEventListener("click", async function () {
                try {
                    await eel.document_delete(item.id)();
                    refreshSettings();
                } catch (error) {
                    console.error("Unable to delete document:", error);
                }
            });

            row.appendChild(body);
            row.appendChild(button);
            container.appendChild(row);
        });
    }

    function renderNoteRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";

            const body = document.createElement("div");
            body.className = "settings-row-body";

            const meta = document.createElement("div");
            meta.className = "settings-row-meta";
            meta.textContent = "Note " + String(item.id);

            const content = document.createElement("div");
            content.className = "settings-row-text";
            content.textContent = String(item.content || "");

            body.appendChild(meta);
            body.appendChild(content);

            const button = document.createElement("button");
            button.type = "button";
            button.className = "settings-delete";
            button.textContent = "Delete";
            button.addEventListener("click", async function () {
                try {
                    await eel.note_delete(item.id)();
                    refreshSettings();
                } catch (error) {
                    console.error("Unable to delete note:", error);
                }
            });

            row.appendChild(body);
            row.appendChild(button);
            container.appendChild(row);
        });
    }

    function renderReminderRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";

            const body = document.createElement("div");
            body.className = "settings-row-body";

            const meta = document.createElement("div");
            meta.className = "settings-row-meta";
            meta.textContent = "Reminder " + String(item.id) + (item.due_at ? " · " + String(item.due_at) : "");

            const content = document.createElement("div");
            content.className = "settings-row-text";
            content.textContent = String(item.content || "");

            body.appendChild(meta);
            body.appendChild(content);

            const button = document.createElement("button");
            button.type = "button";
            button.className = "settings-delete";
            button.textContent = "Delete";
            button.addEventListener("click", async function () {
                try {
                    await eel.reminder_delete(item.id)();
                    refreshSettings();
                } catch (error) {
                    console.error("Unable to delete reminder:", error);
                }
            });

            row.appendChild(body);
            row.appendChild(button);
            container.appendChild(row);
        });
    }

    function renderIntegrationRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";

            const body = document.createElement("div");
            body.className = "settings-row-body";

            const meta = document.createElement("div");
            meta.className = "settings-row-meta";
            const connected = Boolean(item.connected);
            const label = item.label ? " · " + String(item.label) : "";
            meta.textContent = String(item.provider || "integration") + label;

            const content = document.createElement("div");
            content.className = "settings-row-text";
            content.textContent = connected ? "Connected" : "Not connected";

            body.appendChild(meta);
            body.appendChild(content);
            row.appendChild(body);

            if (connected) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "settings-delete";
                button.textContent = "Disconnect";
                button.addEventListener("click", async function () {
                    try {
                        await eel.integration_disconnect(item.provider)();
                        refreshSettings();
                    } catch (error) {
                        console.error("Unable to disconnect integration:", error);
                    }
                });
                row.appendChild(button);
            }

            container.appendChild(row);
        });
    }

    function renderAllowRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";
            const body = document.createElement("div");
            body.className = "settings-row-body";
            const content = document.createElement("div");
            content.className = "settings-row-text";
            content.textContent = String(item.path || item || "");
            body.appendChild(content);
            row.appendChild(body);
            container.appendChild(row);
        });
    }

    function renderAuditRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";
            const body = document.createElement("div");
            body.className = "settings-row-body";
            const meta = document.createElement("div");
            meta.className = "settings-row-meta";
            const okLabel = item.ok ? "ok" : "blocked";
            meta.textContent = String(item.tool || item.event || "event") + " · " + okLabel;
            const content = document.createElement("div");
            content.className = "settings-row-text";
            content.textContent = String(item.created_at || "") + (item.error ? " · " + String(item.error) : "");
            body.appendChild(meta);
            body.appendChild(content);
            row.appendChild(body);
            container.appendChild(row);
        });
    }

    async function refreshEventLog() {
        const list = document.getElementById("event-log-list");
        if (!list) {
            return;
        }
        try {
            const rows = await eel.event_log_list()();
            renderEventLogRows(list, rows, "No task traces yet. Run a command first.");
        } catch (error) {
            console.error("Unable to load event log:", error);
            list.textContent = "Could not load event log.";
        }
    }

    function renderEventLogRows(container, items, emptyText) {
        container.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "settings-empty";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        items.forEach(function (item) {
            const row = document.createElement("div");
            row.className = "settings-row";
            const body = document.createElement("div");
            body.className = "settings-row-body";
            const meta = document.createElement("div");
            meta.className = "settings-row-meta";
            const parts = [
                String(item.event || "event"),
                item.intent ? String(item.intent) : "",
                item.tool ? String(item.tool) : "",
                item.status ? String(item.status) : "",
            ].filter(Boolean);
            meta.textContent = parts.join(" · ");
            const taskId = document.createElement("div");
            taskId.className = "log-task-id";
            taskId.textContent = String(item.task_id || "");
            const content = document.createElement("div");
            content.className = "settings-row-text";
            const detail = [];
            if (item.request) {
                detail.push(String(item.request));
            }
            if (item.observation) {
                detail.push(String(item.observation));
            }
            if (item.duration_ms != null && item.duration_ms !== "") {
                detail.push(String(item.duration_ms) + " ms");
            }
            if (item.error) {
                detail.push(String(item.error));
            }
            content.textContent = detail.join(" · ");
            body.appendChild(meta);
            if (item.task_id) {
                body.appendChild(taskId);
            }
            body.appendChild(content);
            row.appendChild(body);
            container.appendChild(row);
        });
    }

    const confirmSendBtn = document.getElementById("confirmSendBtn");
    const confirmCancelBtn = document.getElementById("confirmCancelBtn");
    if (confirmSendBtn) {
        confirmSendBtn.addEventListener("click", async function () {
            try {
                await eel.confirm_send(true)();
            } catch (error) {
                console.error("Unable to confirm send:", error);
            }
        });
    }
    if (confirmCancelBtn) {
        confirmCancelBtn.addEventListener("click", async function () {
            try {
                await eel.confirm_send(false)();
            } catch (error) {
                console.error("Unable to cancel send:", error);
            }
        });
    }
});
