import importlib

# Fail fast if dependencies aren't importable
for m in ["streamlit", "plotly", "pandas", "networkx"]:
    importlib.import_module(m)

print('imports-ok')

