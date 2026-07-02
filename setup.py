import os
import sys
import subprocess
import getpass

def run_cmd(cmd, cwd=None):
    try:
        subprocess.run(cmd, shell=True, check=True, cwd=cwd)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running command '{cmd}': {e}")
        return False

def main():
    print("==================================================")
    # 1. Setup Virtual Environment
    print("Step 1: Setting up Python Virtual Environment...")
    venv_dir = ".venv"
    if not os.path.isdir(venv_dir):
        print("Creating virtual environment...")
        if not run_cmd(f"{sys.executable} -m venv {venv_dir}"):
            print("Failed to create venv. Make sure python is on PATH.")
            sys.exit(1)
        print("Virtual environment created.")
    else:
        print("Virtual environment already exists.")

    # 2. Install dependencies
    print("\nStep 2: Installing dependencies from requirements.txt...")
    pip_bin = os.path.join(venv_dir, "Scripts", "pip.exe") if os.name == "nt" else os.path.join(venv_dir, "bin", "pip")
    if not os.path.exists(pip_bin):
        print(f"Failed to find pip binary: {pip_bin}")
        sys.exit(1)

    if not run_cmd(f'"{pip_bin}" install -r requirements.txt'):
        print("Failed to install dependencies.")
        sys.exit(1)
    print("Dependencies installed successfully.")

    # 3. Configure Keychain Credentials
    print("\nStep 3: Configuring Google Gemini API Key in OS Keychain...")
    # Import keyring using the venv interpreter (since it may not be in global python)
    python_bin = os.path.join(venv_dir, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv_dir, "bin", "python")
    
    gemini_key = getpass.getpass("Enter your Google Gemini API Key: ").strip()
    if gemini_key:
        # Write to keyring via a one-off python command run inside the venv
        keyring_cmd = f'"{python_bin}" -c "import keyring; keyring.set_password(\\\"hl7-nl-to-sql\\\", \\\"gemini_api_key\\\", \\\"{gemini_key}\\\")"'
        if run_cmd(keyring_cmd):
            print("Gemini API Key stored securely in OS Keychain under service 'hl7-nl-to-sql'!")
        else:
            print("Failed to store API Key in OS Keychain.")
    else:
        print("No API key entered. Skipping credential setup.")

    print("\nSetup Complete! You can run queries using .venv/Scripts/python.")
    print("==================================================")

if __name__ == "__main__":
    main()
