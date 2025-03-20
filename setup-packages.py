import os
import subprocess
import sys
import site

packages = [
    "azure-storage-blob==12.14.0",
    "azure-core==1.31.0",
    "azure-identity",
    "azure-search-documents==11.5.2",
    "PyMuPDF==1.23.0",
    "beautifulsoup4==4.12.2",
    "selenium==4.9.0",
    "webdriver_manager==4.0.2",
    "python-dotenv==1.0.0",
    "flask==2.3.2",
    "botbuilder-core==4.16.2",
    "botbuilder-schema==4.16.2",
    "botbuilder-integration-aiohttp==4.16.2",
    "requests==2.28.1"
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
