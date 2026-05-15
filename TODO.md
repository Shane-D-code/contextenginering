# TODO - P-02 Streamlit Dashboard (Person B)

- [ ] Create `dashboard.py` adapted to repository’s `engine/graph.py` API (`OperationalGraph`).
- [ ] Update `requirements.txt` to include `streamlit`, `pandas`, `plotly` (networkx already present).
- [ ] Ensure dashboard modes work:
  - [ ] Live graph visualization from `graph.G`
  - [ ] Statistics computed from `graph.G` + `_remediation_table`
  - [ ] Edge inspector with confidence/count/evidence_ids/first_seen/last_seen
  - [ ] Test scenarios that call the correct methods/signatures
  - [ ] Confidence decay scenario via `apply_decay(now_ts)`
- [ ] Basic sanity run: `python -m py_compile dashboard.py`
- [ ] Smoke run: `streamlit run dashboard.py`

After the dashboard renders correctly:
- [ ] Evaluate adding real-time callbacks by inspecting event processing in `adapters/engine.py` (and editing graph/engine as needed).

