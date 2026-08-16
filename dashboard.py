import json
import os
from pathlib import Path

import plotly.express as px
import streamlit as st

storage = Path(os.getenv("HERITAGE_STORAGE_DIR", "data"))
state_path, audit_path = storage / "state.json", storage / "audit.json"
st.set_page_config(page_title="HeritageLens Reconciliation", layout="wide")
st.title("HeritageLens: multi-drone reconciliation")
st.caption("Local, deterministic state and decision trace explorer")
if not state_path.exists():
    st.info("No persisted state yet. Start the FastAPI service and submit telemetry events.")
    st.stop()
state = json.loads(state_path.read_text(encoding="utf-8"))
objects = state["objects"]
st.metric("Tracked heritage objects", state["object_count"])
if objects:
    st.subheader("Unified current state")
    st.dataframe(objects, use_container_width=True)
    st.plotly_chart(px.bar(x=[item["class"] for item in objects], title="Resolved object categories", labels={"x": "class", "y": "count"}), use_container_width=True)
audits = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else []
st.subheader("Auditable decision timeline")
st.dataframe(audits, use_container_width=True)
if audits:
    decision = st.selectbox("Inspect decision", audits, format_func=lambda item: item["decision_id"])
    st.json(decision)
