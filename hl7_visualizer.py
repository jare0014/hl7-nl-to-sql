import os
import sys
import json
import urllib.parse
import webbrowser
import subprocess
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import keyring

# Add local project path to import query functions
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)
from query_lake_obsidian import run_query, OMNI_LOGGER_DIR

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class HL7VisualizerHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging to console to keep it clean
        pass

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # Serve UI HTML
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = get_dashboard_html()
            self.wfile.write(html.encode('utf-8'))
            return

        # API: Get configuration
        elif path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            config = {}
            settings_path = os.path.join(OMNI_LOGGER_DIR, "data.json")
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except Exception:
                    pass
            
            # Read keyring presence
            has_gemini_key = False
            try:
                key = keyring.get_password("hl7-nl-to-sql", "gemini_api_key")
                if key:
                    has_gemini_key = True
            except Exception:
                pass
            
            res_data = {
                "ollamaUrl": config.get("ollamaUrl", "http://localhost:11434"),
                "executorModel": config.get("executorModel", "qwen2.5-coder:7b"),
                "templateProvider": config.get("templateProvider", "gemini"),
                "hasGeminiKey": has_gemini_key
            }
            self.wfile.write(json.dumps(res_data).encode('utf-8'))
            return

        # Default fallback
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # API: Save configuration
        if path == "/api/save_config":
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                payload = json.loads(post_data.decode('utf-8'))

                ollama_url = payload.get("ollamaUrl", "").strip()
                executor_model = payload.get("executorModel", "").strip()
                template_provider = payload.get("templateProvider", "gemini").strip()
                gemini_key = payload.get("geminiApiKey", "").strip()

                settings_path = os.path.join(OMNI_LOGGER_DIR, "data.json")
                config = {}
                if os.path.exists(settings_path):
                    try:
                        with open(settings_path, "r", encoding="utf-8") as f:
                            config = json.load(f)
                    except Exception:
                        pass
                
                # Update settings dictionary
                if ollama_url:
                    config["ollamaUrl"] = ollama_url
                if executor_model:
                    config["executorModel"] = executor_model
                if template_provider:
                    config["templateProvider"] = template_provider
                
                # Write to keyring if Gemini key provided
                if gemini_key:
                    try:
                        keyring.set_password("hl7-nl-to-sql", "gemini_api_key", gemini_key)
                    except Exception as e:
                        raise RuntimeError(f"Failed to store key in system keychain: {e}")

                # Save updated config back to data.json
                os.makedirs(OMNI_LOGGER_DIR, exist_ok=True)
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Settings saved successfully!"}).encode('utf-8'))
            except Exception as err:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(err)}).encode('utf-8'))
            return

        # API: Run batch ingest
        elif path == "/api/ingest":
            try:
                print("[HTTP Server] Spawning ingest_all_samples.py...")
                python_bin = sys.executable
                script_path = os.path.join(SCRIPT_DIR, "ingest_all_samples.py")
                
                # Execute in subprocess and capture log output
                result = subprocess.run([python_bin, script_path], capture_output=True, text=True, check=True)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "success",
                    "output": result.stdout
                }).encode('utf-8'))
            except Exception as err:
                # Capture standard error if failed
                err_msg = getattr(err, "stderr", None) or str(err)
                print(f"[HTTP Server] Ingestion failed: {err_msg}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": err_msg
                }).encode('utf-8'))
            return

        # API: Query Data Lake
        elif path == "/api/query":
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                payload = json.loads(post_data.decode('utf-8'))
                nl_query = payload.get("query", "").strip()

                if not nl_query:
                    raise ValueError("Query string cannot be empty.")

                print(f"[HTTP Server] Processing NL Query: '{nl_query}'...")
                res = run_query(nl_query)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "success",
                    "sql": res["sql"],
                    "clinical_summary": res["clinical_summary"],
                    "results_markdown": res["results_markdown"],
                    "columns": res["columns"],
                    "rows": res["rows"],
                    "mappings": res["mappings"]
                }).encode('utf-8'))
            except Exception as err:
                print(f"[HTTP Server] Query failed: {err}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": str(err)
                }).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

