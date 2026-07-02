---
status: 🟢 Active
type: ProfessionalDevelopment
repo: hl7-nl-to-sql
nl_query: ""
---
# HL7 NL-to-SQL Generator (Architecture A)

A secure, natural-language-to-SQL interface for querying HL7 clinical data lakes. This project leverages a local LLM to preserve strict HIPAA compliance, querying a remote database over a private Tailscale overlay network.

## 📐 Architecture: Local Execution, Cloud Database (Architecture A)
* **Local LLM Engine:** Ollama running `qwen2.5-coder:7b` (or general `qwen2.5:7b`) on local hardware.
* **Network & Security:** Tailscale VPN creates an end-to-end encrypted connection between the local workstation and the cloud database, bypassing the public internet entirely.
* **Execution:** A Python backend queries the database schema, constructs context-aware prompts for the local model, validates the returned SQL, and executes it securely.
* **Obsidian Integration:** A front-end interface built similarly to `omni-logger` to trigger natural language queries directly from notes.

## 🔍 NL-to-SQL Query Interface
Enter your clinical question in natural language below:
`INPUT[text:nl_query]`

```meta-bind-button
label: "Execute Query"
style: primary
actions:
  - type: command
    command: omni-logger:hl7-nl-query
```

```meta-bind-button
label: "Ingest All HL7 Samples"
style: default
actions:
  - type: command
    command: omni-logger:hl7-ingest-all
```

---

## Dev Log History

```dataviewjs
const current = dv.current();
if (!current || !current.file) return;
const currentFileName = current.file.name;

// 1. Determine project keywords and git repository names to match
const cleanName = currentFileName
    .replace(/dev log/i, "")
    .replace(/project/i, "")
    .trim()
    .toLowerCase();

const slugName = cleanName.replace(/[^a-z0-9]+/g, "-");

// Collect repo candidates
let candidates = new Set([cleanName, slugName]);

// Support explicit repo names listed in the note's frontmatter
if (current.repo) {
    const repos = Array.isArray(current.repo) ? current.repo : [current.repo];
    for (const r of repos) {
        if (r) {
            candidates.add(r.trim().toLowerCase());
            candidates.add(r.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-"));
        }
    }
}

const candidateList = Array.from(candidates);

// Filter out generic keywords for message-level matching
const genericNames = new Set(["untitled", "untitled.md", "dev log", "project", "log", "history", ""]);
const msgKeywords = candidateList.filter(c => c && !genericNames.has(c));

// 2. Fetch and process daily notes from "02_Journal/01_Daily"
const pages = dv.pages('"02_Journal/01_Daily"').sort(p => p.file.name, "desc");
const rows = [];

for (const p of pages) {
    const logs = [];
    
    // Check if this daily note explicitly links to this project page
    const projects = [].concat(p.Project || []);
    const isLinkedToThisProject = projects.some(proj => {
        if (proj && typeof proj === 'object' && proj.path) {
            return proj.path === current.file.path;
        }
        return String(proj).includes(currentFileName);
    });

    // A. Parse manual log entries (from Dev_Log or Log fields)
    const devLogs = [].concat(p.Dev_Log || []).concat(p.Log || []);
    for (const dl of devLogs) {
        if (!dl) continue;
        const dlStr = String(dl);
        const matchesManual = isLinkedToThisProject || 
                              dlStr.includes(currentFileName) || 
                              candidateList.some(cand => dlStr.toLowerCase().includes(cand));
        if (matchesManual && !logs.includes(dlStr)) {
            logs.push(dlStr);
        }
    }
    
    // B. Parse Antigravity Git Logs
    const content = await dv.io.load(p.file.path);
    if (content) {
        const gitLogRegex = /<!--\s*START(?:_|-)(?:antigravity|Antigravity)(?:_|-)(?:git|Git)(?:_|-)(?:log|Log)\s*-->([\s\S]*?)<!--\s*END(?:_|-)(?:antigravity|Antigravity)(?:_|-)(?:git|Git)(?:_|-)(?:log|Log)\s*-->/i;
        const match = content.match(gitLogRegex);
        if (match) {
            const gitBlock = match[1];
            const lines = gitBlock.split(/\r?\n/);
            let currentRepo = "";
            for (let line of lines) {
                line = line.trim();
                if (line.startsWith("**") && line.endsWith("**")) {
                    currentRepo = line.replace(/\*\*/g, '').trim().toLowerCase();
                } else if (line.startsWith("- ") && currentRepo) {
                    const commitLower = line.toLowerCase();
                    const repoMatches = candidateList.some(cand => 
                        currentRepo === cand || 
                        currentRepo.includes(cand) || 
                        cand.includes(currentRepo)
                    );
                    const messageMatches = msgKeywords.some(kw => commitLower.includes(kw));
                    
                    if (repoMatches || messageMatches) {
                        const logLine = "🐙 **Git Log**: " + line.substring(2);
                        if (!logs.includes(logLine)) {
                            logs.push(logLine);
                        }
                    }
                }
            }
        }
    }
    
    // C. Add to table if logs were found for this day
    if (logs.length > 0) {
        rows.push([p.file.link, logs.join("<br>")]);
    }
}

dv.table(["Date", "Notes"], rows);
```

