/* Agent Orchestra Dashboard - Client-side JavaScript */

(function () {
    "use strict";

    const API = "";
    let wsStatus = null;
    let wsLogs = null;
    let historyOffset = 0;
    const PAGE_SIZE = 20;

    // ── Helpers ─────────────────────────────────────────────────────────

    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    async function api(path) {
        const res = await fetch(API + path);
        return res.json();
    }

    async function apiPost(path) {
        const res = await fetch(API + path, { method: "POST" });
        return res.json();
    }

    function formatTime(ts) {
        if (!ts) return "-";
        try {
            const d = new Date(ts);
            return d.toLocaleString();
        } catch {
            return ts;
        }
    }

    function shortTime(ts) {
        if (!ts) return "";
        try {
            const d = new Date(ts);
            return d.toLocaleTimeString();
        } catch {
            return ts;
        }
    }

    function statusBadge(status) {
        const cls = status === "success" ? "badge-success" : status === "failed" ? "badge-danger" : "badge-gray";
        return `<span class="badge ${cls}">${status}</span>`;
    }

    function formatCost(cost) {
        if (!cost || cost === 0) return "$0.00";
        if (cost < 0.01) return "$" + cost.toFixed(4);
        return "$" + cost.toFixed(2);
    }

    // ── Tab Navigation ──────────────────────────────────────────────────

    $$(".tab").forEach(tab => {
        tab.addEventListener("click", () => {
            $$(".tab").forEach(t => t.classList.remove("active"));
            $$(".panel").forEach(p => p.classList.remove("active"));
            tab.classList.add("active");
            const panel = $("#panel-" + tab.dataset.panel);
            if (panel) panel.classList.add("active");
            loadPanelData(tab.dataset.panel);
        });
    });

    function loadPanelData(panel) {
        switch (panel) {
            case "overview": loadOverview(); break;
            case "agents": loadAgents(); break;
            case "history": loadHistory(); break;
            case "logs": loadLogs(); break;
            case "control": loadControl(); break;
            case "costs": loadCosts(); break;
            case "teams": loadTeams(); break;
        }
    }

    // ── Overview Panel ──────────────────────────────────────────────────

    async function loadOverview() {
        const [stats, execData, status] = await Promise.all([
            api("/api/stats"),
            api("/api/executions?limit=5"),
            api("/api/status"),
        ]);

        $("#stat-total-exec").textContent = stats.total_executions;
        $("#stat-total-agents").textContent = stats.total_agents_run;
        $("#stat-success-rate").textContent = stats.success_rate + "%";
        $("#stat-total-cost").textContent = formatCost(stats.total_cost);

        // Recent executions table
        const execs = execData.executions || [];
        if (execs.length === 0) {
            $("#recent-executions").innerHTML = '<p class="muted">No executions yet</p>';
        } else {
            let html = `<table>
                <thead><tr><th>Time</th><th>Mode</th><th>Agents</th><th>Success</th><th>Failed</th><th>Cost</th></tr></thead>
                <tbody>`;
            for (const e of execs) {
                html += `<tr>
                    <td>${formatTime(e.timestamp)}</td>
                    <td><span class="badge badge-info">${e.mode}</span></td>
                    <td>${e.agent_count}</td>
                    <td class="text-success">${e.success_count}</td>
                    <td class="${e.fail_count > 0 ? 'text-danger' : ''}">${e.fail_count}</td>
                    <td>${formatCost(e.estimated_cost)}</td>
                </tr>`;
            }
            html += "</tbody></table>";
            $("#recent-executions").innerHTML = html;
        }

        // Orchestrator status
        const orch = status.orchestrator || {};
        const running = orch.running;
        let statusHtml = `<p>Status: ${running
            ? '<span class="badge badge-success">Running</span>'
            : '<span class="badge badge-gray">Stopped</span>'}</p>`;
        if (running) {
            statusHtml += `<p class="muted">PID: ${orch.pid} | Mode: ${orch.mode} | Client: ${orch.client_mode} | Started: ${formatTime(orch.started_at)}</p>`;
        }
        if (stats.last_execution) {
            statusHtml += `<p class="muted">Last execution: ${formatTime(stats.last_execution)}</p>`;
        }
        $("#orch-status").innerHTML = statusHtml;
    }

    // ── Agents Panel ────────────────────────────────────────────────────

    async function loadAgents() {
        const agents = await api("/api/agents");
        if (!agents || agents.length === 0) {
            $("#agents-table").innerHTML = '<p class="muted">No agent data</p>';
            return;
        }
        let html = `<table>
            <thead><tr><th>Agent</th><th>Total Runs</th><th>Successes</th><th>Failures</th><th>Last Status</th><th>Last Run</th><th>Avg Output</th></tr></thead>
            <tbody>`;
        for (const a of agents) {
            const rate = a.total_runs > 0 ? ((a.successes / a.total_runs) * 100).toFixed(0) : 0;
            html += `<tr>
                <td><strong>${a.agent}</strong></td>
                <td>${a.total_runs}</td>
                <td class="text-success">${a.successes}</td>
                <td class="${a.failures > 0 ? 'text-danger' : ''}">${a.failures}</td>
                <td>${statusBadge(a.last_status || "unknown")}</td>
                <td>${formatTime(a.last_run)}</td>
                <td>${Math.round(a.avg_output_len)} chars</td>
            </tr>`;
        }
        html += "</tbody></table>";
        $("#agents-table").innerHTML = html;
    }

    // ── History Panel ───────────────────────────────────────────────────

    async function loadHistory() {
        const data = await api(`/api/executions?limit=${PAGE_SIZE}&offset=${historyOffset}`);
        const execs = data.executions || [];
        const total = data.total || 0;
        const page = Math.floor(historyOffset / PAGE_SIZE) + 1;
        const totalPages = Math.ceil(total / PAGE_SIZE);

        $("#history-info").textContent = `Page ${page} of ${totalPages} (${total} total)`;
        $("#history-prev").disabled = historyOffset === 0;
        $("#history-next").disabled = historyOffset + PAGE_SIZE >= total;

        if (execs.length === 0) {
            $("#history-table").innerHTML = '<p class="muted">No executions</p>';
            return;
        }

        let html = `<table>
            <thead><tr><th>#</th><th>Time</th><th>Mode</th><th>Client</th><th>Agents</th><th>Success</th><th>Failed</th><th>Cost</th></tr></thead>
            <tbody>`;
        for (const e of execs) {
            html += `<tr class="clickable" data-exec-id="${e.id}">
                <td>${e.id}</td>
                <td>${formatTime(e.timestamp)}</td>
                <td><span class="badge badge-info">${e.mode}</span></td>
                <td>${e.global_client_mode || "-"}</td>
                <td>${e.agent_count}</td>
                <td class="text-success">${e.success_count}</td>
                <td class="${e.fail_count > 0 ? 'text-danger' : ''}">${e.fail_count}</td>
                <td>${formatCost(e.estimated_cost)}</td>
            </tr>`;
        }
        html += "</tbody></table>";
        $("#history-table").innerHTML = html;

        // Add click handlers for detail view
        $$("#history-table tr.clickable").forEach(row => {
            row.addEventListener("click", () => showExecDetail(row.dataset.execId));
        });
    }

    $("#history-prev").addEventListener("click", () => {
        historyOffset = Math.max(0, historyOffset - PAGE_SIZE);
        loadHistory();
    });

    $("#history-next").addEventListener("click", () => {
        historyOffset += PAGE_SIZE;
        loadHistory();
    });

    async function showExecDetail(id) {
        const modal = $("#exec-detail-modal");
        modal.classList.remove("hidden");
        $("#exec-detail-body").innerHTML = '<p class="muted">Loading...</p>';

        const data = await api(`/api/executions/${id}`);
        if (data.error) {
            $("#exec-detail-body").innerHTML = `<p class="text-danger">${data.error}</p>`;
            return;
        }

        let html = `<p>Time: <strong>${formatTime(data.timestamp)}</strong></p>
            <p>Mode: <span class="badge badge-info">${data.mode}</span>
               Client: <span class="badge badge-gray">${data.global_client_mode || "-"}</span>
               Cost: <strong>${formatCost(data.estimated_cost)}</strong></p>
            <hr style="border-color: var(--border); margin: 1rem 0;">`;

        const results = data.results || [];
        for (const r of results) {
            html += `<div style="margin-bottom: 1rem;">
                <p><strong>${r.agent}</strong> ${statusBadge(r.status)}
                   <span class="muted" style="margin-left: 0.5rem;">${r.client_mode || ""}</span>
                   <span class="muted" style="margin-left: 0.5rem;">${formatTime(r.timestamp)}</span></p>`;
            if (r.output) {
                html += `<div class="agent-output">${escapeHtml(r.output)}</div>`;
            }
            if (r.error) {
                html += `<p class="text-danger" style="margin-top: 0.25rem;">${escapeHtml(r.error)}</p>`;
            }
            html += `</div>`;
        }

        $("#exec-detail-title").textContent = `Execution #${id}`;
        $("#exec-detail-body").innerHTML = html;
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    $("#close-modal").addEventListener("click", () => {
        $("#exec-detail-modal").classList.add("hidden");
    });

    // Close modal on backdrop click
    $("#exec-detail-modal").addEventListener("click", (e) => {
        if (e.target === $("#exec-detail-modal")) {
            $("#exec-detail-modal").classList.add("hidden");
        }
    });

    // ── Logs Panel ──────────────────────────────────────────────────────

    async function loadLogs() {
        const logs = await api("/api/logs?limit=100");
        const container = $("#log-container");
        container.innerHTML = "";
        if (Array.isArray(logs)) {
            // Reverse so oldest first
            for (const entry of logs.reverse()) {
                appendLogEntry(entry);
            }
            container.scrollTop = container.scrollHeight;
        }
    }

    function appendLogEntry(entry) {
        const filter = $("#log-level-filter").value;
        if (filter && entry.level !== filter) return;

        const container = $("#log-container");
        const div = document.createElement("div");
        div.className = "log-entry";
        div.innerHTML = `<span class="log-time">${shortTime(entry.timestamp)}</span><span class="log-level ${entry.level}">[${entry.level.toUpperCase()}]</span>${entry.source ? `<span class="log-source">(${entry.source})</span>` : ""}<span>${escapeHtml(entry.message)}</span>`;
        container.appendChild(div);

        // Auto-scroll
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 50) {
            container.scrollTop = container.scrollHeight;
        }
    }

    $("#clear-logs").addEventListener("click", () => {
        $("#log-container").innerHTML = '<div class="muted">Logs cleared</div>';
    });

    $("#log-level-filter").addEventListener("change", loadLogs);

    // ── Control Panel ───────────────────────────────────────────────────

    async function loadControl() {
        const [status, cfg] = await Promise.all([
            api("/api/status"),
            api("/api/config"),
        ]);

        const orch = status.orchestrator || {};
        updateControlButtons(orch.running);

        let statusHtml = orch.running
            ? `<p><span class="badge badge-success">Running</span> PID: ${orch.pid} | Mode: ${orch.mode} | Client: ${orch.client_mode}</p>
               <p class="muted">Started: ${formatTime(orch.started_at)}</p>`
            : '<p><span class="badge badge-gray">Stopped</span></p>';
        $("#control-status").innerHTML = statusHtml;

        $("#config-display").textContent = JSON.stringify(cfg, null, 2);
    }

    function updateControlButtons(running) {
        $("#btn-start").disabled = running;
        $("#btn-stop").disabled = !running;
    }

    $("#btn-start").addEventListener("click", async () => {
        const mode = $("#ctrl-mode").value;
        const clientMode = $("#ctrl-client-mode").value;
        $("#btn-start").disabled = true;
        const result = await apiPost(`/api/orchestrator/start?mode=${mode}&client_mode=${clientMode}`);
        if (result.error) {
            alert(result.error);
        }
        loadControl();
    });

    $("#btn-stop").addEventListener("click", async () => {
        $("#btn-stop").disabled = true;
        const result = await apiPost("/api/orchestrator/stop");
        if (result.error) {
            alert(result.error);
        }
        loadControl();
    });

    // ── Costs Panel ─────────────────────────────────────────────────────

    async function loadCosts() {
        const data = await api("/api/costs");

        $("#cost-total").textContent = formatCost(data.total_cost);

        // By mode
        const modes = data.by_mode || {};
        if (Object.keys(modes).length === 0) {
            $("#cost-by-mode").innerHTML = '<p class="muted">No data</p>';
        } else {
            let html = "<table><thead><tr><th>Mode</th><th>Cost</th></tr></thead><tbody>";
            for (const [mode, cost] of Object.entries(modes)) {
                html += `<tr><td>${mode}</td><td>${formatCost(cost)}</td></tr>`;
            }
            html += "</tbody></table>";
            $("#cost-by-mode").innerHTML = html;
        }

        // By agent
        const agents = data.by_agent || {};
        if (Object.keys(agents).length === 0) {
            $("#cost-by-agent").innerHTML = '<p class="muted">No data</p>';
        } else {
            let html = "<table><thead><tr><th>Agent</th><th>Cost</th></tr></thead><tbody>";
            for (const [agent, cost] of Object.entries(agents)) {
                html += `<tr><td>${agent}</td><td>${formatCost(cost)}</td></tr>`;
            }
            html += "</tbody></table>";
            $("#cost-by-agent").innerHTML = html;
        }

        // By date
        const dates = data.by_date || {};
        if (Object.keys(dates).length === 0) {
            $("#cost-by-date").innerHTML = '<p class="muted">No data</p>';
        } else {
            let html = "<table><thead><tr><th>Date</th><th>Cost</th></tr></thead><tbody>";
            for (const [date, cost] of Object.entries(dates)) {
                html += `<tr><td>${date}</td><td>${formatCost(cost)}</td></tr>`;
            }
            html += "</tbody></table>";
            $("#cost-by-date").innerHTML = html;
        }
    }

    // ── Teams Panel ─────────────────────────────────────────────────────

    async function loadTeams() {
        const data = await api("/api/teams?limit=50");
        const sessions = data.sessions || [];
        const total = data.total || 0;

        $("#teams-total").textContent = total;

        // Count active (running) sessions
        const active = sessions.filter(s => s.status === "running").length;
        $("#teams-active").textContent = active;

        if (sessions.length === 0) {
            $("#teams-table").innerHTML = '<p class="muted">No team sessions yet. Launch one with ./scripts/launch-team.sh</p>';
            return;
        }

        let html = `<table>
            <thead><tr><th>#</th><th>Team</th><th>Status</th><th>Teammates</th><th>Success</th><th>Failed</th><th>Started</th></tr></thead>
            <tbody>`;
        for (const s of sessions) {
            const statusCls = s.status === "completed" ? "badge-success"
                : s.status === "running" ? "badge-info"
                : s.status === "partial" ? "badge-warning"
                : "badge-gray";
            html += `<tr class="clickable" data-team-id="${s.id}">
                <td>${s.id}</td>
                <td><strong>${s.team_name}</strong></td>
                <td><span class="badge ${statusCls}">${s.status}</span></td>
                <td>${s.teammate_count}</td>
                <td class="text-success">${s.success_count}</td>
                <td class="${s.fail_count > 0 ? 'text-danger' : ''}">${s.fail_count}</td>
                <td>${formatTime(s.started_at)}</td>
            </tr>`;
        }
        html += "</tbody></table>";
        $("#teams-table").innerHTML = html;

        // Click handlers for detail
        $$("#teams-table tr.clickable").forEach(row => {
            row.addEventListener("click", () => showTeamDetail(row.dataset.teamId));
        });
    }

    async function showTeamDetail(id) {
        const modal = $("#team-detail-modal");
        modal.classList.remove("hidden");
        $("#team-detail-body").innerHTML = '<p class="muted">Loading...</p>';

        const data = await api(`/api/teams/${id}`);
        if (data.error) {
            $("#team-detail-body").innerHTML = `<p class="text-danger">${data.error}</p>`;
            return;
        }

        const statusCls = data.status === "completed" ? "badge-success"
            : data.status === "running" ? "badge-info"
            : data.status === "partial" ? "badge-warning"
            : "badge-gray";

        let html = `<p>Team: <strong>${data.team_name}</strong>
            <span class="badge ${statusCls}">${data.status}</span></p>
            <p class="muted">Started: ${formatTime(data.started_at)}${data.completed_at ? ' | Completed: ' + formatTime(data.completed_at) : ''}</p>`;

        if (data.task_description) {
            html += `<p style="margin-top: 0.5rem;">Task: ${escapeHtml(data.task_description)}</p>`;
        }

        html += `<hr style="border-color: var(--border); margin: 1rem 0;">`;

        const tasks = data.tasks || [];
        for (const t of tasks) {
            html += `<div style="margin-bottom: 1rem;">
                <p><strong>${t.teammate}</strong> ${statusBadge(t.status)}
                   <span class="muted" style="margin-left: 0.5rem;">${formatTime(t.started_at)}</span></p>`;
            if (t.role) {
                html += `<p class="muted" style="font-size: 0.8rem; margin-top: 0.25rem;">${escapeHtml(t.role)}</p>`;
            }
            if (t.output) {
                html += `<div class="agent-output">${escapeHtml(t.output)}</div>`;
            }
            if (t.error) {
                html += `<p class="text-danger" style="margin-top: 0.25rem;">${escapeHtml(t.error)}</p>`;
            }
            html += `</div>`;
        }

        $("#team-detail-title").textContent = `Team Session #${id} — ${data.team_name}`;
        $("#team-detail-body").innerHTML = html;
    }

    $("#close-team-modal").addEventListener("click", () => {
        $("#team-detail-modal").classList.add("hidden");
    });

    $("#team-detail-modal").addEventListener("click", (e) => {
        if (e.target === $("#team-detail-modal")) {
            $("#team-detail-modal").classList.add("hidden");
        }
    });

    // ── WebSocket ───────────────────────────────────────────────────────

    function connectWebSockets() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const base = `${proto}//${location.host}`;

        // Status WebSocket
        wsStatus = new WebSocket(`${base}/ws/status`);
        wsStatus.onopen = () => {
            $("#connection-status").className = "badge badge-success";
            $("#connection-status").textContent = "Connected";
        };
        wsStatus.onclose = () => {
            $("#connection-status").className = "badge badge-gray";
            $("#connection-status").textContent = "Disconnected";
            setTimeout(connectWebSockets, 3000);
        };
        wsStatus.onerror = () => { wsStatus.close(); };
        wsStatus.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.type === "new_execution") {
                    // Refresh overview if visible
                    const activePanel = document.querySelector(".panel.active");
                    if (activePanel && activePanel.id === "panel-overview") {
                        loadOverview();
                    }
                }
            } catch {}
        };

        // Logs WebSocket
        wsLogs = new WebSocket(`${base}/ws/logs`);
        wsLogs.onmessage = (e) => {
            try {
                const entry = JSON.parse(e.data);
                appendLogEntry(entry);
            } catch {}
        };

        // Teams WebSocket
        const wsTeams = new WebSocket(`${base}/ws/teams`);
        wsTeams.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.type === "new_team_session") {
                    const activePanel = document.querySelector(".panel.active");
                    if (activePanel && activePanel.id === "panel-teams") {
                        loadTeams();
                    }
                }
            } catch {}
        };
    }

    // ── Clock ───────────────────────────────────────────────────────────

    function updateClock() {
        const now = new Date();
        $("#clock").textContent = now.toLocaleTimeString();
    }
    setInterval(updateClock, 1000);
    updateClock();

    // ── Init ────────────────────────────────────────────────────────────

    loadOverview();
    connectWebSockets();

})();
