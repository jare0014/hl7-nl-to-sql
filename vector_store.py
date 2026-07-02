import os
import re
import json
import sqlite3
import chromadb

# Set up database path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_PATH = os.environ.get("CHROMA_PATH") or os.path.join(SCRIPT_DIR, "chroma_db")
DB_PATH = os.environ.get("HL7_DB_PATH") or os.path.join(SCRIPT_DIR, "hl7_data_lake.db")

# Initialize ChromaDB persistent client
client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(name="hl7_mappings")

def seed_vocabularies():
    """Reads SQLite database values and seeds ChromaDB with semantic mappings."""
    print("Seeding semantic vocabularies into ChromaDB...")
    
    # 1. Clear existing collection elements to ensure a fresh index
    existing_count = collection.count()
    if existing_count > 0:
        # Fetch all IDs to delete
        results = collection.get(include=[])
        if results and "ids" in results:
            collection.delete(ids=results["ids"])
            print(f"Cleared {existing_count} existing records from vector store.")

    documents = []
    metadatas = []
    ids = []
    counter = 0

    # 2. Add Abnormality Flag Synonyms
    flags = [
        # High Flag
        ("high", {"type": "flag", "code": "H", "description": "High"}),
        ("elevated", {"type": "flag", "code": "H", "description": "High"}),
        ("sky high", {"type": "flag", "code": "H", "description": "High"}),
        ("critical high", {"type": "flag", "code": "H", "description": "High"}),
        ("hyper", {"type": "flag", "code": "H", "description": "High"}),
        ("elev", {"type": "flag", "code": "H", "description": "High"}),
        ("above range", {"type": "flag", "code": "H", "description": "High"}),
        ("abnormally high", {"type": "flag", "code": "H", "description": "High"}),
        ("critical elevation", {"type": "flag", "code": "H", "description": "High"}),
        ("crit high", {"type": "flag", "code": "H", "description": "High"}),
        ("abnormal high", {"type": "flag", "code": "H", "description": "High"}),
        # Low Flag
        ("low", {"type": "flag", "code": "L", "description": "Low"}),
        ("decreased", {"type": "flag", "code": "L", "description": "Low"}),
        ("critical low", {"type": "flag", "code": "L", "description": "Low"}),
        ("hypo", {"type": "flag", "code": "L", "description": "Low"}),
        ("lo", {"type": "flag", "code": "L", "description": "Low"}),
        ("below range", {"type": "flag", "code": "L", "description": "Low"}),
        ("abnormally low", {"type": "flag", "code": "L", "description": "Low"}),
        ("critical decrease", {"type": "flag", "code": "L", "description": "Low"}),
        ("crit low", {"type": "flag", "code": "L", "description": "Low"}),
        ("abnormal low", {"type": "flag", "code": "L", "description": "Low"}),
        # Normal Flag
        ("normal", {"type": "flag", "code": "N", "description": "Normal"}),
        ("within range", {"type": "flag", "code": "N", "description": "Normal"}),
        ("healthy", {"type": "flag", "code": "N", "description": "Normal"}),
        ("in range", {"type": "flag", "code": "N", "description": "Normal"}),
        ("wfl", {"type": "flag", "code": "N", "description": "Normal"}),
        ("wnl", {"type": "flag", "code": "N", "description": "Normal"}),
        ("negative", {"type": "flag", "code": "N", "description": "Normal"})
    ]
    for text, meta in flags:
        documents.append(text)
        metadatas.append(meta)
        ids.append(f"flag_{counter}")
        counter += 1

    # 3. Add Gender Synonyms
    genders = [
        ("male", {"type": "gender", "code": "M"}),
        ("man", {"type": "gender", "code": "M"}),
        ("boy", {"type": "gender", "code": "M"}),
        ("gentleman", {"type": "gender", "code": "M"}),
        ("female", {"type": "gender", "code": "F"}),
        ("woman", {"type": "gender", "code": "F"}),
        ("girl", {"type": "gender", "code": "F"}),
        ("lady", {"type": "gender", "code": "F"}),
        ("unknown sex", {"type": "gender", "code": "U"}),
        ("other gender", {"type": "gender", "code": "U"}),
        ("unknown", {"type": "gender", "code": "U"}),
        ("other", {"type": "gender", "code": "U"}),
        ("unspecified", {"type": "gender", "code": "U"})
    ]
    for text, meta in genders:
        documents.append(text)
        metadatas.append(meta)
        ids.append(f"gender_{counter}")
        counter += 1

    # 4. Fetch and Index Patients dynamically from SQLite
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT mrn, name FROM patients;")
            for mrn, name in cursor.fetchall():
                # Add patient name variations
                # e.g., "ALEX JARECKI"
                documents.append(name.lower())
                metadatas.append({"type": "patient", "mrn": mrn, "name": name})
                ids.append(f"patient_name_{counter}")
                counter += 1
                
                # e.g., just the last name "jarecki"
                last_name = name.split(",")[-1].strip().lower() if "," in name else name.split()[-1].strip().lower()
                documents.append(last_name)
                metadatas.append({"type": "patient", "mrn": mrn, "name": name})
                ids.append(f"patient_last_{counter}")
                counter += 1

                # e.g., just the first name "alex"
                first_name = name.split(",")[0].strip().lower() if "," in name else name.split()[0].strip().lower()
                if first_name != last_name:
                    documents.append(first_name)
                    metadatas.append({"type": "patient", "mrn": mrn, "name": name})
                    ids.append(f"patient_first_{counter}")
                    counter += 1
                    
                # Index all individual alphanumeric name parts (captures middle names, caret separations, etc.)
                name_parts = re.split(r'[^a-zA-Z0-9]', name)
                for part in name_parts:
                    part_lower = part.strip().lower()
                    if len(part_lower) > 1 and part_lower not in [first_name, last_name, name.lower()]:
                        documents.append(part_lower)
                        metadatas.append({"type": "patient", "mrn": mrn, "name": name})
                        ids.append(f"patient_token_{counter}")
                        counter += 1
                
            # 5. Fetch and Index Unique Test Names & Synonyms
            TEST_SYNONYMS = {
                "cholesterol, total": ["total cholesterol", "tc", "chol", "tchol", "cholesterol"],
                "cholesterol in ldl": ["ldl", "ldl-c", "bad cholesterol", "ldl cholesterol", "low density lipoprotein"],
                "cholesterol in hdl": ["hdl", "hdl-c", "good cholesterol", "hdl cholesterol", "high density lipoprotein"],
                "triglycerides": ["trigs", "tg", "triglyceride", "tri"],
                "glucose": ["blood sugar", "glu", "bs", "bg", "glucose", "blood glucose", "sugar", "glucose levels"]
            }

            cursor.execute("SELECT DISTINCT test_name FROM observations;")
            for (test_name,) in cursor.fetchall():
                documents.append(test_name.lower())
                metadatas.append({"type": "test_name", "value": test_name})
                ids.append(f"test_name_{counter}")
                counter += 1
                
                # Strip out common separators for short variations
                short_name = test_name.replace(",", "").replace("-", "").lower()
                if short_name != test_name.lower():
                    documents.append(short_name)
                    metadatas.append({"type": "test_name", "value": test_name})
                    ids.append(f"test_short_{counter}")
                    counter += 1
                
                # Dynamic matching of synonyms
                cleaned_test_key = test_name.lower().strip()
                for key, synonyms in TEST_SYNONYMS.items():
                    if key in cleaned_test_key or cleaned_test_key in key:
                        for syn in synonyms:
                            if syn not in documents:
                                documents.append(syn)
                                metadatas.append({"type": "test_name", "value": test_name})
                                ids.append(f"test_syn_{counter}")
                                counter += 1
                    
            conn.close()
        except Exception as e:
            print(f"Error querying SQLite for vocabulary seeding: {e}")

    # 5. Push to ChromaDB
    if documents:
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"Successfully indexed {len(documents)} terms in ChromaDB.")
    else:
        print("No terms found to index.")