---

# Future Deployment Plan: HIPAA-Compliant Hybrid Data Lake

This plan outlines the architecture and security steps required to transition the local HL7 data lake and query engine into a secure, shared clinical environment.

---

## 📐 Target Architecture

```text
+------------------------------------------+
|          Clinic Local Network            |
|                                          |
|  +--------------------+                  |
|  | Central GPU Server |                  |
|  |  - Ollama (LLM)    |                  |
|  +---------^----------+                  |
|            |                             |
|    Tailscale (WireGuard)                 |
|            |                             |
+------------|-----------------------------+
             | (Encrypted Tunnel)
+------------|-----------------------------+
|      Secure Cloud VPS (VPC)              |
|            |                             |
|  +---------v----------+                  |
|  |   Data Lake DB     |                  |
|  | - PostgreSQL       |                  |
|  | - pgvector         |                  |
|  +--------------------+                  |
+------------------------------------------+
```

---

## 🔒 Security & HIPAA Requirements

### 1. Encryption in Transit
*   **Default Behavior:** Ollama communicates via unencrypted HTTP on port `11434`.
*   **Cloud Connection:** All connections between local workstations, the central clinic GPU server, and the cloud database VPS must flow through **Tailscale**. Tailscale enforces peer-to-peer WireGuard encryption (TLS 1.3/AES-GCM), preventing sniffers on the clinic LAN or the public internet from intercepting patient data.

### 2. Access Control
*   The cloud database (PostgreSQL) must be configured to bind and listen **only** on its Tailscale interface (`100.x.y.z`). All public firewall ports (`5432` for Postgres, etc.) must remain closed to the public internet.
*   Only registered nodes in the clinic's Tailscale Admin Console (Tailnet) are granted permissions to connect.

---

## 🛠️ Step-by-Step Migration Roadmap

### Phase 1: Database Migration
1.  Spin up a secure managed PostgreSQL instance (e.g., AWS RDS, Supabase, or a private VM).
2.  Enable the **`pgvector`** extension in PostgreSQL:
    ```sql
    CREATE EXTENSION IF NOT EXISTS vector;
    ```
3.  Migrate the schema from SQLite to PostgreSQL. Update Python DB connections in `query_lake_obsidian.py` to use `psycopg2` or `SQLAlchemy`.

### Phase 2: Vector Store Consolidation
1.  Replace the local ChromaDB client in `vector_store.py` with PostgreSQL `pgvector` tables.
2.  Index patient name embeddings, flags, and test names directly in the database, eliminating the need to maintain a separate ChromaDB directory.

