"""Regenerate data_dictionary.md from the schema.   Usage: python build_docs.py"""

from pathlib import Path

from src.docs import render_data_dictionary

if __name__ == "__main__":
    Path("data_dictionary.md").write_text(render_data_dictionary(), encoding="utf-8", newline="\n")
    print("wrote data_dictionary.md")
