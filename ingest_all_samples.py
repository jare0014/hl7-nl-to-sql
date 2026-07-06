import os
import sys
import json
import sqlite3
import requests
import time

# Set up paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("HL7_DB_PATH") or os.path.join(SCRIPT_DIR, "hl7_data_lake.db")
SAMPLES_DIR = os.path.join(SCRIPT_DIR, "samples")
VAULT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OMNI_LOGGER_DIR = os.path.join(VAULT_DIR, ".obsidian", "plugins", "omni-logger")

# 1. Load Gemini API Key
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
    if os.path.exists(OMNI_LOGGER_DIR):
        settings_path = os.path.join(OMNI_LOGGER_DIR, "data.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

def call_llm(prompt, json_format=False):
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
        if json_format:
            payload["response_format"] = {"type": "json_object"}
        res = requests.post(url, json=payload, timeout=300)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"].strip()
    else:
        if not GEMINI_API_KEY:
            raise ValueError("Gemini API Key not set. Configure it in Obsidian or set GEMINI_API_KEY environment variable.")
        
        model = settings.get("templateModel", "gemini-2.5-flash") or "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        if json_format:
            payload["generationConfig"] = {"responseMimeType": "application/json"}
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

def clean_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    if text.startswith("json\n"):
        text = text[5:].strip()
    return text

def ingest_message(content, filename):
    print(f"Ingesting: {filename}...")
    
    prompt = f"""
    You are an expert clinical database ingestion system. Parse the following raw HL7 message and convert it to structured JSON.
    
    HL7 Message:
    {content}
    
    Return your response strictly as a JSON object matching this schema. Even if the message is an ADT message (with no observations), return empty observations array:
    {{
      "mrn": "patient MRN",
      "patient_name": "patient full name",
      "dob": "YYYY-MM-DD",
      "gender": "M/F/U",
      "results": [
        {{
          "test_name": "name of the test",
          "value": 12.3,
          "unit": "measurement unit",
          "flag": "H/L/N/etc",
          "timestamp": "YYYY-MM-DD HH:MM:SS"
        }}
      ]
    }}
    """
    try:
        response_text = call_llm(prompt, json_format=True)
        cleaned = clean_json_response(response_text)
        data = json.loads(cleaned)
        
        # Sanitize parsed fields to prevent list-binding errors
        mrn = data.get("mrn")
        if isinstance(mrn, list):
            mrn = mrn[0] if mrn else ""
        mrn = str(mrn) if mrn is not None else ""
        
        name = data.get("patient_name") or data.get("name")
        if isinstance(name, list):
            name = name[0] if name else ""
        name = str(name) if name is not None else ""
        
        dob = data.get("dob")
        if isinstance(dob, list):
            dob = dob[0] if dob else ""
        dob = str(dob) if dob is not None else ""
        
        gender = data.get("gender")
        if isinstance(gender, list):
            gender = gender[0] if gender else ""
        gender = str(gender) if gender is not None else ""
        
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            # Insert Patient
            cursor.execute("""
            INSERT INTO patients (mrn, name, dob, gender)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mrn) DO UPDATE SET
                name=excluded.name,
                dob=excluded.dob,
                gender=excluded.gender;
            """, (mrn, name, dob, gender))
            
            # Insert Observations if present
            for obs in data.get("results", []):
                # Check for empty observation blocks
                if not obs.get("test_name"):
                    continue
                val = obs.get("value")
                if isinstance(val, (list, dict)):
                    val = str(val)
                cursor.execute("""
                INSERT INTO observations (mrn, test_name, value, unit, flag, timestamp)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (mrn, obs.get("test_name"), val, obs.get("unit"), obs.get("flag"), obs.get("timestamp")))
                
            conn.commit()
            print(f"Successfully processed {filename} for patient {name}.")
        finally:
            conn.close()
    except Exception as e:
        print(f"Error processing {filename}: {e}")
        try:
            print(f"Raw response: {response_text[:500]}...")
        except NameError:
            pass

def run_batch_ingest():
    if not os.path.exists(SAMPLES_DIR):
        print(f"Error: Samples directory '{SAMPLES_DIR}' does not exist. Run pull_samples.py first.")
        return
        
    # Clear patients and observations to prevent duplicate data on re-run
    print("Clearing database tables for fresh batch ingestion...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM observations;")
        cursor.execute("DELETE FROM patients;")
        conn.commit()
        conn.close()
        print("Database cleared successfully.")
    except Exception as e:
        print(f"Warning: Could not clear database: {e}")

    # Check provider to determine rate limit sleep
    settings = load_settings()
    provider = settings.get("templateProvider", "gemini").lower()
    is_ollama = (provider == "ollama")

    # Scan subdirectories
    categories = ["ADT", "ORU"]
    for cat in categories:
        cat_path = os.path.join(SAMPLES_DIR, cat)
        if not os.path.exists(cat_path):
            continue
            
        files = [f for f in os.listdir(cat_path) if f.endswith(".txt")]
        print(f"\nProcessing {len(files)} files in category: {cat}")
        
        for f in files:
            file_path = os.path.join(cat_path, f)
            with open(file_path, "r", encoding="utf-8") as file_content:
                content = file_content.read()
            ingest_message(content, f"{cat}/{f}")
            # Rate limit guard (only required for public API like Gemini)
            if not is_ollama:
                time.sleep(5)
            
    # Re-seed ChromaDB vector search vocabularies
    try:
        import vector_store
        vector_store.seed_vocabularies()
        print("\nAll database vocabularies successfully re-seeded in ChromaDB.")
    except Exception as e:
        print(f"\nWarning: Could not seed ChromaDB: {e}")

if __name__ == "__main__":
    run_batch_ingest()