### Phase 3: Centralizing Ollama
1.  Deploy Ollama on a single, high-performance local server on the clinic's network (equipped with a GPU like an RTX 4090 or Apple Silicon Mac Studio).
2.  Configure workstations to run the local Python script, pointing their LLM calls to the central server's Tailscale IP:
    `http://<central-gpu-server-tailscale-ip>:11434`

---
# Tests
### 🔍 NL-to-SQL Query Results
* **Question:** Show me observations flagged as high
* **Generated SQL:**
  ```sql
  SELECT * FROM observations WHERE flag = 'high'
  ```
* **Result:**
No records found matching query.

---
### 🔍 NL-to-SQL Query Results
* **Question:** Show me any abnormal labs
* **Generated SQL:**
  ```sql
  SELECT * FROM observations WHERE flag != 'N'
  ```
* **Result:**
| observation_id | mrn | test_name | value | unit | flag | timestamp |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | MRN998877 | Cholesterol, Total | 210.0 | mg/dL | H | 2026-06-25 10:30:00 |
| 3 | MRN998877 | Cholesterol in LDL | 125.0 | mg/dL | H | 2026-06-25 10:30:00 |

---
### 🔍 NL-to-SQL Query Results
* **Question:** How many patients records are accessible?
* **Generated SQL:**
  ```sql
  SELECT COUNT(*) FROM patients
  ```
* **Result:**
| COUNT(*) |
| --- |
| 1 |

---
### 🔍 NL-to-SQL Query Results
* **Question:** Show me recent labs for jarecki

> [!NOTE] 📋 Clinical Summary
> Jarecki's recent labs from 2026-06-25 10:30:00 include Total Cholesterol 210.0 mg/dL (H), Triglycerides 150.0 mg/dL (N), LDL Cholesterol 125.0 mg/dL (H), and HDL Cholesterol 45.0 mg/dL (N).

* **Generated SQL:**
  ```sql
  SELECT * FROM observations WHERE mrn = 'MRN998877' ORDER BY timestamp DESC
  ```

#### 📊 Database Records
| observation_id | mrn | test_name | value | unit | flag | timestamp |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | MRN998877 | Cholesterol, Total | 210.0 | mg/dL | H | 2026-06-25 10:30:00 |
| 2 | MRN998877 | Triglycerides | 150.0 | mg/dL | N | 2026-06-25 10:30:00 |
| 3 | MRN998877 | Cholesterol in LDL | 125.0 | mg/dL | H | 2026-06-25 10:30:00 |
| 4 | MRN998877 | Cholesterol in HDL | 45.0 | mg/dL | N | 2026-06-25 10:30:00 |

---
### 🔍 NL-to-SQL Query Results
* **Question:** Did Alex ever have high cholesterol

> [!NOTE] 📋 Clinical Summary
> Yes, Alex Jarecki had a high 'Cholesterol, Total' level of 210.0 mg/dL (flag H) recorded on 2026-06-25.

* **Generated SQL:**
  ```sql
  SELECT
  T1.name,
  T2.test_name,
  T2.value,
  T2.unit,
  T2.flag,
  T2.timestamp
FROM patients AS T1
INNER JOIN observations AS T2
  ON T1.mrn = T2.mrn
WHERE
  T1.mrn = 'MRN998877' AND T2.test_name = 'Cholesterol, Total' AND T2.flag = 'H';
  ```

#### 📊 Database Records
| name | test_name | value | unit | flag | timestamp |
| --- | --- | --- | --- | --- | --- |
| ALEX JARECKI | Cholesterol, Total | 210.0 | mg/dL | H | 2026-06-25 10:30:00 |

---
### 🔍 NL-to-SQL Query Results
* **Question:** What is Eve's glucose level?

> [!NOTE] 📋 Clinical Summary
> No matching clinical records were found in the data lake.

