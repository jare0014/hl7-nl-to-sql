import os
import urllib.request
import json

# Setup local output directory
OUTPUT_DIR = "samples"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# List of raw files we want to pull from the bqfan/sample-hl7-messages repository
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/bqfan/sample-hl7-messages/main/"

FILES_TO_PULL = {
    "ORU": [
        "hl7-samples-main/ORU/1632738119.txt",
        "hl7-samples-main/ORU/1632738156.txt",
        "hl7-samples-main/ORU/1632738559-R01.txt"
    ],
    "ADT": [
        "hl7-samples-main/ADT/1632738177-A01.txt",
        "hl7-samples-main/ADT/1632738187-A02.txt",
        "hl7-samples-main/ADT/1632738204-A03.txt",
        "hl7-samples-main/ADT/1632738228-A04.txt",
        "hl7-samples-main/ADT/1632738325-A05.txt",
        "hl7-samples-main/ADT/1632738347-A08.txt",
        "hl7-samples-main/ADT/1632738363-A11.txt",
        "hl7-samples-main/ADT/1632738375-A12.txt",
        "hl7-samples-main/ADT/1632738390-A13.txt",
        "hl7-samples-main/ADT/1632738539-A04.txt"
    ]
}

def pull_files():
    print("Starting download of mock HL7 v2 messages from GitHub...")
    
    for category, paths in FILES_TO_PULL.items():
        cat_dir = os.path.join(OUTPUT_DIR, category)
        os.makedirs(cat_dir, exist_ok=True)
        
        for path in paths:
            filename = os.path.basename(path)
            url = GITHUB_RAW_BASE + path
            dest = os.path.join(cat_dir, filename)
            
            print(f"Downloading {category}/{filename}...")
            try:
                urllib.request.urlretrieve(url, dest)
            except Exception as e:
                print(f"Failed to download {filename}: {e}")
                
    print(f"\nSuccess! Mock HL7 messages saved to local folder: ./{OUTPUT_DIR}/")

if __name__ == "__main__":
    pull_files()