def get_dashboard_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HL7 NL-to-SQL Clinical Data Lake Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0a0e17;
            --bg-panel: rgba(16, 22, 37, 0.95);
            --bg-card: rgba(22, 30, 49, 0.7);
            --bg-card-border: rgba(255, 255, 255, 0.08);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-indigo: #6366f1;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --glow-indigo: rgba(99, 102, 241, 0.15);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.1) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.05) 0px, transparent 50%);
        }

        header {
            padding: 24px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--bg-card-border);
            background: rgba(10, 14, 23, 0.8);
            backdrop-filter: blur(10px);
        }

        .logo-area h1 {
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #a5b4fc, #6366f1, #34d399);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .logo-area span {
            font-size: 11px;
            font-weight: 500;
            background: rgba(99, 102, 241, 0.2);
            color: #a5b4fc;
            padding: 3px 8px;
            border-radius: 99px;
            border: 1px solid rgba(99, 102, 241, 0.3);
            text-transform: uppercase;
        }

        .container {
            display: flex;
            flex: 1;
            padding: 30px 40px;
            gap: 30px;
            max-width: 1600px;
            margin: 0 auto;
            width: 100%;
        }

        /* Panels */
        .left-column {
            flex: 0 0 380px;
            display: flex;
            flex-direction: column;
            gap: 30px;
        }

        .right-column {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 30px;
        }

        .panel {
            background: var(--bg-panel);
            border: 1px solid var(--bg-card-border);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 30px -10px rgba(0,0,0,0.5);
        }

        .panel-title {
            font-size: 15px;
            font-weight: 700;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
            color: #e2e8f0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            padding-bottom: 10px;
        }

        /* Form elements */
        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .form-group input, .form-group select {
            width: 100%;
            background: rgba(15, 23, 42, 0.5);
            border: 1px solid var(--bg-card-border);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text-main);
            font-family: inherit;
            font-size: 13px;
            transition: all 0.2s;
        }

        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: var(--accent-indigo);
            box-shadow: 0 0 0 3px var(--glow-indigo);
        }

        /* Button styles */
        .btn {
            background: var(--accent-indigo);
            color: white;
            border: none;
            padding: 12px 20px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            width: 100%;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
        }

        .btn:hover {
            opacity: 0.9;
            transform: translateY(-1px);
        }

        .btn:active {
            transform: translateY(0);
        }

        .btn-secondary {
            background: rgba(255,255,255,0.05);
            border: 1px solid var(--bg-card-border);
            color: var(--text-main);
            box-shadow: none;
        }

        .btn-secondary:hover {
            background: rgba(255,255,255,0.1);
        }

        /* Query Input */
        .query-box-container {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }

        .query-input {
            flex: 1;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--bg-card-border);
            border-radius: 12px;
            padding: 16px 20px;
            color: var(--text-main);
            font-family: inherit;
            font-size: 15px;
            transition: all 0.2s;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
        }

        .query-input:focus {
            outline: none;
            border-color: var(--accent-indigo);
            box-shadow: 0 0 0 3px var(--glow-indigo);
        }

        .btn-query {
            width: 140px;
            font-size: 15px;
            font-weight: 700;
            border-radius: 12px;
        }

        /* Results Display */
        .results-panel {
            min-height: 400px;
            display: flex;
            flex-direction: column;
        }

        .results-tabs {
            display: flex;
            gap: 8px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            margin-bottom: 20px;
            padding-bottom: 8px;
        }

        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .tab-btn:hover {
            color: var(--text-main);
            background: rgba(255,255,255,0.03);
        }

        .tab-btn.active {
            color: white;
            background: rgba(99, 102, 241, 0.2);
            border: 1px solid rgba(99, 102, 241, 0.3);
        }

        .tab-content {
            display: none;
            flex: 1;
        }

        .tab-content.active {
            display: block;
        }

        /* Clinical Summary Callout */
        .summary-callout {
            background: rgba(59, 130, 246, 0.08);
            border-left: 4px solid var(--accent-blue);
            border-radius: 8px;
            padding: 20px;
            font-size: 14px;
            line-height: 1.6;
            color: #e2e8f0;
            margin-bottom: 20px;
        }

        /* Tables */
        .table-container {
            width: 100%;
            overflow-x: auto;
            border: 1px solid var(--bg-card-border);
            border-radius: 10px;
            background: rgba(10, 14, 23, 0.4);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }

        th {
            background: rgba(255,255,255,0.03);
            color: var(--text-muted);
            font-weight: 600;
            padding: 12px 16px;
            border-bottom: 1px solid var(--bg-card-border);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        td {
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            color: #cbd5e1;
        }

        tr:hover td {
            background: rgba(255,255,255,0.01);
        }

        /* Code highlight */
        pre {
            background: rgba(10, 14, 23, 0.8);
            padding: 20px;
            border-radius: 10px;
            border: 1px solid var(--bg-card-border);
            overflow-x: auto;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            color: #34d399;
            line-height: 1.5;
        }

        /* Logs Console */
        .console-log {
            background: #05070c;
            border: 1px solid var(--bg-card-border);
            border-radius: 10px;
            padding: 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: #94a3b8;
            height: 180px;
            overflow-y: auto;
            white-space: pre-wrap;
            margin-top: 14px;
        }

        .console-log.active-run {
            color: #cbd5e1;
            border-color: rgba(16, 185, 129, 0.3);
        }

        /* Semantic vocabulary pills */
        .mappings-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .mapping-type {
            font-size: 12px;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .pills-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 6px;
        }

        .pill {
            background: rgba(99, 102, 241, 0.1);
            color: #818cf8;
            border: 1px solid rgba(99, 102, 241, 0.25);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
        }

        .pill-empty {
            font-size: 13px;
            color: var(--text-muted);
            font-style: italic;
        }

        /* Status helper classes */
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 99px;
            display: inline-block;
        }
        .status-success { background: var(--accent-green); }
        .status-pending { background: var(--accent-blue); }

        .loader {
            display: none;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 40px;
            font-size: 14px;
            color: var(--text-muted);
        }

        .spinner {
            border: 3px solid rgba(255,255,255,0.05);
            width: 24px;
            height: 24px;
            border-radius: 50%;
            border-left-color: var(--accent-indigo);
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <header>
        <div class="logo-area">
            <h1>🏥 Clinical Data Lake <span>NL-to-SQL</span></h1>
        </div>
        <div>
            <span style="font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
                <span class="status-dot status-success"></span> Data Lake: Active
            </span>
        </div>
    </header>

    <div class="container">
        <!-- Sidebar Controls -->
        <div class="left-column">
            <!-- Settings panel -->
            <div class="panel">
                <div class="panel-title">⚙️ LLM Configuration</div>
                <div class="form-group">
                    <label>Provider</label>
                    <select id="config-provider" onchange="toggleProviderFields()">
                        <option value="gemini">Google Gemini (Cloud)</option>
                        <option value="ollama">Ollama (Local-First)</option>
                    </select>
                </div>
                <div id="gemini-fields">
                    <div class="form-group">
                        <label>Google Gemini API Key</label>
                        <input type="password" id="config-gemini-key" placeholder="••••••••••••••••">
                        <p style="font-size: 11px; color: var(--text-muted); margin-top: 6px;" id="gemini-key-status">
                            Checking OS Keychain...
                        </p>
                    </div>
                </div>
                <div id="ollama-fields" style="display: none;">
                    <div class="form-group">
                        <label>Ollama Host URL</label>
                        <input type="text" id="config-ollama-url" placeholder="http://100.93.91.76:11434">
                    </div>
                    <div class="form-group">
                        <label>Ollama Model</label>
                        <input type="text" id="config-ollama-model" placeholder="qwen2.5-coder:7b">
                    </div>
                </div>
                <button class="btn" onclick="saveConfig()">Save Settings</button>
            </div>

            <!-- Ingest control panel -->
            <div class="panel">
                <div class="panel-title">🔄 Ingest Telemetry</div>
                <p style="font-size: 13px; color: var(--text-muted); line-height: 1.5; margin-bottom: 16px;">
                    Read raw patient HL7 files (`samples/`), extract parameters using the LLM, and seed SQLite database and ChromaDB.
                </p>
                <button class="btn btn-secondary" onclick="runIngestion()">Run Batch Ingest</button>
                <div class="console-log" id="ingest-logs">Console logs idle...</div>
            </div>
        </div>

        <!-- Main Query Area -->
        <div class="right-column">
            <!-- Query lab -->
            <div class="panel">
                <div class="panel-title">🧬 Clinical Query Lab</div>
                <div class="query-box-container">
                    <input type="text" class="query-input" id="query-input" placeholder="Type a clinician request (e.g. 'When was Donald Duck admitted?' or 'List patients with high glucose values')..." onkeydown="if(event.key === 'Enter') executeQuery()">
                    <button class="btn btn-query" onclick="executeQuery()">Execute</button>
                </div>
            </div>

            <!-- Query Output Panel -->
            <div class="panel results-panel" id="results-panel" style="display: none;">
                <div class="results-tabs">
                    <button class="tab-btn active" onclick="switchTab('summary')">🩺 Clinical Summary</button>
                    <button class="tab-btn" onclick="switchTab('records')">📊 Database Records</button>
                    <button class="tab-btn" onclick="switchTab('sql')">💻 Generated SQL</button>
                    <button class="tab-btn" onclick="switchTab('mappings')">🔍 ChromaDB Vocab</button>
                </div>

                <div class="loader" id="query-loader">
                    <div class="spinner"></div>
                    <span>Translating query & searching patient database...</span>
                </div>

                <div id="query-results-area">
                    <!-- Tab 1: Clinical Summary -->
                    <div class="tab-content active" id="tab-summary">
                        <div class="summary-callout" id="clinical-summary-text">
                            No query processed yet.
                        </div>
                    </div>

                    <!-- Tab 2: Database Records -->
                    <div class="tab-content" id="tab-records">
                        <div class="table-container">
                            <table id="records-table">
                                <thead>
                                    <tr><th>Headers</th></tr>
                                </thead>
                                <tbody>
                                    <tr><td>No records fetched.</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Tab 3: Generated SQL -->
                    <div class="tab-content" id="tab-sql">
                        <pre><code id="sql-code-block">-- SQL query will appear here</code></pre>
                    </div>

                    <!-- Tab 4: ChromaDB Mappings -->
                    <div class="tab-content" id="tab-mappings">
                        <div class="mappings-container">
                            <div>
                                <div class="mapping-type">Patients matched:</div>
                                <div class="pills-list" id="map-patients"><span class="pill-empty">None</span></div>
                            </div>
                            <div>
                                <div class="mapping-type">Test Names matched:</div>
                                <div class="pills-list" id="map-tests"><span class="pill-empty">None</span></div>
                            </div>
                            <div>
                                <div class="mapping-type">Abnormality Flags matched:</div>
                                <div class="pills-list" id="map-flags"><span class="pill-empty">None</span></div>
                            </div>
                            <div>
                                <div class="mapping-type">Genders matched:</div>
                                <div class="pills-list" id="map-genders"><span class="pill-empty">None</span></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Init config on load
        window.addEventListener('load', fetchConfig);

        async function fetchConfig() {
            try {
                const response = await fetch('/api/config');
                const data = await response.json();

                document.getElementById('config-provider').value = data.templateProvider;
                document.getElementById('config-ollama-url').value = data.ollamaUrl;
                document.getElementById('config-ollama-model').value = data.executorModel;

                const keyStatusEl = document.getElementById('gemini-key-status');
                if (data.hasGeminiKey) {
                    keyStatusEl.innerHTML = "🟢 API Key stored securely in OS Keychain";
                    keyStatusEl.style.color = "var(--accent-green)";
                } else {
                    keyStatusEl.innerHTML = "🔴 No API Key detected in OS Keychain";
                    keyStatusEl.style.color = "var(--accent-red)";
                }

                toggleProviderFields();
            } catch (err) {
                console.error("Failed to fetch configuration", err);
            }
        }

        function toggleProviderFields() {
            const provider = document.getElementById('config-provider').value;
            const geminiFields = document.getElementById('gemini-fields');
            const ollamaFields = document.getElementById('ollama-fields');

            if (provider === 'gemini') {
                geminiFields.style.display = 'block';
                ollamaFields.style.display = 'none';
            } else {
                geminiFields.style.display = 'none';
                ollamaFields.style.display = 'block';
            }
        }

        async function saveConfig() {
            const payload = {
                templateProvider: document.getElementById('config-provider').value,
                ollamaUrl: document.getElementById('config-ollama-url').value,
                executorModel: document.getElementById('config-ollama-model').value,
                geminiApiKey: document.getElementById('config-gemini-key').value
            };

            try {
                const response = await fetch('/api/save_config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                
                if (data.status === 'success') {
                    alert("Settings saved successfully!");
                    document.getElementById('config-gemini-key').value = '';
                    fetchConfig();
                } else {
                    alert("Error: " + data.message);
                }
            } catch (err) {
                alert("Failed to save settings: " + err);
            }
        }

        async function runIngestion() {
            const logsEl = document.getElementById('ingest-logs');
            logsEl.className = 'console-log active-run';
            logsEl.innerHTML = "Ingesting files in category: ADT & ORU... running LLM extraction over all files... please wait (takes 1-3 mins)...\\n";

            try {
                const response = await fetch('/api/ingest', { method: 'POST' });
                const data = await response.json();
                
                if (data.status === 'success') {
                    logsEl.innerHTML = data.output;
                    alert("Telemetry ingestion completed successfully!");
                } else {
                    logsEl.innerHTML = "Error: " + data.message;
                    alert("Ingestion failed!");
                }
            } catch (err) {
                logsEl.innerHTML = "Fatal Error: " + err;
                alert("Ingestion connection failed!");
            } finally {
                logsEl.className = 'console-log';
            }
        }

        async function executeQuery() {
            const query = document.getElementById('query-input').value.trim();
            if (!query) return;

            const resultsPanel = document.getElementById('results-panel');
            const resultsArea = document.getElementById('query-results-area');
            const loader = document.getElementById('query-loader');

            resultsPanel.style.display = 'block';
            resultsArea.style.display = 'none';
            loader.style.display = 'flex';

            try {
                const response = await fetch('/api/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });
                const data = await response.json();

                if (data.status === 'success') {
                    // Update Summary
                    document.getElementById('clinical-summary-text').innerHTML = data.clinical_summary;
                    
                    // Update SQL
                    document.getElementById('sql-code-block').innerHTML = data.sql;

                    // Update Table
                    buildRecordsTable(data.columns, data.rows);

                    // Update ChromaDB Mappings
                    buildMappings(data.mappings);

                    resultsArea.style.display = 'block';
                } else {
                    alert("Query failed: " + data.message);
                }
            } catch (err) {
                alert("Query failed to connect: " + err);
            } finally {
                loader.style.display = 'none';
            }
        }

        function buildRecordsTable(columns, rows) {
            const table = document.getElementById('records-table');
            
            if (!columns || columns.length === 0) {
                table.innerHTML = "<thead><tr><th>Headers</th></tr></thead><tbody><tr><td>No records found.</td></tr></tbody>";
                return;
            }

            // Headers
            let html = "<thead><tr>";
            columns.forEach(col => {
                html += `<th>${col}</th>`;
            });
            html += "</tr></thead><tbody>";

            // Rows
            if (!rows || rows.length === 0) {
                html += `<tr><td colspan="${columns.length}">Query executed successfully. No rows returned.</td></tr>`;
            } else {
                rows.forEach(row => {
                    html += "<tr>";
                    row.forEach(val => {
                        html += `<td>${val !== null ? val : 'NULL'}</td>`;
                    });
                    html += "</tr>";
                });
            }
            html += "</tbody>";
            table.innerHTML = html;
        }

        function buildMappings(mappings) {
            const mapPatients = document.getElementById('map-patients');
            const mapTests = document.getElementById('map-tests');
            const mapFlags = document.getElementById('map-flags');
            const mapGenders = document.getElementById('map-genders');

            buildPillsList(mapPatients, mappings.patients, p => `"${p.matched_term}" ➔ MRN:${p.mrn} (${p.name})`);
            buildPillsList(mapTests, mappings.test_names, t => `"${t.matched_term}" ➔ ${t.value}`);
            buildPillsList(mapFlags, mappings.flags, f => `"${f.matched_term}" ➔ ${f.code} (${f.description})`);
            buildPillsList(mapGenders, mappings.genders, g => `"${g.matched_term}" ➔ ${g.code}`);
        }

        function buildPillsList(container, items, labelFn) {
            if (!items || items.length === 0) {
                container.innerHTML = '<span class="pill-empty">None</span>';
                return;
            }

            let html = '';
            items.forEach(item => {
                html += `<span class="pill">${labelFn(item)}</span>`;
            });
            container.innerHTML = html;
        }

        function switchTab(tabId) {
            const buttons = document.querySelectorAll('.tab-btn');
            const contents = document.querySelectorAll('.tab-content');

            buttons.forEach(btn => {
                btn.classList.remove('active');
                if (btn.innerText.toLowerCase().includes(tabId)) {
                    btn.classList.add('active');
                }
            });

            contents.forEach(content => {
                content.classList.remove('active');
                if (content.id === `tab-${tabId}`) {
                    content.classList.add('active');
                }
            });
        }
    </script>
</body>
</html>
"""

def main():
    # Setup HTTP Server to host the query interface locally
    port = 8081
    
    # Try finding an open port starting from 8081
    while True:
        try:
            server_address = ('0.0.0.0', port)
            httpd = ThreadingHTTPServer(server_address, HL7VisualizerHTTPHandler)
            break
        except OSError:
            port += 1
            if port > 8100:
                print("Error: Could not find an open port between 8081 and 8100.")
                sys.exit(1)

    print(f"==================================================")
    print(f"  HL7 CLINICAL DATA LAKE QUERY PORTAL ENGAGED      ")
    print(f"==================================================")
    print(f"Local Portal Address:   http://127.0.0.1:{port}")
    print(f"Network Portal Address: http://0.0.0.0:{port} (accessible on Wi-Fi)")
    print(f"Press Ctrl+C to terminate the local server.")
    print(f"==================================================")

    # Open browser on the server address in a separate thread so it doesn't block server initialization
    def open_browser():
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass

    threading.Timer(1.0, open_browser).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local HL7 visualizer portal. Goodbye!")
        httpd.server_close()

if __name__ == "__main__":
    main()
