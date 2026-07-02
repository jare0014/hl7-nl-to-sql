import sqlite3
import sys

DB_PATH = "hl7_data_lake.db"

def run_query(sql):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        if cursor.description is None:
            conn.commit()
            print("Query executed successfully. No rows returned.")
            return
            
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        if not rows:
            print("No records found.")
            return
            
        # Print as markdown table
        print("| " + " | ".join(columns) + " |")
        print("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in rows:
            print("| " + " | ".join(str(val) if val is not None else "NULL" for val in row) + " |")
            
    except Exception as e:
        print(f"SQL Error: {e}", file=sys.stderr)
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_sql.py \"<SQL QUERY>\"")
        sys.exit(1)
        
    query = sys.argv[1]
    run_query(query)
