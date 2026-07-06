import os
import sys
import re
import json
import sqlite3
import requests

# 1. Paths and Setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("HL7_DB_PATH") or os.path.join(SCRIPT_DIR, "hl7_data_lake.db")
VAULT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OMNI_LOGGER_DIR = os.path.join(VAULT_DIR, ".obsidian", "plugins", "omni-logger")

# 1. API key loading
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    try:
        import keyring
        GEMINI_API_KEY = keyring.get_password("hl7-nl-to-sql", "gemini_api_key")
    except Exception:
        pass

# Fallback API key loading
if not GEMINI_API_KEY and os.path.exists(OMNI_LOGGER_DIR):
    sys.path.append(OMNI_LOGGER_DIR)
    try:
        from log_calls import get_gemini_key
        GEMINI_API_KEY = get_gemini_key()
    except Exception:
        pass

def load_settings():
    """Loads settings from the omni-logger plugin to respect user configurations."""
    if os.path.exists(OMNI_LOGGER_DIR):
        settings_path = os.path.join(OMNI_LOGGER_DIR, "data.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

def call_llm(prompt):
    """Calls either Gemini or Ollama depending on the omni-logger plugin configuration."""
    settings = load_settings()
    
    # Determine provider: env variable first, then OLLAMA_HOST detection, then settings
    provider = os.environ.get("LLM_PROVIDER")
    if not provider:
        if os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_URL"):
            provider = "ollama"
        else:
            provider = settings.get("templateProvider", "gemini").lower()
    else:
        provider = provider.lower()
    
    if provider == "ollama":
        ollama_url = os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_URL") or settings.get("ollamaUrl", "http://localhost:11434")
        ollama_url = ollama_url.rstrip("/")
        if not ollama_url.startswith(("http://", "https://")):
            ollama_url = f"http://{ollama_url}"
        host_part = ollama_url.split("://")[-1]
        if ":" not in host_part:
            ollama_url = f"{ollama_url}:11434"
        url = f"{ollama_url}/v1/chat/completions"
        model_name = os.environ.get("OLLAMA_MODEL") or settings.get("executorModel") or settings.get("customExecutorModel") or "qwen2.5-coder:7b"
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0
        }
        res = requests.post(url, json=payload, timeout=300)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"].strip()
    else:
        # Default to Gemini
        if not GEMINI_API_KEY:
            raise ValueError("Gemini API Key not set. Configure it in Obsidian or set GEMINI_API_KEY environment variable.")
        
        model = settings.get("templateModel", "gemini-2.5-flash") or "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

def get_schema_ddl():
    """Extracts SQL table creation DDL from SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall() if row[0] is not None]
    conn.close()
    return "\n\n".join(tables)

def execute_sql(sql):
    """Executes SQL against database and formats results as a markdown table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        if cursor.description is None:
            conn.commit()
            return "Query executed successfully. No rows returned.", [], []
            
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        if not rows:
            return "No records found matching query.", [], []
            
        # Format markdown table
        lines = []
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(val) if val is not None else "NULL" for val in row) + " |")
        return "\n".join(lines), rows, columns
    except Exception as e:
        return f"Database Error: {e}", [], []
    finally:
        conn.close()

def generate_clinical_summary(question, sql, rows, columns):
    """Generates a grounded natural language summary of the query results."""
    if not rows:
        return "No matching clinical records were found in the data lake."
        
    # Format rows for LLM context
    rows_text = []
    for r in rows:
        rows_text.append(", ".join(f"{col}: {val}" for col, val in zip(columns, r)))
    results_string = "\n".join(rows_text)
    
    prompt = f"""
    You are a clinical data assistant. Given a clinician's question, the translated SQL query, and the matching database results from the patient data lake, synthesize a brief, professional natural language summary that directly answers the question.
    
    Instructions:
    1. Write in a clear, concise, objective, and professional tone suitable for a clinical dashboard.
    2. Focus on the core clinical numbers, test names, and abnormality flags.
    3. Ground your summary STRICTLY in the provided database results. Do not extrapolate, assume external details, or offer medical advice.
    
    Clinician's Question:
    {question}
    
    Translated SQL Query:
    {sql}
    
    Query Results:
    {results_string}
    
    Write a concise summary (1-3 sentences) answering the question:
    """
    try:
        summary = call_llm(prompt).strip()
        return summary
    except Exception as e:
        return f"Error synthesizing clinical summary: {e}"

