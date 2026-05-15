#!/usr/bin/env python3
"""Streamlit Dashboard for P-02 OperationalGraph Debugging
Run with: streamlit run dashboard.py

This dashboard is tailored to this repo's engine.graph.OperationalGraph API.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from engine.graph import OperationalGraph

    GRAPH_AVAILABLE = True
except Exception as e:
    GRAPH_AVAILABLE = False
    GRAPH_IMPORT_ERROR = str(e)


# ========== PAGE CONFIGURATION ==========
st.set_page_config(
    page_title="P-02 Graph Debugger",
    page_icon="🕸️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ========== CUSTOM CSS ==========
st.markdown(
    """
<style>
    .metric-card { background-color: #f0f2f6; border-radius: 10px; padding: 15px; margin: 10px 0; }
    .edge-good { color: #28a745; font-weight: bold; }
    .edge-bad { color: #dc3545; font-weight: bold; }
    .temporal-violation {
        background-color: #ffebee;
        border-left: 4px solid #dc3545;
        padding: 10px;
        margin: 5px 0;
        font-family: monospace;
        font-size: 12px;
    }
    .reinforcement-event {
        background-color: #e8f5e9;
        border-left: 4px solid #28a745;
        padding: 10px;
        margin: 5px 0;
        font-family: monospace;
        font-size: 12px;
    }
</style>
""",
    unsafe_allow_html=True,
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _graph_stats(g: OperationalGraph) -> dict:
    num_nodes = g.G.number_of_nodes()
    num_edges = g.G.number_of_edges()
    confidences = [d.get("confidence", 0.0) for _, _, d in g.G.edges(data=True)]
    avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0

    # remediation table is internal but stable for this repo
    total_remediations = sum(len(v) for v in getattr(g, "_remediation_table", {}).values())

    return {
        "num_nodes": num_nodes,
        "num_edges": num_edges,
        "avg_confidence": avg_conf,
        "total_remediations": total_remediations,
    }


# ========== INITIALIZE SESSION STATE ==========
if "graph" not in st.session_state:
    if GRAPH_AVAILABLE:
        st.session_state.graph = OperationalGraph()
        st.session_state.events_ingested = 0
        st.session_state.temporal_violations = []  # tracked in UI (OperationalGraph drops silently)
        st.session_state.reinforcements = []
        st.session_state.manual_events = []
    else:
        st.session_state.graph = None
        st.session_state.events_ingested = 0
        st.session_state.temporal_violations = []
        st.session_state.reinforcements = []
        st.session_state.manual_events = []

if "manual_events" not in st.session_state:
    st.session_state.manual_events = []


# ========== SIDEBAR ==========
with st.sidebar:
    st.title("🕸️ P-02 Graph Debugger")
    st.markdown("---")

    mode = st.radio(
        "Dashboard Mode",
        ["📊 Live Graph", "📈 Statistics", "🔬 Edge Inspector", "🧪 Test Scenarios"],
        index=0,
    )

    st.markdown("---")

    if mode == "📊 Live Graph":
        st.subheader("Graph Controls")
        max_hops = st.slider("Max Traversal Hops", 1, 5, 2)  # visual hint only
        min_confidence = st.slider("Min Confidence Threshold", 0.0, 1.0, 0.3, 0.05)

        st.markdown("---")
        if st.button("🗑️ Reset Graph", type="secondary"):
            if GRAPH_AVAILABLE:
                st.session_state.graph = OperationalGraph()
                st.session_state.events_ingested = 0
                st.session_state.temporal_violations = []
                st.session_state.reinforcements = []
                st.session_state.manual_events = []
            st.rerun()

    st.markdown("---")
    st.caption(f"Events ingested: {st.session_state.events_ingested}")
    st.caption(f"Temporal violations (UI logged): {len(st.session_state.temporal_violations)}")


# ========== MODE 1: LIVE GRAPH VISUALIZATION ==========
if mode == "📊 Live Graph":
    st.title("📊 Live Causal Graph")
    st.markdown("Edges appear only when causality is detected (OperationalGraph enforces `ts_src < ts_dst`).")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Graph Visualization")

        if not st.session_state.graph:
            st.warning("Graph not initialized.")
        elif st.session_state.graph.G.number_of_edges() == 0:
            st.info("No edges yet. Use 'Test Scenarios' or 'Manual Event Injection' to ingest events.")
        else:
            # Build a visualization digraph
            G = nx.DiGraph()
            for u, v, data in st.session_state.graph.G.edges(data=True):
                conf = float(data.get("confidence", 0.0))
                if conf >= min_confidence:
                    G.add_edge(
                        u,
                        v,
                        confidence=conf,
                        relation=data.get("relation", ""),
                        count=int(data.get("count", 0)),
                        label=f"{data.get('relation','')}\n{conf:.2f}",
                    )

            if G.number_of_edges() == 0:
                st.info(f"No edges with confidence ≥ {min_confidence}. Try lowering the threshold or ingest more events.")
            else:
                pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

                edge_traces = []
                for u, v, data in G.edges(data=True):
                    x0, y0 = pos[u]
                    x1, y1 = pos[v]
                    conf = data["confidence"]

                    if conf >= 0.7:
                        color = "#28a745"  # green
                        width = 4
                    elif conf >= 0.4:
                        color = "#ffc107"  # yellow
                        width = 3
                    else:
                        color = "#dc3545"  # red
                        width = 2

                    edge_traces.append(
                        go.Scatter(
                            x=[x0, x1, None],
                            y=[y0, y1, None],
                            mode="lines",
                            line=dict(width=width, color=color),
                            hoverinfo="text",
                            text=(
                                f"{data['relation']}<br>Confidence: {conf:.2f}<br>Count: {data['count']}<br>"
                                f"{u} → {v}"
                            ),
                            showlegend=False,
                        )
                    )

                node_x, node_y, node_text = [], [], []
                for node in G.nodes():
                    x, y = pos[node]
                    node_x.append(x)
                    node_y.append(y)
                    node_text.append(f"<b>{node}</b><br>Degree: {G.degree(node)}")

                node_trace = go.Scatter(
                    x=node_x,
                    y=node_y,
                    mode="markers+text",
                    marker=dict(size=30, color="#4a90e2", line=dict(color="white", width=2)),
                    text=node_text,
                    textposition="top center",
                    hoverinfo="text",
                    showlegend=False,
                )

                fig = go.Figure(
                    data=edge_traces + [node_trace],
                    layout=go.Layout(
                        hovermode="closest",
                        margin=dict(b=20, l=5, r=5, t=40),
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        title=dict(
                            text=(
                                f"Causal Graph | {G.number_of_nodes()} nodes | {G.number_of_edges()} edges"
                                f" | min_conf={min_confidence}"
                            ),
                            font=dict(size=14),
                        ),
                    ),
                )

                st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Recent Activity")

        if st.session_state.manual_events:
            st.write("**Last 5 events ingested:**")
            for event in st.session_state.manual_events[-5:]:
                with st.container():
                    st.markdown(
                        f"`{event['kind']}` | `{event.get('service', event.get('cid', 'N/A'))}` | `{event.get('ts', 'N/A')}`"
                    )

        if st.session_state.temporal_violations:
            st.error(f"⚠️ {len(st.session_state.temporal_violations)} temporal violations logged")
            with st.expander("View violations"):
                for v in st.session_state.temporal_violations[-5:]:
                    st.markdown(f"<div class='temporal-violation'>{v}</div>", unsafe_allow_html=True)

        if st.session_state.reinforcements:
            st.success(f"✅ {len(st.session_state.reinforcements)} reinforcement events")
            with st.expander("View reinforcements"):
                for r in st.session_state.reinforcements[-5:]:
                    st.markdown(f"<div class='reinforcement-event'>{r}</div>", unsafe_allow_html=True)

        st.subheader("Manual Event Injection (debug)")
        with st.form("manual_event_form"):
            event_kind = st.selectbox(
                "Event Kind",
                ["deploy", "edge_add", "remediation"],
            )

            # common inputs
            col_a, col_b = st.columns(2)
            with col_a:
                cid = st.text_input("Canonical ID (cid)", "svcA")
                cid2 = st.text_input("Target Canonical ID (dst cid for edge)", "svcB")
            with col_b:
                ts = st.text_input("Timestamp (ISO)", _now_iso())

            if event_kind == "deploy":
                version = st.text_input("Version", "v1.0.0")
            elif event_kind == "edge_add":
                relation = st.text_input("Relation", "calls")
                evidence_id = st.text_input("Evidence ID", "e1")
                ts_src = st.text_input("ts_src (ISO)", ts)
                ts_dst = st.text_input("ts_dst (ISO)", _now_iso())
            else:  # remediation
                action = st.text_input("action", "rollback")
                outcome = st.text_input("outcome", "resolved")
                incident_id = st.text_input("incident_id", "inc_001")

            if st.form_submit_button("Inject"):
                g = st.session_state.graph
                if not g:
                    st.error("Graph unavailable.")
                else:
                    if event_kind == "deploy":
                        g.record_deploy(cid, version, ts)
                        st.success(f"Recorded deploy for {cid} @ {ts}")
                        st.session_state.manual_events.append({"kind": "deploy", "service": cid, "ts": ts, "version": version})
                    elif event_kind == "edge_add":
                        # log temporal violation for UI clarity (graph silently drops)
                        try:
                            from engine.graph import _parse_ts  # type: ignore

                            if _parse_ts(ts_src) >= _parse_ts(ts_dst):
                                st.session_state.temporal_violations.append(
                                    f"Dropped edge_add due to ts_src >= ts_dst: {cid} -> {cid2}, {ts_src} >= {ts_dst}"
                                )
                        except Exception:
                            pass

                        g.add_edge(
                            src_cid=cid,
                            dst_cid=cid2,
                            relation=relation,
                            evidence_id=evidence_id,
                            ts_src=ts_src,
                            ts_dst=ts_dst,
                        )
                        st.success(f"Attempted edge_add {cid} → {cid2} ({relation})")
                        st.session_state.manual_events.append({"kind": "edge_add", "service": cid, "ts": ts_dst, "relation": relation, "evidence": evidence_id})
                    else:  # remediation
                        event = {"ts": ts, "action": action, "outcome": outcome, "incident_id": incident_id}
                        g.reinforce_remediation(cid=cid, event=event)
                        st.session_state.reinforcements.append(
                            f"Remediation reinforcement for {cid} ({action}/{outcome}) @ {ts}"
                        )
                        st.session_state.manual_events.append({"kind": "remediation", "service": cid, "ts": ts})
                        st.success("Remediation reinforcement applied")

                    st.session_state.events_ingested += 1
                    st.rerun()


# ========== MODE 2: STATISTICS ==========
elif mode == "📈 Statistics":
    st.title("📈 Graph Statistics & Metrics")

    g = st.session_state.graph
    if not g:
        st.warning("Graph not initialized.")
    else:
        stats = _graph_stats(g)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Nodes", stats["num_nodes"])
        col2.metric("Edges", stats["num_edges"])
        col3.metric("Avg Confidence", f"{stats['avg_confidence']:.3f}")
        col4.metric("Remediations", stats["total_remediations"])

        st.markdown("---")

        # Confidence distribution
        if stats["num_edges"] > 0:
            confidences = [d.get("confidence", 0.0) for _, _, d in g.G.edges(data=True)]
            df_conf = pd.DataFrame({"confidence": confidences})
            fig_conf = px.histogram(
                df_conf,
                x="confidence",
                nbins=20,
                title="Edge Confidence Distribution",
                color_discrete_sequence=["#4a90e2"],
            )
            fig_conf.update_layout(bargap=0.05)
            st.plotly_chart(fig_conf, use_container_width=True)

        # Edge types breakdown
        if stats["num_edges"] > 0:
            edge_types: dict[str, int] = {}
            for _, _, d in g.G.edges(data=True):
                rel = d.get("relation", "")
                edge_types[rel] = edge_types.get(rel, 0) + 1
            df_types = pd.DataFrame({"relation": list(edge_types.keys()), "count": list(edge_types.values())})
            fig_types = px.bar(
                df_types,
                x="relation",
                y="count",
                title="Edges by Relation Type",
                color_discrete_sequence=["#ffc107"],
            )
            st.plotly_chart(fig_types, use_container_width=True)

        # Recent remediations
        rem_table = getattr(g, "_remediation_table", {})
        all_rows = []
        for cid, rows in rem_table.items():
            for r in rows:
                all_rows.append(
                    {
                        "cid": cid,
                        "action": r.get("action", ""),
                        "outcome": r.get("outcome", ""),
                        "incident_id": r.get("incident_id", ""),
                        "ts": r.get("ts", ""),
                    }
                )

        if all_rows:
            st.subheader("Remediation History (latest first)")
            df_rem = pd.DataFrame(all_rows).sort_values("ts", ascending=False)
            st.dataframe(df_rem.head(50), use_container_width=True)


# ========== MODE 3: EDGE INSPECTOR ==========
elif mode == "🔬 Edge Inspector":
    st.title("🔬 Edge Inspector")
    st.markdown("Inspect individual causal edges and their properties.")

    g = st.session_state.graph
    if not g or g.G.number_of_edges() == 0:
        st.info("No edges yet. Ingest events to see them here.")
    else:
        edges_list = []
        for u, v, data in g.G.edges(data=True):
            edges_list.append(
                {
                    "source": u,
                    "target": v,
                    "relation": data.get("relation", ""),
                    "confidence": float(data.get("confidence", 0.0)),
                    "count": int(data.get("count", 0)),
                    "first_seen": data.get("first_seen", ""),
                    "last_seen": data.get("last_seen", ""),
                    "evidence_count": len(data.get("evidence_ids", [])),
                    "evidence_ids": data.get("evidence_ids", []),
                    "remediation_reinforced": bool(data.get("remediation_reinforced", False)),
                }
            )

        df_edges = pd.DataFrame(edges_list)

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            min_conf_filter = st.slider("Min Confidence", 0.0, 1.0, 0.0, 0.05)
        with col_f2:
            relation_filter = st.multiselect(
                "Relation Types",
                options=sorted(df_edges["relation"].unique().tolist()),
                default=[],
            )
        with col_f3:
            reinforced_only = st.checkbox("Only show remediation-reinforced edges")

        filtered_df = df_edges[df_edges["confidence"] >= min_conf_filter]
        if relation_filter:
            filtered_df = filtered_df[filtered_df["relation"].isin(relation_filter)]
        if reinforced_only:
            filtered_df = filtered_df[filtered_df["remediation_reinforced"] == True]

        st.dataframe(filtered_df, use_container_width=True)

        st.subheader("Edge Details")
        selectable = [
            f"{row.source} → {row.target} ({row.relation})"
            for row in filtered_df.itertuples(index=False)
        ]

        selected_edge = st.selectbox("Select an edge to inspect", selectable) if selectable else None

        if selected_edge:
            src, rest = selected_edge.split(" → ")
            dst, rel_part = rest.split(" (")
            relation = rel_part.rstrip(")")

            data = g.G.get_edge_data(src, dst)
            if not data:
                st.warning("Edge not found (it may have been filtered out).")
            else:
                st.info(f"Inspecting: {src} → {dst} ({relation})")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Confidence", f"{float(data.get('confidence', 0.0)):.3f}")
                    st.metric("Observations", int(data.get("count", 0)))
                    st.metric("Evidence Points", len(data.get("evidence_ids", [])))
                with col2:
                    st.metric("First Seen", str(data.get("first_seen", ""))[:19])
                    st.metric("Last Seen", str(data.get("last_seen", ""))[:19])
                    st.metric(
                        "Remediation Reinforced",
                        "Yes" if bool(data.get("remediation_reinforced", False)) else "No",
                    )

                with st.expander("Evidence IDs"):
                    st.write(data.get("evidence_ids", []))


# ========== MODE 4: TEST SCENARIOS ==========
elif mode == "🧪 Test Scenarios":
    st.title("🧪 Test Scenarios")
    st.markdown("Run predefined scenarios to verify graph behavior.")

    g = st.session_state.graph
    if not g:
        st.error("OperationalGraph unavailable. Check import errors.")
        if "GRAPH_IMPORT_ERROR" in globals():
            st.text(GRAPH_IMPORT_ERROR)

    # Scenario 1: Basic causality
    with st.expander("Scenario 1: Basic Deploy → Metric Causality", expanded=True):
        st.markdown("A deploy followed by an edge_add with ts_src < ts_dst creates/boosts a causal edge.")
        if st.button("Run Scenario 1", key="scenario1"):
            st.session_state.graph = OperationalGraph()
            st.session_state.temporal_violations = []
            st.session_state.reinforcements = []
            st.session_state.manual_events = []
            g = st.session_state.graph

            g.record_deploy("payment-svc", "v2.0.0", "2024-01-01T10:00:00")
            # Add causal edge directly (graph doesn't infer from deploy; dashboard is for debugging writes)
            g.add_edge(
                src_cid="payment-svc",
                dst_cid="payment-svc",
                relation="deploy_to_metric",
                evidence_id="metric_001",
                ts_src="2024-01-01T10:00:00",
                ts_dst="2024-01-01T10:05:00",
            )
            st.success("✅ Scenario 1 complete. Switch to 'Live Graph'.")
            st.session_state.events_ingested += 1

    # Scenario 2: Confidence reinforcement
    with st.expander("Scenario 2: Confidence Growth with Repetition", expanded=True):
        st.markdown("Repeated identical edge_add calls increase confidence (and count).")
        if st.button("Run Scenario 2", key="scenario2"):
            st.session_state.graph = OperationalGraph()
            g = st.session_state.graph

            for i in range(5):
                g.add_edge(
                    src_cid="svcA",
                    dst_cid="svcB",
                    relation="calls",
                    evidence_id=f"e{i}",
                    ts_src=f"T{i}",
                    ts_dst=f"T{i+1}",
                )

            data = g.G.get_edge_data("svcA", "svcB")
            conf = float(data.get("confidence", 0.0)) if data else 0.0
            cnt = int(data.get("count", 0)) if data else 0
            st.write({"confidence": round(conf, 3), "count": cnt})
            st.success("✅ Scenario 2 complete. (Check Edge Inspector) ")
            st.session_state.events_ingested += 1

    # Scenario 3: Temporal violation detection (UI logged; graph drops silently)
    with st.expander("Scenario 3: Temporal Violation Detection", expanded=True):
        st.markdown("Edge with ts_src >= ts_dst is dropped by OperationalGraph.add_edge.")
        if st.button("Run Scenario 3", key="scenario3"):
            st.session_state.graph = OperationalGraph()
            st.session_state.temporal_violations = []
            g = st.session_state.graph

            # This should add
            g.add_edge("svcA", "svcB", "calls", "e1", "2024-01-01T00:00:00", "2024-01-01T00:01:00")
            before = g.G.number_of_edges()

            # This should be dropped
            g.add_edge("svcA", "svcB", "calls", "e2", "2024-01-01T00:01:00", "2024-01-01T00:00:00")
            after = g.G.number_of_edges()

            if after == before:
                st.success("✅ Temporal enforcement working. Edge count stayed the same.")
            else:
                st.warning("⚠️ Edge count changed; verify timestamps parsing.")

            st.session_state.temporal_violations.append(
                "Attempted edge with ts_src >= ts_dst; OperationalGraph should silently drop it."
            )
            st.session_state.events_ingested += 1

    # Scenario 4: Remediation reinforcement
    with st.expander("Scenario 4: Remediation Reinforcement", expanded=True):
        st.markdown("A resolved remediation boosts confidence of edges involving the given cid (within 10 minutes window).")
        if st.button("Run Scenario 4", key="scenario4"):
            st.session_state.graph = OperationalGraph()
            g = st.session_state.graph

            # Add a causal edge whose last_seen is close to remediation ts
            g.add_edge("svcA", "svcB", "calls", "e1", "2024-01-01T10:00:00", "2024-01-01T10:05:00")
            old_data = g.G.get_edge_data("svcA", "svcB")
            old_conf = float(old_data.get("confidence", 0.0)) if old_data else 0.0

            g.reinforce_remediation(
                cid="svcA",
                event={
                    "ts": "2024-01-01T10:06:00",
                    "action": "rollback",
                    "outcome": "resolved",
                    "incident_id": "inc_001",
                },
            )

            new_data = g.G.get_edge_data("svcA", "svcB")
            new_conf = float(new_data.get("confidence", 0.0)) if new_data else 0.0

            st.write({"before": round(old_conf, 3), "after": round(new_conf, 3), "delta": round(new_conf - old_conf, 3)})
            st.success("✅ Scenario 4 complete. Check Live Graph color shift / Edge Inspector.")
            st.session_state.events_ingested += 1

    # Scenario 5: Confidence decay
    with st.expander("Scenario 5: Confidence Decay Over Time", expanded=True):
        st.markdown("apply_decay subtracts 0.01 per day of no reinforcement (min confidence clamp at 0.1).")
        if st.button("Run Scenario 5", key="scenario5"):
            st.session_state.graph = OperationalGraph()
            g = st.session_state.graph

            g.add_edge(
                "svcA",
                "svcB",
                "calls",
                "e1",
                "2024-01-01T00:00:00",
                "2024-01-01T00:01:00",
            )
            old_data = g.G.get_edge_data("svcA", "svcB")
            old_conf = float(old_data.get("confidence", 0.0)) if old_data else 0.0

            g.apply_decay("2024-01-11T00:00:00")
            new_data = g.G.get_edge_data("svcA", "svcB")
            new_conf = float(new_data.get("confidence", 0.0)) if new_data else 0.0

            st.write({"before": round(old_conf, 3), "after": round(new_conf, 3), "delta": round(old_conf - new_conf, 3)})
            st.success("✅ Scenario 5 complete.")
            st.session_state.events_ingested += 1


st.markdown("---")
st.caption("P-02 Graph Debugger | Streamlit | Built for Person B")

