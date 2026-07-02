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
