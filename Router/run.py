"""
Entry point script to run the Axeane Automation UI.
Usage: python Router\run.py  (or double-click run.bat in the root folder)
"""
import sys
import os

# Ensure the Router directory is in the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    try:
        print("Starting Axeane Automation UI...")
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Application terminated by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        