* **Generated SQL:**
  ```sql
  SELECT T2.value FROM patients AS T1 INNER JOIN observations AS T2 ON T1.mrn = T2.mrn WHERE T1.name = 'EVERYWOMAN EVE JONES' AND T2.test_name = 'GLUCOSE POST 12H CFST:MCNC:PT:SER/PLAS:QN' AND T2.flag = 'N'
  ```

#### 📊 Database Records
No records found matching query.

---
### 🔍 NL-to-SQL Query Results
* **Question:** What is Eve's glucose level?

> [!NOTE] 📋 Clinical Summary
> No matching clinical records were found in the data lake.

* **Generated SQL:**
  ```sql
  SELECT T2.value FROM patients AS T1 INNER JOIN observations AS T2 ON T1.mrn = T2.mrn WHERE T1.name = 'Eve' AND T2.test_name = 'GLUCOSE POST 12H CFST:MCNC:PT:SER/PLAS:QN'
  ```

#### 📊 Database Records
No records found matching query.

---
### 🔍 NL-to-SQL Query Results
* **Question:** What is Eve's glucose level?

> [!NOTE] 📋 Clinical Summary
> Eve's glucose level is 182.0 mg/dL.

* **Generated SQL:**
  ```sql
  SELECT T2.value FROM patients AS T1 INNER JOIN observations AS T2 ON T1.mrn = T2.mrn WHERE T1.name = 'EVERYWOMAN EVE JONES' AND T2.test_name = 'GLUCOSE POST 12H CFST:MCNC:PT:SER/PLAS:QN'
  ```

#### 📊 Database Records
| value |
| --- |
| 182.0 |

---
### 🔍 NL-to-SQL Query Results
* **Question:** Who had the highest glucose level and when?

> [!NOTE] 📋 Clinical Summary
> No matching clinical records were found in the data lake.

* **Generated SQL:**
  ```sql
  SELECT p.name, o.timestamp, o.value 
FROM patients p 
JOIN observations o ON p.mrn = o.mrn 
WHERE o.test_name = 'GLUCOSE POST 12H CFST:MCNC:PT:SER/PLAS:QN' AND o.flag = 'H' 
ORDER BY o.value DESC 
LIMIT 1
  ```

#### 📊 Database Records
No records found matching query.

---
### 🔍 NL-to-SQL Query Results
* **Question:** Who had the highest glucose level and when?

> [!NOTE] 📋 Clinical Summary
> EVERYWOMAN EVE JONES had the highest glucose level of 182.0 recorded on 2002-02-15 at 07:30.

* **Generated SQL:**
  ```sql
  SELECT p.name, o.timestamp, o.value 
FROM patients p 
JOIN observations o ON p.mrn = o.mrn 
WHERE o.test_name = 'GLUCOSE POST 12H CFST:MCNC:PT:SER/PLAS:QN' 
ORDER BY o.value DESC 
LIMIT 1
  ```

#### 📊 Database Records
| name | timestamp | value |
| --- | --- | --- |
| EVERYWOMAN EVE JONES | 2002-02-15 07:30 | 182.0 |

---
### 🔍 NL-to-SQL Query Results
* **Question:** Who had the highest glucose level and when?

> [!NOTE] 📋 Clinical Summary
> EVERYWOMAN EVE JONES had the highest glucose level of 182.0 mg/dL on February 15, 2002 at 07:30.

* **Generated SQL:**
  ```sql
  SELECT p.name, o.test_name, o.value, o.unit, o.timestamp 
FROM patients p 
JOIN observations o ON p.mrn = o.mrn 
WHERE o.test_name = 'GLUCOSE POST 12H CFST:MCNC:PT:SER/PLAS:QN' 
ORDER BY o.value DESC 
LIMIT 1
  ```

#### 📊 Database Records
| name                 | test_name                                 | value | unit  | timestamp        |
| -------------------- | ----------------------------------------- | ----- | ----- | ---------------- |
| EVERYWOMAN EVE JONES | GLUCOSE POST 12H CFST:MCNC:PT:SER/PLAS:QN | 182.0 | mg/dl | 2002-02-15 07:30 |

