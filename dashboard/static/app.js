/* Agent Orchestra Dashboard - Client-side JavaScript */

(function () {
    "use strict";

    const API = "";
    let wsStatus = null;
    let wsLogs = null;
    let historyOffset = 0;
    const PAGE_SIZE = 20;

    // Track current running session for progress terminal
    let activeSessionId = null;

    // ── Helpers ─────────────────────────────────────────────────────────

    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    async function api(path) {
        const res = await fetch(API + path);
        return res.json();
    }

    async function apiPost(path, body) {
        const opts = { method: "POST" };
        if (body) {
            opts.headers = { "Content-Type": "application/json" };
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(API + path, opts);
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
        const cls = status === "success" || status === "completed" || status === "merged" ? "badge-success"
            : status === "failed" ? "badge-danger"
            : status === "running" ? "badge-info"
            : status === "cancelled" || status === "discarded" ? "badge-warning"
            : "badge-gray";
        return `<span class="badge ${cls}">${status}</span>`;
    }

    function formatCost(cost) {
        if (!cost || cost === 0) return "$0.00";
        if (cost < 0.01) return "$" + cost.toFixed(4);
        return "$" + cost.toFixed(2);
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
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
            case "teams": loadTeams(); loadTeamTemplates(); break;
            case "gm": loadGM(); loadGMTemplates(); break;
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

    // ── Teams Panel — Templates ─────────────────────────────────────────

    let teamTemplatesLoaded = false;

    async function loadTeamTemplates() {
        if (teamTemplatesLoaded) return;
        try {
            const templates = await api("/api/teams/templates");
            const select = $("#launch-team-select");
            select.innerHTML = '<option value="">-- Select a team --</option>';
            if (Array.isArray(templates)) {
                for (const t of templates) {
                    const opt = document.createElement("option");
                    opt.value = t.name;
                    opt.textContent = `${t.name} — ${t.description} (${t.teammate_count} teammates)`;
                    select.appendChild(opt);
                }
            }
            teamTemplatesLoaded = true;
        } catch {
            $("#launch-team-select").innerHTML = '<option value="">Failed to load templates</option>';
        }
    }

    // ── Teams Panel — Launch ────────────────────────────────────────────

    $("#btn-launch-team").addEventListener("click", async () => {
        const teamName = $("#launch-team-select").value;
        const taskDesc = $("#launch-task").value.trim();
        const repoPath = $("#launch-repo-path").value.trim() || undefined;

        if (!teamName) {
            $("#launch-status").textContent = "Please select a team template.";
            return;
        }
        if (!taskDesc) {
            $("#launch-status").textContent = "Please describe the task.";
            return;
        }

        $("#btn-launch-team").disabled = true;
        $("#launch-status").textContent = "Launching...";

        const result = await apiPost("/api/teams/launch", {
            team_name: teamName,
            task_description: taskDesc,
            repo_path: repoPath,
        });

        if (result.error) {
            $("#launch-status").textContent = "Error: " + result.error;
            $("#btn-launch-team").disabled = false;
            return;
        }

        // Show progress terminal
        activeSessionId = result.session_id;
        $("#progress-session-id").textContent = result.session_id;
        $("#progress-terminal").innerHTML = '<div class="term-line term-info">Session started. Waiting for output...</div>';
        $("#progress-terminal-card").classList.remove("hidden");
        $("#btn-cancel-session").disabled = false;

        $("#launch-status").textContent = "Launched! Session: " + result.session_id;
        $("#btn-launch-team").disabled = false;
        $("#launch-task").value = "";

        // Refresh table
        loadTeams();
    });

    // ── Teams Panel — Cancel ────────────────────────────────────────────

    $("#btn-cancel-session").addEventListener("click", async () => {
        if (!activeSessionId) return;
        if (!confirm("Cancel running session " + activeSessionId + "?")) return;

        $("#btn-cancel-session").disabled = true;
        const result = await apiPost(`/api/teams/${activeSessionId}/cancel`);
        if (result.error) {
            alert("Cancel failed: " + result.error);
            $("#btn-cancel-session").disabled = false;
        } else {
            appendTerminalLine("Session cancelled.", "term-warn");
            activeSessionId = null;
            loadTeams();
        }
    });

    // ── Teams Panel — Progress Terminal ─────────────────────────────────

    function appendTerminalLine(text, cls) {
        const terminal = $("#progress-terminal");
        if (!terminal) return;
        const div = document.createElement("div");
        div.className = "term-line " + (cls || "");
        div.textContent = text;
        terminal.appendChild(div);
        terminal.scrollTop = terminal.scrollHeight;
    }

    function handleTeamProgress(data) {
        if (data.type !== "team_progress") return;

        // Only render for the active session's terminal
        if (data.session_id !== activeSessionId) {
            // Still refresh table for any status changes
            if (data.event === "completed" || data.event === "cancelled") {
                loadTeams();
            }
            return;
        }

        switch (data.event) {
            case "stdout":
                appendTerminalLine(data.data, "term-stdout");
                break;
            case "stderr":
                appendTerminalLine(data.data, "term-stderr");
                break;
            case "completed":
                appendTerminalLine(
                    `Session ${data.status} (exit code: ${data.exit_code})`,
                    data.status === "completed" ? "term-info" : "term-stderr"
                );
                $("#btn-cancel-session").disabled = true;
                activeSessionId = null;
                loadTeams();
                break;
            case "cancelled":
                appendTerminalLine("Session cancelled.", "term-warn");
                $("#btn-cancel-session").disabled = true;
                activeSessionId = null;
                loadTeams();
                break;
        }
    }

    // ── Teams Panel — Sessions Table ────────────────────────────────────

    async function loadTeams() {
        const data = await api("/api/teams?limit=50");
        const sessions = data.sessions || [];
        const total = data.total || 0;

        $("#teams-total").textContent = total;

        // Count active (running) sessions
        const active = sessions.filter(s => s.status === "running").length;
        $("#teams-active").textContent = active;

        if (sessions.length === 0) {
            $("#teams-table").innerHTML = '<p class="muted">No team sessions yet. Use the form above to launch one.</p>';
            return;
        }

        let html = `<table>
            <thead><tr><th>#</th><th>Team</th><th>Task</th><th>Status</th><th>Started</th><th>Actions</th></tr></thead>
            <tbody>`;
        for (const s of sessions) {
            const statusCls = s.status === "completed" || s.status === "merged" ? "badge-success"
                : s.status === "running" ? "badge-info"
                : s.status === "cancelled" || s.status === "discarded" ? "badge-warning"
                : s.status === "failed" ? "badge-danger"
                : "badge-gray";
            const taskSnippet = s.task_description
                ? escapeHtml(s.task_description.length > 60 ? s.task_description.slice(0, 60) + "..." : s.task_description)
                : '<span class="muted">-</span>';

            // Build action buttons based on status
            let actions = '';
            if (s.session_id) {
                if (s.status === "completed" || s.status === "failed") {
                    actions = `<span class="actions-cell">
                        <button class="btn btn-sm" onclick="window._teamAction('diff','${escapeHtml(s.session_id)}')">Diff</button>
                        <button class="btn btn-sm btn-success" onclick="window._teamAction('merge','${escapeHtml(s.session_id)}')">Merge</button>
                        <button class="btn btn-sm btn-danger" onclick="window._teamAction('discard','${escapeHtml(s.session_id)}')">Discard</button>
                    </span>`;
                } else if (s.status === "running") {
                    actions = `<span class="actions-cell">
                        <button class="btn btn-sm btn-danger" onclick="window._teamAction('cancel','${escapeHtml(s.session_id)}')">Cancel</button>
                    </span>`;
                } else {
                    actions = `<span class="muted">-</span>`;
                }
            }

            html += `<tr class="clickable" data-team-id="${s.id}">
                <td>${s.id}</td>
                <td><strong>${escapeHtml(s.team_name)}</strong></td>
                <td>${taskSnippet}</td>
                <td><span class="badge ${statusCls}">${s.status}</span></td>
                <td>${formatTime(s.started_at)}</td>
                <td>${actions}</td>
            </tr>`;
        }
        html += "</tbody></table>";
        $("#teams-table").innerHTML = html;

        // Click handlers for detail (but not on action buttons)
        $$("#teams-table tr.clickable").forEach(row => {
            row.addEventListener("click", (e) => {
                if (e.target.closest(".actions-cell")) return;
                showTeamDetail(row.dataset.teamId);
            });
        });
    }

    // Expose action handler globally for inline onclick
    window._teamAction = function (action, sessionId) {
        switch (action) {
            case "diff": showDiff(sessionId); break;
            case "merge": mergeTeam(sessionId); break;
            case "discard": discardTeam(sessionId); break;
            case "cancel": cancelTeam(sessionId); break;
        }
    };

    // ── Teams Panel — Diff Viewer ───────────────────────────────────────

    async function showDiff(sessionId) {
        const modal = $("#diff-modal");
        modal.classList.remove("hidden");
        $("#diff-viewer").innerHTML = '<p class="muted">Loading diff...</p>';
        $("#diff-stat").textContent = "";
        $("#diff-modal-title").textContent = "Diff — " + sessionId;

        const data = await api(`/api/teams/${sessionId}/diff`);
        if (data.error) {
            $("#diff-viewer").innerHTML = `<p class="text-danger">${escapeHtml(data.error)}</p>`;
            return;
        }

        if (data.stat) {
            $("#diff-stat").textContent = data.stat;
        }

        const diff = data.diff || "";
        if (!diff.trim()) {
            $("#diff-viewer").innerHTML = '<p class="muted">No changes detected.</p>';
            return;
        }

        // Render diff with color coding
        const lines = diff.split("\n");
        let html = "";
        for (const line of lines) {
            if (line.startsWith("+++") || line.startsWith("---")) {
                html += `<div class="diff-line diff-meta">${escapeHtml(line)}</div>`;
            } else if (line.startsWith("@@")) {
                html += `<div class="diff-line diff-hunk">${escapeHtml(line)}</div>`;
            } else if (line.startsWith("+")) {
                html += `<div class="diff-line diff-add">${escapeHtml(line)}</div>`;
            } else if (line.startsWith("-")) {
                html += `<div class="diff-line diff-del">${escapeHtml(line)}</div>`;
            } else {
                html += `<div class="diff-line">${escapeHtml(line)}</div>`;
            }
        }
        $("#diff-viewer").innerHTML = html;
    }

    $("#close-diff-modal").addEventListener("click", () => {
        $("#diff-modal").classList.add("hidden");
    });

    $("#diff-modal").addEventListener("click", (e) => {
        if (e.target === $("#diff-modal")) {
            $("#diff-modal").classList.add("hidden");
        }
    });

    // ── Teams Panel — Merge / Discard / Cancel ──────────────────────────

    async function mergeTeam(sessionId) {
        if (!confirm("Merge branch for session " + sessionId + " into main?")) return;
        const result = await apiPost(`/api/teams/${sessionId}/merge`);
        if (result.error) {
            alert("Merge failed: " + result.error);
        } else {
            loadTeams();
        }
    }

    async function discardTeam(sessionId) {
        if (!confirm("Discard worktree for session " + sessionId + "? This cannot be undone.")) return;
        const result = await apiPost(`/api/teams/${sessionId}/discard`);
        if (result.error) {
            alert("Discard failed: " + result.error);
        } else {
            loadTeams();
        }
    }

    async function cancelTeam(sessionId) {
        if (!confirm("Cancel running session " + sessionId + "?")) return;
        const result = await apiPost(`/api/teams/${sessionId}/cancel`);
        if (result.error) {
            alert("Cancel failed: " + result.error);
        } else {
            loadTeams();
        }
    }

    // ── Teams Panel — Detail Modal ──────────────────────────────────────

    async function showTeamDetail(id) {
        const modal = $("#team-detail-modal");
        modal.classList.remove("hidden");
        $("#team-detail-body").innerHTML = '<p class="muted">Loading...</p>';

        const data = await api(`/api/teams/${id}`);
        if (data.error) {
            $("#team-detail-body").innerHTML = `<p class="text-danger">${data.error}</p>`;
            return;
        }

        const statusCls = data.status === "completed" || data.status === "merged" ? "badge-success"
            : data.status === "running" ? "badge-info"
            : data.status === "cancelled" || data.status === "discarded" ? "badge-warning"
            : data.status === "failed" ? "badge-danger"
            : "badge-gray";

        let html = `<p>Team: <strong>${escapeHtml(data.team_name)}</strong>
            <span class="badge ${statusCls}">${data.status}</span></p>
            <p class="muted">Started: ${formatTime(data.started_at)}${data.completed_at ? ' | Completed: ' + formatTime(data.completed_at) : ''}</p>`;

        if (data.task_description) {
            html += `<p style="margin-top: 0.5rem;">Task: ${escapeHtml(data.task_description)}</p>`;
        }

        if (data.branch_name) {
            html += `<p class="muted" style="margin-top: 0.25rem;">Branch: <code>${escapeHtml(data.branch_name)}</code></p>`;
        }

        html += `<hr style="border-color: var(--border); margin: 1rem 0;">`;

        const tasks = data.tasks || [];
        for (const t of tasks) {
            html += `<div style="margin-bottom: 1rem;">
                <p><strong>${escapeHtml(t.teammate)}</strong> ${statusBadge(t.status)}
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

    // ── GM Panel — Templates ────────────────────────────────────────────

    let gmTemplatesLoaded = false;
    let gmTemplatesData = [];
    let activeGMProjectId = null;
    let gmPollInterval = null;
    let gmElapsedInterval = null;
    let gmStartedAt = null;
    const gmAgentOutput = {};  // session_id → last N lines
    const GM_OUTPUT_LINES = 3;
    let gmSessionIds = new Set();

    function formatDuration(seconds) {
        if (!seconds || seconds < 0) return "0s";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return m > 0 ? `${m}m${s.toString().padStart(2, "0")}s` : `${s}s`;
    }

    function startGMElapsedTimer(startedAt) {
        gmStartedAt = new Date(startedAt);
        if (gmElapsedInterval) clearInterval(gmElapsedInterval);
        gmElapsedInterval = setInterval(() => {
            const el = $("#gm-elapsed");
            if (!el || !gmStartedAt) return;
            const elapsed = (Date.now() - gmStartedAt.getTime()) / 1000;
            el.textContent = formatDuration(elapsed);
        }, 1000);
    }

    function stopGMTimers() {
        if (gmPollInterval) { clearInterval(gmPollInterval); gmPollInterval = null; }
        if (gmElapsedInterval) { clearInterval(gmElapsedInterval); gmElapsedInterval = null; }
    }

    function startGMPolling(projectId) {
        stopGMTimers();
        gmPollInterval = setInterval(() => refreshGMPipeline(projectId), 5000);
    }

    async function refreshGMPipeline(projectId) {
        const data = await api(`/api/gm/projects/${projectId}`);
        if (data.error) return;

        renderGMPhase(data.phase);
        renderGMProgressSummary(data);

        const grid = $("#gm-agents-grid");
        grid.innerHTML = "";
        for (const s of (data.sessions || [])) {
            renderGMAgentCardFull(s, data.started_at);
        }

        if (data.phase === "completed" || data.phase === "failed") {
            stopGMTimers();
            const el = $("#gm-elapsed");
            if (el && data.started_at && data.completed_at) {
                const dur = (new Date(data.completed_at) - new Date(data.started_at)) / 1000;
                el.textContent = formatDuration(dur) + " (done)";
            }
            $("#btn-gm-cancel").disabled = true;
            loadGMProjects();
        }
    }

    function renderGMProgressSummary(data) {
        const el = $("#gm-progress-summary");
        if (!el) return;
        const sessions = data.sessions || [];
        const completed = sessions.filter(s => s.status === "completed" || s.status === "failed").length;
        const running = sessions.filter(s => s.status === "running").length;
        const merged = data.merged_count || 0;

        el.innerHTML = `
            <div class="gm-stat">Agents: <span class="gm-stat-value">${completed}/${data.agent_count}</span> done</div>
            <div class="gm-stat">Running: <span class="gm-stat-value">${running}</span></div>
            <div class="gm-stat">Merged: <span class="gm-stat-value">${merged}</span></div>
            ${data.build_attempts > 0 ? `<div class="gm-stat">Build fixes: <span class="gm-stat-value">${data.build_attempts}</span></div>` : ""}
            ${data.test_attempts > 0 ? `<div class="gm-stat">Test fixes: <span class="gm-stat-value">${data.test_attempts}</span></div>` : ""}
        `;
    }

    function captureGMAgentOutput(data) {
        if (data.type !== "team_progress") return;
        if (!gmSessionIds.has(data.session_id)) return;
        if (data.event !== "stdout" && data.event !== "stderr") return;

        const sid = data.session_id;
        if (!gmAgentOutput[sid]) gmAgentOutput[sid] = [];
        gmAgentOutput[sid].push(data.data);
        if (gmAgentOutput[sid].length > GM_OUTPUT_LINES) {
            gmAgentOutput[sid].shift();
        }

        // Live-update the card's output area
        const card = document.querySelector(`.gm-agent-card[data-session-id="${sid}"]`);
        if (card) {
            let outputEl = card.querySelector(".agent-live-output");
            if (!outputEl) {
                outputEl = document.createElement("div");
                outputEl.className = "agent-live-output";
                card.appendChild(outputEl);
            }
            outputEl.textContent = gmAgentOutput[sid].join("\n");
        }
    }

    function renderGMAgentCardFull(session, projectStartedAt) {
        const grid = $("#gm-agents-grid");
        const card = document.createElement("div");
        card.className = "gm-agent-card";
        card.dataset.sessionId = session.session_id;
        grid.appendChild(card);
        // Track session IDs for output capture
        gmSessionIds.add(session.session_id);

        const now = Date.now();
        let timeHtml = "";
        if (session.started_at) {
            const start = new Date(session.started_at).getTime();
            if (session.completed_at) {
                const dur = (new Date(session.completed_at).getTime() - start) / 1000;
                timeHtml = `<div class="agent-time">${formatDuration(dur)}</div>`;
            } else {
                const elapsed = (now - start) / 1000;
                timeHtml = `<div class="agent-time running">${formatDuration(elapsed)}...</div>`;
            }
        }

        let filesHtml = "";
        if (session.files_changed) {
            try {
                const files = JSON.parse(session.files_changed);
                filesHtml = `<div class="agent-files">${files.length} files changed</div>`;
            } catch {}
        }

        let mergeHtml = "";
        if (session.merge_result) {
            const cls = session.merge_result === "merged" || session.merge_result === "merged_resolved"
                ? "text-success" : session.merge_result === "skipped" ? "text-warning" : "";
            mergeHtml = `<div class="agent-merge ${cls}">${session.merge_result}</div>`;
        }

        // Progress bar
        const isDone = session.status === "completed" || session.status === "failed";
        const fillCls = session.status === "failed" ? "failed" : isDone ? "done" : "running";
        const fillWidth = isDone ? 100 : Math.min(95, 20 + ((now - new Date(session.started_at || now).getTime()) / 1000 / 60) * 2);

        // Show buffered output if available
        const lines = gmAgentOutput[session.session_id] || [];
        const liveOutputHtml = lines.length > 0 && session.status === "running"
            ? `<div class="agent-live-output">${escapeHtml(lines.join("\n"))}</div>`
            : "";

        card.innerHTML = `
            <div class="agent-name">${escapeHtml(session.team_name)}</div>
            <div class="agent-status">${statusBadge(session.status)}</div>
            ${timeHtml}
            <div class="agent-progress-bar"><div class="fill ${fillCls}" style="width: ${fillWidth}%"></div></div>
            ${liveOutputHtml}
            ${filesHtml}
            ${mergeHtml}
        `;
    }

    async function loadGMTemplates() {
        if (gmTemplatesLoaded) return;
        try {
            const templates = await api("/api/gm/templates");
            gmTemplatesData = Array.isArray(templates) ? templates : [];
            const select = $("#gm-template-select");
            select.innerHTML = '<option value="">-- Select a project template --</option>';
            for (const t of gmTemplatesData) {
                const opt = document.createElement("option");
                opt.value = t.name;
                opt.textContent = `${t.name} — ${t.description} (${t.agent_count} agents)`;
                select.appendChild(opt);
            }
            gmTemplatesLoaded = true;
        } catch {
            $("#gm-template-select").innerHTML = '<option value="">Failed to load templates</option>';
        }
    }

    // Auto-fill fields when template changes
    if ($("#gm-template-select")) {
        $("#gm-template-select").addEventListener("change", () => {
            const name = $("#gm-template-select").value;
            const tpl = gmTemplatesData.find(t => t.name === name);
            if (tpl) {
                $("#gm-repo-path").value = tpl.repo_path || "";
                $("#gm-build-cmd").value = tpl.build_command || "";
                $("#gm-test-cmd").value = tpl.test_command || "";
            }
        });
    }

    // ── GM Panel — Launch ─────────────────────────────────────────────

    $("#btn-gm-launch").addEventListener("click", async () => {
        const templateName = $("#gm-template-select").value;
        const repoPath = $("#gm-repo-path").value.trim();
        const buildCmd = $("#gm-build-cmd").value.trim();
        const testCmd = $("#gm-test-cmd").value.trim();

        if (!templateName) {
            $("#gm-launch-status").textContent = "Please select a project template.";
            return;
        }
        if (!repoPath) {
            $("#gm-launch-status").textContent = "Repository path is required.";
            return;
        }

        const tpl = gmTemplatesData.find(t => t.name === templateName);
        if (!tpl || !tpl.agents || tpl.agents.length === 0) {
            $("#gm-launch-status").textContent = "Template has no agents.";
            return;
        }

        $("#btn-gm-launch").disabled = true;
        $("#gm-launch-status").textContent = "Launching pipeline...";

        const result = await apiPost("/api/gm/launch", {
            project_name: templateName,
            agents: tpl.agents,
            repo_path: repoPath,
            build_command: buildCmd || null,
            test_command: testCmd || null,
        });

        if (result.error) {
            $("#gm-launch-status").textContent = "Error: " + result.error;
            $("#btn-gm-launch").disabled = false;
            return;
        }

        activeGMProjectId = result.project_id;
        $("#gm-pipeline-name").textContent = templateName;
        $("#gm-log-terminal").innerHTML = '<div class="term-line term-info">Pipeline started. Launching agents...</div>';
        $("#gm-pipeline-card").classList.remove("hidden");
        $("#btn-gm-cancel").disabled = false;
        $("#gm-agents-grid").innerHTML = "";

        // Set initial phase
        renderGMPhase("launching");
        startGMElapsedTimer(new Date().toISOString());
        startGMPolling(result.project_id);

        $("#gm-launch-status").textContent = "Launched! Project: " + result.project_id;
        $("#btn-gm-launch").disabled = false;

        loadGMProjects();
    });

    // ── GM Panel — Cancel ─────────────────────────────────────────────

    $("#btn-gm-cancel").addEventListener("click", async () => {
        if (!activeGMProjectId) return;
        if (!confirm("Cancel GM project " + activeGMProjectId + "?")) return;

        $("#btn-gm-cancel").disabled = true;
        const result = await apiPost(`/api/gm/projects/${activeGMProjectId}/cancel`);
        if (result.error) {
            alert("Cancel failed: " + result.error);
            $("#btn-gm-cancel").disabled = false;
        } else {
            appendGMLog("Pipeline cancelled.", "term-warn");
            activeGMProjectId = null;
            loadGMProjects();
        }
    });

    // ── GM Panel — Phase Bar Rendering ────────────────────────────────

    function renderGMPhase(currentPhase) {
        const phases = ["launching", "waiting", "analyzing", "merging", "building", "testing", "completed"];
        const bar = $$("#gm-phase-bar .gm-phase");
        const currentIdx = phases.indexOf(currentPhase);
        const isFailed = currentPhase === "failed";

        bar.forEach((el, i) => {
            el.classList.remove("active", "completed", "failed");
            const phase = el.dataset.phase;
            const idx = phases.indexOf(phase);

            if (isFailed) {
                if (idx < currentIdx) {
                    el.classList.add("completed");
                } else if (idx === currentIdx) {
                    el.classList.add("failed");
                }
            } else {
                if (idx < currentIdx) {
                    el.classList.add("completed");
                } else if (idx === currentIdx) {
                    el.classList.add("active");
                }
            }
        });
    }

    // ── GM Panel — Agent Cards ────────────────────────────────────────

    function renderGMAgentCard(session) {
        const grid = $("#gm-agents-grid");
        let card = grid.querySelector(`[data-session-id="${session.session_id}"]`);
        if (!card) {
            card = document.createElement("div");
            card.className = "gm-agent-card";
            card.dataset.sessionId = session.session_id;
            grid.appendChild(card);
        }

        let filesHtml = "";
        if (session.files_changed) {
            try {
                const files = JSON.parse(session.files_changed);
                filesHtml = `<div class="agent-files">${files.map(f => escapeHtml(f)).join("<br>")}</div>`;
            } catch {}
        }

        let mergeHtml = "";
        if (session.merge_result) {
            const cls = session.merge_result === "merged" || session.merge_result === "merged_resolved"
                ? "text-success" : session.merge_result === "skipped" ? "text-warning" : "";
            mergeHtml = `<div class="agent-merge ${cls}">${session.merge_result}</div>`;
        }

        card.innerHTML = `
            <div class="agent-name">${escapeHtml(session.team_name)}</div>
            <div class="agent-status">${statusBadge(session.status)}</div>
            ${filesHtml}
            ${mergeHtml}
        `;
    }

    // ── GM Panel — Decision Cards ──────────────────────────────────────

    function renderGMDecisionCard(decision) {
        const area = $("#gm-decisions-area");
        if (!area) return;
        area.classList.remove("hidden");

        // Don't duplicate
        if (area.querySelector(`[data-decision-id="${decision.decision_id}"]`)) return;

        const card = document.createElement("div");
        card.className = "gm-decision-card";
        card.dataset.decisionId = decision.decision_id;

        const typeLabel = (decision.decision_type || "").replace(/_/g, " ");
        const contextHtml = decision.context
            ? `<div class="decision-context">${escapeHtml(decision.context.slice(-2048))}</div>`
            : "";

        card.innerHTML = `
            <div class="decision-header">
                <span class="decision-type">${escapeHtml(typeLabel)}</span>
                <span class="badge badge-warning">Awaiting Approval</span>
            </div>
            <div class="decision-description">${escapeHtml(decision.description)}</div>
            <div class="decision-proposed">Proposed: ${escapeHtml(decision.proposed_action)}</div>
            ${contextHtml}
            <div class="decision-actions">
                <button class="btn btn-sm btn-success" onclick="window._gmDecision('approve','${escapeHtml(decision.decision_id)}')">Approve</button>
                <button class="btn btn-sm btn-danger" onclick="window._gmDecision('reject','${escapeHtml(decision.decision_id)}')">Reject</button>
            </div>
        `;
        area.appendChild(card);
    }

    function removeGMDecisionCard(decisionId) {
        const area = $("#gm-decisions-area");
        if (!area) return;
        const card = area.querySelector(`[data-decision-id="${decisionId}"]`);
        if (card) card.remove();
        if (area.children.length === 0) area.classList.add("hidden");
    }

    window._gmDecision = async function (action, decisionId) {
        const btn = event && event.target;
        if (btn) btn.disabled = true;

        const result = await apiPost(`/api/gm/decisions/${decisionId}/resolve`, { action });
        if (result.error) {
            alert("Decision failed: " + result.error);
            if (btn) btn.disabled = false;
        } else {
            removeGMDecisionCard(decisionId);
        }
    };

    function loadPendingDecisions(decisions) {
        const area = $("#gm-decisions-area");
        if (!area) return;
        area.innerHTML = "";
        const pending = (decisions || []).filter(d => d.status === "pending");
        if (pending.length === 0) {
            area.classList.add("hidden");
            return;
        }
        area.classList.remove("hidden");
        for (const d of pending) {
            renderGMDecisionCard(d);
        }
    }

    // ── GM Panel — Log Terminal ───────────────────────────────────────

    function appendGMLog(text, cls) {
        const terminal = $("#gm-log-terminal");
        if (!terminal) return;
        const div = document.createElement("div");
        div.className = "term-line " + (cls || "term-stdout");
        div.textContent = text;
        terminal.appendChild(div);
        terminal.scrollTop = terminal.scrollHeight;
    }

    // ── GM Panel — WebSocket Handler ──────────────────────────────────

    function handleGMProgress(data) {
        if (data.type !== "gm_progress") return;
        if (data.project_id !== activeGMProjectId) {
            // Still refresh projects list on completion
            if (data.event === "project_completed" || data.event === "project_failed") {
                loadGMProjects();
            }
            return;
        }

        switch (data.event) {
            case "project_started":
                appendGMLog(`Project '${data.project_name}' started`, "term-info");
                break;
            case "agent_launched":
                appendGMLog(`Agent launched: ${data.team_name} (${data.session_id})`, "term-info");
                renderGMAgentCard({ session_id: data.session_id, team_name: data.team_name, status: "running" });
                break;
            case "agent_completed":
                appendGMLog(`Agent ${data.session_id}: ${data.status}`, data.status === "completed" ? "term-info" : "term-stderr");
                renderGMAgentCard({ session_id: data.session_id, team_name: "", status: data.status });
                break;
            case "phase_change":
                renderGMPhase(data.phase);
                appendGMLog(`Phase: ${data.phase}`, "term-info");
                break;
            case "merge_order_determined":
                appendGMLog(`Merge order: ${(data.merge_order || []).join(" → ")}`, "term-info");
                break;
            case "merge_started":
                appendGMLog(`Merging: ${data.session_id} (#${data.index + 1})`, "term-info");
                break;
            case "merge_completed":
                if (data.skipped) {
                    appendGMLog(`Skipped: ${data.session_id}`, "term-warn");
                } else {
                    appendGMLog(`Merged: ${data.session_id}`, "term-info");
                }
                break;
            case "merge_conflict":
                appendGMLog(`Conflict in ${data.session_id}: ${data.error || ""}`, "term-warn");
                break;
            case "conflict_resolved":
                appendGMLog(`Conflicts resolved for ${data.session_id}`, "term-info");
                break;
            case "build_started":
                appendGMLog("Build started...", "term-info");
                break;
            case "build_result":
                appendGMLog(`Build ${data.success ? "passed" : "FAILED"}`, data.success ? "term-info" : "term-stderr");
                if (!data.success && data.output) {
                    appendGMLog(data.output.slice(-500), "term-stderr");
                }
                break;
            case "build_fix_attempt":
                appendGMLog(`Build fix attempt ${data.attempt}...`, "term-warn");
                break;
            case "test_started":
                appendGMLog("Tests started...", "term-info");
                break;
            case "test_result":
                appendGMLog(`Tests ${data.success ? "passed" : "FAILED"}`, data.success ? "term-info" : "term-stderr");
                if (!data.success && data.output) {
                    appendGMLog(data.output.slice(-500), "term-stderr");
                }
                break;
            case "test_fix_attempt":
                appendGMLog(`Test fix attempt ${data.attempt}...`, "term-warn");
                break;
            case "decision_required":
                renderGMDecisionCard(data);
                appendGMLog(`APPROVAL REQUIRED (${data.decision_type}): ${data.description}`, "term-warn");
                break;
            case "decision_resolved":
                removeGMDecisionCard(data.decision_id);
                appendGMLog(`Decision ${data.decision_id}: ${data.action}`, "term-info");
                break;
            case "project_completed":
                appendGMLog("Pipeline completed successfully!", "term-info");
                renderGMPhase("completed");
                $("#btn-gm-cancel").disabled = true;
                activeGMProjectId = null;
                loadGMProjects();
                break;
            case "project_failed":
                appendGMLog(`Pipeline failed: ${data.reason || "unknown"}`, "term-stderr");
                renderGMPhase("failed");
                $("#btn-gm-cancel").disabled = true;
                activeGMProjectId = null;
                loadGMProjects();
                break;
        }
    }

    // ── GM Panel — Projects Table ─────────────────────────────────────

    async function loadGMProjects() {
        const data = await api("/api/gm/projects?limit=50");
        const projects = data.projects || [];
        const total = data.total || 0;

        $("#gm-total").textContent = total;
        const active = projects.filter(p => !["completed", "failed"].includes(p.phase)).length;
        $("#gm-active").textContent = active;

        if (projects.length === 0) {
            $("#gm-projects-table").innerHTML = '<p class="muted">No GM projects yet. Use the form above to launch one.</p>';
            return;
        }

        let html = `<table>
            <thead><tr><th>Project</th><th>Phase</th><th>Agents</th><th>Merged</th><th>Started</th><th>Actions</th></tr></thead>
            <tbody>`;
        for (const p of projects) {
            const phaseCls = p.phase === "completed" ? "badge-success"
                : p.phase === "failed" ? "badge-danger"
                : ["merging", "building", "testing"].includes(p.phase) ? "badge-warning"
                : "badge-info";

            let actions = "";
            if (p.phase === "failed") {
                actions = `<span class="actions-cell">
                    <button class="btn btn-sm btn-success" onclick="window._gmAction('retry','${escapeHtml(p.project_id)}')">Retry</button>
                    <button class="btn btn-sm" onclick="window._gmAction('detail','${escapeHtml(p.project_id)}')">Detail</button>
                </span>`;
            } else if (p.phase === "completed") {
                actions = `<span class="actions-cell">
                    <button class="btn btn-sm btn-success" onclick="window._gmAction('push','${escapeHtml(p.project_id)}')">Push</button>
                    <button class="btn btn-sm" onclick="window._gmAction('detail','${escapeHtml(p.project_id)}')">Detail</button>
                </span>`;
            } else {
                actions = `<span class="actions-cell">
                    <button class="btn btn-sm" onclick="window._gmAction('detail','${escapeHtml(p.project_id)}')">Detail</button>
                </span>`;
            }

            html += `<tr>
                <td><strong>${escapeHtml(p.project_name)}</strong></td>
                <td><span class="badge ${phaseCls}">${p.phase}</span></td>
                <td>${p.completed_count || 0}/${p.agent_count}</td>
                <td>${p.merged_count || 0}</td>
                <td>${formatTime(p.started_at)}</td>
                <td>${actions}</td>
            </tr>`;
        }
        html += "</tbody></table>";
        $("#gm-projects-table").innerHTML = html;
    }

    async function loadGM() {
        await loadGMProjects();
        // Auto-show active pipeline if one exists
        if (!activeGMProjectId) {
            const data = await api("/api/gm/projects?limit=1");
            const projects = data.projects || [];
            if (projects.length > 0 && !["completed", "failed"].includes(projects[0].phase)) {
                window._gmAction("detail", projects[0].project_id);
            }
        }
    }

    // GM action handler
    window._gmAction = async function (action, projectId) {
        switch (action) {
            case "retry": {
                if (!confirm("Retry failed merges/builds for " + projectId + "?")) return;
                const result = await apiPost(`/api/gm/projects/${projectId}/retry`);
                if (result.error) alert("Retry failed: " + result.error);
                else loadGMProjects();
                break;
            }
            case "push": {
                if (!confirm("Push merged result to remote for " + projectId + "?")) return;
                const result = await apiPost(`/api/gm/projects/${projectId}/push`);
                if (result.error) alert("Push failed: " + result.error);
                else { alert("Pushed successfully!"); loadGMProjects(); }
                break;
            }
            case "detail": {
                const data = await api(`/api/gm/projects/${projectId}`);
                if (data.error) { alert(data.error); return; }
                // Show in pipeline card
                activeGMProjectId = projectId;
                $("#gm-pipeline-name").textContent = data.project_name;
                $("#gm-pipeline-card").classList.remove("hidden");
                const isFinished = ["completed", "failed"].includes(data.phase);
                $("#btn-gm-cancel").disabled = isFinished;
                renderGMPhase(data.phase);
                renderGMProgressSummary(data);
                // Render agent cards with timing
                const grid = $("#gm-agents-grid");
                grid.innerHTML = "";
                for (const s of (data.sessions || [])) {
                    renderGMAgentCardFull(s, data.started_at);
                }
                // Elapsed timer
                if (data.started_at) {
                    if (isFinished && data.completed_at) {
                        const dur = (new Date(data.completed_at) - new Date(data.started_at)) / 1000;
                        $("#gm-elapsed").textContent = formatDuration(dur) + " (done)";
                    } else {
                        startGMElapsedTimer(data.started_at);
                        startGMPolling(projectId);
                    }
                }
                // Load pending decisions
                loadPendingDecisions(data.decisions);
                // Show error if failed
                const terminal = $("#gm-log-terminal");
                terminal.innerHTML = "";
                if (data.error_message) {
                    appendGMLog("Error: " + data.error_message, "term-stderr");
                }
                if (data.merge_order) {
                    try {
                        const order = JSON.parse(data.merge_order);
                        appendGMLog("Merge order: " + order.join(" \u2192 "), "term-info");
                    } catch {}
                }
                break;
            }
        }
    };

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
                if (data.type === "team_progress") {
                    handleTeamProgress(data);
                    captureGMAgentOutput(data);
                } else if (data.type === "new_team_session") {
                    const activePanel = document.querySelector(".panel.active");
                    if (activePanel && activePanel.id === "panel-teams") {
                        loadTeams();
                    }
                }
            } catch {}
        };

        // GM WebSocket
        const wsGM = new WebSocket(`${base}/ws/gm`);
        wsGM.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                handleGMProgress(data);
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