def resolve_semantic_terms(query, n_results=3):
    """Queries ChromaDB by tokenizing the input query, applying typo tolerance, and grouping resolved mappings by type."""
    # 1. Fetch all documents from Chroma for fuzzy matching
    try:
        all_docs_results = collection.get(include=["documents"])
        all_docs = list(set(all_docs_results.get("documents", []))) if all_docs_results else []
    except Exception as e:
        print(f"Warning: Could not fetch documents from ChromaDB for fuzzy matching: {e}")
        all_docs = []

    # Build individual word possibilities for multi-word phrases to enable word-by-word correction
    fuzzy_possibilities = set()
    for doc in all_docs:
        fuzzy_possibilities.add(doc)
        if " " in doc:
            for word in re.findall(r'\b\w+\b', doc):
                if len(word) > 1:
                    fuzzy_possibilities.add(word)
    fuzzy_possibilities_list = list(fuzzy_possibilities)

    # Clean the query and split into words
    words = re.findall(r'\b\w+\b', query.lower())
    
    # Filter out common SQL and English stop words to reduce noise
    stop_words = {
        # Query/SQL-specific terms
        "show", "me", "find", "get", "list", "query", "run", "all", "any", "the", "a", "an",
        "of", "for", "in", "on", "at", "to", "with", "where", "having", "select", "from",
        "who", "whose", "patient", "patients", "test", "tests", "observation", "observations",
        "result", "results", "value", "values", "flag", "flags", "is", "are", "was", "were",
        "check", "if", "or", "and",
        # Mathematical / Superlative terms to prevent fuzzy-matching them as flags
        "highest", "lowest", "max", "min", "maximum", "minimum", "largest", "smallest",
        "least", "first", "last", "latest", "earliest", "newest", "oldest", "recent",
        # Common pronouns & articles
        "i", "you", "he", "she", "it", "we", "they", "them", "him", "her", "us", "my", "your",
        "his", "its", "our", "their", "this", "that", "these", "those", "here", "there", "which",
        "what", "how", "why", "when", "who", "whom",
        # Prepositions & Conjunctions
        "about", "above", "across", "after", "against", "along", "among", "around", "at",
        "before", "behind", "below", "beneath", "beside", "between", "beyond", "but", "by",
        "concerning", "despite", "down", "during", "except", "following", "for", "from",
        "in", "inside", "into", "like", "near", "of", "off", "on", "onto", "out", "outside",
        "over", "past", "regarding", "since", "through", "throughout", "till", "to", "toward",
        "under", "underneath", "until", "up", "upon", "with", "within", "without",
        # Verbs & Auxiliaries
        "be", "been", "being", "have", "has", "had", "do", "does", "did", "can", "could",
        "shall", "should", "will", "would", "may", "might", "must",
        # Adverbs & Others
        "already", "also", "always", "anyway", "back", "else", "even", "ever", "hence",
        "just", "maybe", "more", "most", "much", "no", "not", "only", "other", "so", "some",
        "still", "such", "than", "then", "thereby", "therefore", "too", "very", "well", "yet"
    }
    
    tokens = [w for w in words if w not in stop_words and len(w) > 1]
    
    # Apply fuzzy matching to correct typos in tokens
    import difflib
    corrected_tokens = []
    for token in tokens:
        if token in fuzzy_possibilities:
            corrected_tokens.append(token)
        else:
            matches = difflib.get_close_matches(token, fuzzy_possibilities_list, n=1, cutoff=0.7)
            if matches:
                print(f"Fuzzy corrected: '{token}' -> '{matches[0]}'")
                corrected_tokens.append(matches[0])
            else:
                corrected_tokens.append(token)

    # If no tokens are left, fallback to querying the whole sentence
    if not corrected_tokens:
        corrected_tokens = [query]
        
    # Query ChromaDB with all corrected tokens
    results = collection.query(
        query_texts=corrected_tokens,
        n_results=n_results
    )
    
    resolved = {
        "patients": [],
        "flags": [],
        "test_names": [],
        "genders": []
    }
    
    if not results or not results["metadatas"]:
        return resolved

    seen_mrns = set()
    seen_flags = set()
    seen_tests = set()
    seen_genders = set()
    
    # results["metadatas"] is a list of lists (one list per query token)
    for token_idx, metadatas in enumerate(results["metadatas"]):
        distances = results["distances"][token_idx] if "distances" in results else [0.0] * len(metadatas)
        documents = results["documents"][token_idx]
        
        for meta, dist, doc in zip(metadatas, distances, documents):
            # Since these are single-token comparisons, we want a strict distance threshold.
            # cosine distance < 0.6 is an excellent filter for direct semantic hits.
            if dist > 0.6:
                continue
                
            m_type = meta.get("type")
            
            if m_type == "patient":
                mrn = meta.get("mrn")
                if mrn not in seen_mrns:
                    resolved["patients"].append({"mrn": mrn, "name": meta.get("name"), "matched_term": doc})
                    seen_mrns.add(mrn)
                    
            elif m_type == "flag":
                code = meta.get("code")
                if code not in seen_flags:
                    resolved["flags"].append({"code": code, "description": meta.get("description"), "matched_term": doc})
                    seen_flags.add(code)
                    
            elif m_type == "test_name":
                val = meta.get("value")
                if val not in seen_tests:
                    resolved["test_names"].append({"value": val, "matched_term": doc})
                    seen_tests.add(val)
                    
            elif m_type == "gender":
                code = meta.get("code")
                if code not in seen_genders:
                    resolved["genders"].append({"code": code, "matched_term": doc})
                    seen_genders.add(code)
                
    return resolved

if __name__ == "__main__":
    # Test seeding and lookup
    seed_vocabularies()
    
    print("\n--- Testing Search ---")
    test_query = "Show me elevated lipid panel results for Jarecki"
    print(f"Query: '{test_query}'")
    matches = resolve_semantic_terms(test_query)
    print(json.dumps(matches, indent=2))

    print("\n--- Testing Synonyms and Typos ---")
    test_query_2 = "Is there abnormally high cholsterol or glukose for alex?"
    print(f"Query: '{test_query_2}'")
    matches_2 = resolve_semantic_terms(test_query_2)
    print(json.dumps(matches_2, indent=2))

