"""StockRescue — FalkorDB Graph Hacks 2026 demo dashboard."""

import pandas as pd
import streamlit as st

from agent import StockRescueAgent

st.set_page_config(page_title="StockRescue", page_icon="🛒", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; }
      div[data-testid="stMetric"] {
        background: rgba(128, 128, 128, 0.08);
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 12px;
        padding: 0.8rem 1rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_agent():
    return StockRescueAgent()


try:
    agent = get_agent()
except Exception as e:
    st.error(f"Cannot reach FalkorDB: {e}")
    st.info("Start the stack with `docker compose up` and refresh.")
    st.stop()

# ------------------------------------------------------------------- header

st.title("🛒 StockRescue")
st.caption(
    "A store is out of stock. A rule-based agent walks the FalkorDB graph "
    "to find the nearest store with *safe* surplus, explains why, and "
    "remembers every decision."
)

with st.sidebar:
    st.header("⚙️ Demo controls")
    if st.button("🔄 Reset demo data", use_container_width=True):
        agent.reset()
        st.session_state.pop("rec", None)
        st.session_state.pop("query", None)
        st.success("Graph wiped and reseeded.")
    st.divider()
    st.markdown(
        "**How it works**\n\n"
        "1. `Store -[NEARBY {km}]-> Store`\n"
        "2. `Store -[STOCKS {qty, min_keep}]-> Product`\n"
        "3. `Decision -[FROM/TO/FOR]->` memory nodes\n\n"
        "The agent runs a multi-hop Cypher traversal (up to 2 hops), "
        "never drains a store below its safety minimum, and skips "
        "sources you rejected before — even after a restart."
    )

stores = agent.stores()
products = agent.products()

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    store = st.selectbox(
        "Store that is out of stock",
        stores, format_func=lambda s: s["name"])
with col2:
    product = st.selectbox(
        "Product needed",
        products, format_func=lambda p: p["name"])
with col3:
    st.write("")
    st.write("")
    find = st.button("🔎 Find Stock", type="primary",
                     use_container_width=True)

if find:
    st.session_state["query"] = (store["id"], product["id"])
    st.session_state["rec"] = agent.find_stock(store["id"], product["id"])

# If the user changed the dropdowns, drop the stale recommendation.
if st.session_state.get("query") not in (None, (store["id"], product["id"])):
    st.session_state.pop("rec", None)
    st.session_state.pop("query", None)

# ------------------------------------------------------------ recommendation

rec = st.session_state.get("rec")

if st.session_state.get("query") == (store["id"], product["id"]):
    st.divider()
    if rec is None:
        st.warning(
            f"No store can safely supply **{product['name']}** to "
            f"**{store['name']}** right now. Every nearby store is either "
            "at its safety minimum or was rejected earlier. "
            "(Reset the demo to clear rejection memory.)"
        )
    else:
        st.subheader("🤖 Agent recommendation")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Source store", rec["source_name"])
        m2.metric("Road distance", f"{rec['distance_km']} km")
        m3.metric("Stock at source", f"{rec['qty']} units")
        m4.metric("Safety threshold", f"keep ≥ {rec['min_keep']}")

        st.success(f"**Why:** {rec['reason']}")
        if rec["skipped"]:
            names = {s["id"]: s["name"] for s in stores}
            st.info(
                "🧠 **Memory:** skipped previously rejected source(s): "
                + ", ".join(names.get(i, i) for i in rec["skipped"])
            )

        b1, b2, _ = st.columns([1, 1, 2])
        if b1.button("✅ Reserve 1 Unit", type="primary",
                     use_container_width=True):
            agent.reserve(store["id"], rec["source_id"], product["id"],
                          rec["reason"])
            st.session_state.pop("rec", None)
            st.session_state.pop("query", None)
            st.toast(f"Reserved 1 unit from {rec['source_name']} ✅")
            st.rerun()
        if b2.button("❌ Reject & Try Next", use_container_width=True):
            agent.reject(store["id"], rec["source_id"], product["id"])
            st.session_state["rec"] = agent.find_stock(
                store["id"], product["id"])
            st.rerun()

        # -------------------------------------------------- graph visual
        st.subheader("🕸️ Why this path — live graph view")
        hop_path = rec["path"]  # store names: target ... source
        path_edges = set()
        for i in range(len(hop_path) - 1):
            path_edges.add(frozenset((hop_path[i], hop_path[i + 1])))

        dot = [
            "graph G {",
            '  bgcolor="transparent"; layout=neato; overlap=false;',
            '  node [shape=box, style="rounded,filled", fontname="Helvetica",'
            '        fillcolor="#eceff4", color="#4c566a"];',
            '  edge [fontname="Helvetica", fontsize=10, color="#9aa3b2"];',
        ]
        dot.append(
            f'  "{store["name"]}" [fillcolor="#fdecea", color="#d64545",'
            f' label="{store["name"]}\\n(out of stock)"];')
        dot.append(
            f'  "{rec["source_name"]}" [fillcolor="#e6f4ea",'
            f' color="#2f9e44", label="{rec["source_name"]}\\n'
            f'({rec["qty"]} in stock, keep ≥ {rec["min_keep"]})"];')
        for a, b, km in agent.road_network():
            on_path = frozenset((a, b)) in path_edges
            style = ('penwidth=3, color="#2f9e44", fontcolor="#2f9e44"'
                     if on_path else 'style=dashed')
            dot.append(f'  "{a}" -- "{b}" [label="{km} km", {style}];')
        dot.append(
            f'  "{product["name"]}" [shape=ellipse, fillcolor="#fff3bf",'
            f' color="#b08900"];')
        dot.append(
            f'  "{rec["source_name"]}" -- "{product["name"]}"'
            f' [label="STOCKS", penwidth=2, color="#b08900"];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot), use_container_width=True)

# -------------------------------------------------------- inventory + history

st.divider()
left, right = st.columns(2)

with left:
    st.subheader("📦 Live inventory (from FalkorDB)")
    inv = pd.DataFrame(agent.inventory())
    st.dataframe(inv, use_container_width=True, hide_index=True)

with right:
    st.subheader("🧾 Decision history (persists)")
    hist = agent.history()
    if hist:
        st.dataframe(pd.DataFrame(hist), use_container_width=True,
                     hide_index=True)
    else:
        st.caption("No decisions yet. Find stock and reserve or reject one.")
