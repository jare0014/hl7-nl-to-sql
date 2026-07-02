import os
import sys
import json
import sqlite3
import requests

# 1. Add omni-logger to system path to reuse get_gemini_key
try:
    vault_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    omni_logger_path = os.path.join(vault_dir, ".obsidian", "plugins", "omni-logger")
    sys.path.append(omni_logger_path)
    from log_calls import get_gemini_key
    GEMINI_API_KEY = get_gemini_key()
except Exception as e:
    print(f"Warning: Could not automatically load Gemini API key from omni-logger: {e}")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

DB_PATH = "hl7_data_lake.db"

def init_db():
    """Initializes a clean SQLite data lake for HL7 observation data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create Patients Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
        mrn TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        dob TEXT,
        gender TEXT
    );
    """)
    
    # Create Observations Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS observations (
        observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        mrn TEXT NOT NULL,
        test_name TEXT NOT NULL,
        value REAL,
        unit TEXT,
        flag TEXT,
        timestamp TEXT,
        FOREIGN KEY (mrn) REFERENCES patients(mrn)
    );
    """)
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def call_gemini(prompt, response_mime_type="text/plain"):
    """Queries Gemini 3.5 Flash using the user's vault API key."""
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key is not set. Please set the GEMINI_API_KEY environment variable or configure it in omni-logger.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    
    if response_mime_type == "application/json":
        payload["generationConfig"] = {"responseMimeType": "application/json"}
        
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    res.raise_for_status()
    res_data = res.json()
    return res_data["candidates"][0]["content"]["parts"][0]["text"].strip()

def ingest_hl7(raw_hl7):
    """Parses raw HL7 message via Gemini and inserts it into the database."""
    print("\n[Ingest] Parsing HL7 message with Gemini...")
    prompt = f"""
    You are a clinical database ingestion system. Parse the following raw HL7 message into structured JSON.
    
    HL7 Message:
    {raw_hl7}
    
    Return your response strictly as a JSON object matching this schema:
    {{
      "mrn": "patient MRN",
      "patient_name": "patient full name",
      "dob": "YYYY-MM-DD",
      "gender": "M/F",
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
    
    response_text = call_gemini(prompt, response_mime_type="application/json")
    data = json.loads(response_text)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Insert or update patient
    cursor.execute("""
    INSERT INTO patients (mrn, name, dob, gender)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(mrn) DO UPDATE SET
        name=excluded.name,
        dob=excluded.dob,
        gender=excluded.gender;
    """, (data["mrn"], data["patient_name"], data["dob"], data["gender"]))
    
    # Insert observations
    for obs in data["results"]:
        cursor.execute("""
        INSERT INTO observations (mrn, test_name, value, unit, flag, timestamp)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (data["mrn"], obs["test_name"], obs["value"], obs["unit"], obs["flag"], obs["timestamp"]))
        
    conn.commit()
    conn.close()
    print(f"Successfully ingested lab results for patient {data['patient_name']} (MRN: {data['mrn']}).")

def get_schema_ddl():
    """Returns the SQL DDL statements for the database tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall() if row[0] is not None]
    conn.close()
    return "\n\n".join(tables)

def query_database_nl(question):
    """Generates a SQL query from natural language, executes it, and displays results."""
    print(f"\n[Query] Translating Question: '{question}'")
    schema = get_schema_ddl()
    
    prompt = f"""
    You are an expert SQLite translator. Given the following database schema, write a SQL query that answers the user's question.
    
    Schema:
    {schema}
    
    User Question:
    {question}
    
    Instructions:
    1. Generate SQLite compatible SQL.
    2. Output ONLY the raw SQL code. Do not include markdown code fences (like ```sql), markdown blocks, explanations, or introductory text. Just the executable SQL string.
    """
    
    sql = call_gemini(prompt).strip()
    # Clean up any accidental formatting
    sql = sql.replace("```sql", "").replace("```", "").strip()
    
    print(f"Generated SQL:\n  {sql}\n")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        # Display nicely
        if not rows:
            print("Result: No records found matching query.")
            return
            
        print("Query Results:")
        col_header = " | ".join(cols)
        print(col_header)
        print("-" * len(col_header))
        for row in rows:
            print(" | ".join(str(val) for val in row))
            
    except Exception as e:
        print(f"Database Error running query: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    # Test message
    mock_hl7 = (
        "MSH|^~\\&|CLINICAL_SYSTEM|HOSPITAL_A|REC_SYSTEM|REC_FACILITY|20260625145100||ORU^R01^ORU_R01|MSG00001|P|2.5\n"
        "PID|1||MRN998877^^^HOSPITAL_A^MR||JARECKI^ALEX||19920515|M|||123 ELM ST^APT 4B^MINNEAPOLIS^MN^55401||555-0199|||S||||||\n"
        "PV1|1|O|OUTPATIENT_CLINIC||||12345^SMITH^JOHN^M^^Dr||||||||||||||||||||||||||||||||||||20260625090000\n"
        "OBR|1|REQ112233|FILT445566|24331-1^Lipid Panel^LN|||20260625091500|||||||||12345^SMITH^JOHN^M^^Dr||||||20260625103000|||F\n"
        "OBX|1|NM|2093-3^Cholesterol, Total^LN||210|mg/dL|<200|H|||F|||20260625103000\n"
        "OBX|2|NM|2571-8^Triglycerides^LN||150|mg/dL|<150|N|||F|||20260625103000\n"
        "OBX|3|NM|18262-6^Cholesterol in LDL^LN||125|mg/dL|<100|H|||F|||20260625103000\n"
        "OBX|4|NM|2085-9^Cholesterol in HDL^LN||45|mg/dL|>40|N|||F|||20260625103000"
    )

    init_db()
    ingest_hl7(mock_hl7)
    
    # Run a test NL-to-SQL query
    query_database_nl("Find all patients who have any lab values flagged with 'H'")
    query_database_nl("Show the average cholesterol (Total and LDL) for patient ALEX JARECKI")
