import os
import subprocess
import sys
import site

packages = [
    "azure-storage-blob",
    "azure-core",
    "azure-search-documents",
    "PyMuPDF",
    "beautifulsoup4",
    "selenium",
    "webdriver_manager",
    "python-dotenv"
]

def install_packages(packages):
    for package in packages:
        try:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except subprocess.CalledProcessError as e:
            print(f"Error installing {package}: {e}")
    print("Package installation complete.")

def add_site_packages_to_path():
    paths = site.getsitepackages()
    current_path = os.environ.get("PATH", "")
    for p in paths:
        # Check if the path is already present
        if p.lower() not in current_path.lower():
            print(f"Adding {p} to PATH...")
            subprocess.check_call(f'setx PATH "%PATH%;{p}"', shell=True)
        else:
            print(f"{p} is already in PATH.")
    print("Finished updating PATH.")

if __name__ == "__main__":
    install_packages(packages)
    add_site_packages_to_path()
