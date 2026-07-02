# HL7 NL-to-SQL Clinical Data Engine

A secure, HIPAA-compliant natural language to SQL (NL-to-SQL) engine for parsing, storing, and querying HL7 clinical data lakes. 

The pipeline combines a local SQLite database (for structured clinical records), ChromaDB (for semantic synonym matching and fuzzy name correction), and Ollama (local LLM inference) to translate conversational queries into valid SQL without exposing patient data to public cloud APIs. 

Private networking is established between workstations and the database/LLM host using Tailscale.

---

## 📐 Architecture Overview

```text
+------------------------------------------------+
|                Workstation (Client)            |
|  - Obsidian Front-End / Markdown Files         |
|  - Local Python Query Runner                   |
|  - ChromaDB (Fuzzy synonym & term mappings)    |
+-----------------------^------------------------+
                        |
            Tailscale (WireGuard)
            [Encrypted VPN Tunnel]
                        |
+-----------------------v------------------------+
|             Ollama PC (Server Host)            |
|  - SQLite Database (hl7_data_lake.db)          |
|  - Ollama Service (running qwen2.5-coder:7b)   |
+------------------------------------------------+
```

---

## 🛠️ Installation & Dependency Setup

### 1. Python Environment & OS Keychain Configuration
This project requires **Python 3.8+**. 

Run the interactive setup wizard in the project root to automatically create a virtual environment, install dependencies, and configure your Gemini API Key securely inside your OS Keychain/Credential Manager:
```bash
python setup.py
```

### 2. SQLite Database
*   **Database Engine:** SQLite is built directly into Python; no separate database server installation is required.
*   **GUI Viewer:** To inspect tables, view patient demographics, and manually verify observation records, it is highly recommended to install [DB Browser for SQLite](https://sqlitebrowser.org/).

### 3. Vector Database (ChromaDB)
*   ChromaDB runs as a lightweight, embedded vector store. The database files are stored locally in the `./chroma_db` directory. 
*   No external Chroma service needs to be set up.

---

## 🦙 Ollama Host Setup (LLM Server)

Ollama runs on your high-performance hardware to process prompts locally.

1.  **Install Ollama:** Download and install Ollama from [ollama.com](https://ollama.com).
2.  **Pull the Coder Model:** Run the following command in a terminal to download the optimized coding LLM:
    ```bash
    ollama pull qwen2.5-coder:7b
    ```
3.  **Enable Network Access (Listen on all interfaces):**
    By default, Ollama only listens to requests on `localhost`. To share Ollama over your Tailscale private network:
    *   **Environment Variable:** Add a System Environment Variable named `OLLAMA_HOST` and set its value to `0.0.0.0`.
    *   **Restart Ollama:** Right-click the Ollama tray icon, click **Quit**, and restart Ollama from the Start menu so it loads the new system variable.
4.  **Configure Windows Firewall:**
    Tailscale network connections on Windows are classified under the **Public** profile. You must explicitly allow the Ollama service to listen on public networks by running this command in **PowerShell (as Administrator)**:
    ```powershell
    Set-NetFirewallRule -DisplayName "ollama.exe" -Profile Any
    ```

---

## 🔒 Tailscale Private Network Setup

Tailscale creates an end-to-end encrypted WireGuard overlay network to connect your workstations securely.

1.  Download and install Tailscale on all participating machines from [tailscale.com](https://tailscale.com).
2.  Log in with your credentials to add the machines to your private admin console (Tailnet).
3.  Obtain the private Tailscale IP of your Ollama host PC (e.g., `100.93.91.76`).

---

## ⚙️ Configuration & Standalone Mode

You can run the engine completely standalone (independent of Obsidian) by setting the following environment variables in your terminal session:

### Environment Variables List

| Variable | Description | Default | Example |
| :--- | :--- | :--- | :--- |
| `OLLAMA_HOST` | Host URL of your Ollama PC | `http://localhost:11434` | `http://100.93.91.76:11434` |
| `OLLAMA_MODEL` | Local LLM model identifier | `qwen2.5-coder:7b` | `qwen2.5:7b` |
| `HL7_DB_PATH` | Path to SQLite database file | `./hl7_data_lake.db` | `/custom/path/hl7.db` |
| `CHROMA_PATH` | Path to ChromaDB directory | `./chroma_db` | `/custom/path/chroma` |
| `LLM_PROVIDER` | Override active model provider | `gemini` (if key set) / `ollama` | `ollama` |

*   **In PowerShell:**
    ```powershell
    $env:OLLAMA_HOST = "http://<ollama-pc-ip>:11434"
    $env:OLLAMA_MODEL = "qwen2.5-coder:7b"
    ```
*   **In Windows CMD:**
    ```cmd
    set OLLAMA_HOST=http://<ollama-pc-ip>:11434
    set OLLAMA_MODEL=qwen2.5-coder:7b
    ```
*   **In Linux/macOS:**
    ```bash
    export OLLAMA_HOST="http://<ollama-pc-ip>:11434"
    export OLLAMA_MODEL="qwen2.5-coder:7b"
    ```

---

## 🚀 Execution Commands

### 1. Ingesting Raw HL7 Messages
Place your raw clinical messages (e.g., `.txt` HL7 files) into `samples/ADT/` (demographics) or `samples/ORU/` (observational results). Then run:
```bash
python ingest_all_samples.py
```
This script will:
*   Extract patient data and clinical measurements using your local Ollama instance.
*   Populate the SQLite tables.
*   Auto-index patient names, test names, and abnormality flags inside ChromaDB.

### 2. Executing Natural Language Queries
Create a markdown file (or use an Obsidian note) containing a `nl_query` field in its frontmatter:
```markdown
---
nl_query: "Show me all abnormal labs for John Doe"
---
```
Run the query runner script, passing the path to your markdown file:
```bash
python query_lake_obsidian.py "/absolute/path/to/your/note.md"
```
The query engine will:
*   Fuzzy-correct spelling errors (e.g., "cholsterol" $\rightarrow$ "cholesterol").
*   Translate "abnormal" $\rightarrow$ `flag != 'N'` and "John Doe" $\rightarrow$ `mrn: '1234-12'` using ChromaDB.
*   Query your SQLite database.
*   Synthesize a grounded natural language summary and append a styled markdown results block back to the bottom of the note.