def process_file_query(file_path):
    """Reads frontmatter, extracts query, runs translation/execution, and writes back."""
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        return
        
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Parse Frontmatter robustly (ignoring BOM and spaces)
    content_clean = content.lstrip("\ufeff").lstrip()
    if not content_clean.startswith("---"):
        print("Error: Markdown file has no frontmatter (doesn't start with ---).")
        return
        
    parts = content_clean.split("---", 2)
    if len(parts) < 3:
        print("Error: Markdown file has no frontmatter (incomplete delimiters).")
        return
        
    frontmatter_text = parts[1].strip()
    body_text = parts[2]
    
    # Parse YAML fields simply
    fm_lines = frontmatter_text.splitlines()
    nl_query = ""
    query_line_idx = -1
    
    for idx, line in enumerate(fm_lines):
        if line.startswith("nl_query:"):
            nl_query = line.replace("nl_query:", "", 1).strip()
            # Remove enclosing quotes if present
            if (nl_query.startswith('"') and nl_query.endswith('"')) or (nl_query.startswith("'") and nl_query.endswith("'")):
                nl_query = nl_query[1:-1]
            query_line_idx = idx
            break
            
    if not nl_query:
        print("No active natural language query found in frontmatter.")
        return
        
    print(f"Processing query: '{nl_query}'")
    
    # Resolve semantic mappings from ChromaDB
    mappings = {}
    try:
        import vector_store
        # Re-seed to capture any new records inserted
        vector_store.seed_vocabularies()
        mappings = vector_store.resolve_semantic_terms(nl_query)
        print("Resolved semantic terms from ChromaDB:", json.dumps(mappings))
    except Exception as e:
        print(f"Warning: Semantic search resolution bypassed/failed: {e}")

    # Build context block from mappings
    context_lines = []
    if mappings.get("patients"):
        context_lines.append("Patients matched:")
        for p in mappings["patients"]:
            context_lines.append(f"- \"{p['matched_term']}\" maps to Patient MRN '{p['mrn']}' (Name: '{p['name']}')")
    if mappings.get("flags"):
        context_lines.append("Abnormality flags matched:")
        for f in mappings["flags"]:
            context_lines.append(f"- \"{f['matched_term']}\" maps to flag = '{f['code']}' (Description: '{f['description']}')")
    if mappings.get("test_names"):
        context_lines.append("Lab test names matched:")
        for t in mappings["test_names"]:
            context_lines.append(f"- \"{t['matched_term']}\" maps to test_name = '{t['value']}'")
    if mappings.get("genders"):
        context_lines.append("Genders matched:")
        for g in mappings["genders"]:
            context_lines.append(f"- \"{g['matched_term']}\" maps to gender = '{g['code']}'")
            
    context_block = "\n".join(context_lines) if context_lines else "No direct database mappings resolved."

    # Translate query to SQL
    schema = get_schema_ddl()
    prompt = f"""
    You are an expert SQLite translator. Given the following database schema, write a SQL query that answers the user's question.
    
    Schema:
    {schema}
    
    Resolved Database Mappings (Use these exact codes and values in your SQL query constraints):
    {context_block}
    
    Column Value Domains:
    - observations.flag: This column uses abbreviations for abnormality flags:
      * 'H' represents High. If the user asks for 'high' or 'elevated' values, query for flag = 'H'.
      * 'L' represents Low. If the user asks for 'low' or 'decreased' values, query for flag = 'L'.
      * 'N' represents Normal. If the user asks for 'normal' values, query for flag = 'N'.
    - patients.gender: This column uses abbreviations for administrative sex:
      * 'M' represents Male/man/boy.
      * 'F' represents Female/woman/girl.
      * 'U' represents Unknown/Other.
    
    User Question:
    {nl_query}
    
    Instructions:
    1. Generate SQLite compatible SQL.
    2. Output ONLY the raw SQL code. Do not include markdown code fences (like ```sql), explanations, or introductory text. Just the executable SQL string.
    3. Do NOT add filters or constraints on the 'flag' or 'gender' columns unless they are explicitly resolved and listed in the "Resolved Database Mappings" block above. For example, if the user asks for "highest" or "maximum", do not filter by flag = 'H' unless 'flag = H' is explicitly resolved in the mappings. Instead, use mathematical aggregates (MAX, MIN) or sorting (ORDER BY ... DESC LIMIT 1) to find superlatives.
    """
    
    try:
        sql = call_llm(prompt).strip()
        sql = sql.replace("```sql", "").replace("```", "").strip()
    except Exception as e:
        print(f"LLM Error: {e}")
        return
        
    # Execute SQL
    results_markdown, rows, columns = execute_sql(sql)
    
    # Generate clinical summary
    clinical_summary = generate_clinical_summary(nl_query, sql, rows, columns)
    
    # Append results block to the body with Callout styling
    new_results_block = f"""
---
### 🔍 NL-to-SQL Query Results
* **Question:** {nl_query}

> [!NOTE] 📋 Clinical Summary
> {clinical_summary}

* **Generated SQL:**
  ```sql
  {sql}
  ```

#### 📊 Database Records
{results_markdown}
"""
    
    body_text = body_text.rstrip() + "\n" + new_results_block + "\n"
    
    # Clear the query in frontmatter
    if query_line_idx != -1:
        fm_lines[query_line_idx] = "nl_query: \"\""
    else:
        fm_lines.append("nl_query: \"\"")
        
    updated_frontmatter = "\n".join(fm_lines)
    updated_content = f"---\n{updated_frontmatter}\n---\n{body_text}"
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(updated_content)
        
    print("Success: Appended results to note and cleared input.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python query_lake_obsidian.py <absolute_note_path>")
        sys.exit(1)
        
    note_path = sys.argv[1]
    process_file_query(note_path)
