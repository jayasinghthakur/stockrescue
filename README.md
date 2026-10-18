# 🛒 StockRescue — FalkorDB Graph Hacks 2026

A retail store runs out of a product. A **rule-based decision agent** (no LLM —
and we don't pretend otherwise) walks a **FalkorDB graph** to find the nearest
store with *safe* surplus stock, recommends a transfer, shows the exact graph
path that justified the choice, and **remembers every decision** — including
rejections — across sessions.

## Run it

```bash
docker compose up --build
```

Then open **http://localhost:8501**. That's it — Compose starts both FalkorDB
and the Streamlit dashboard.

## Graph model

```
(:Store)    -[:NEARBY {km}]->            (:Store)      # road links, both ways
(:Store)    -[:STOCKS {qty, min_keep}]-> (:Product)    # min_keep = safety stock
(:Decision) -[:FROM]-> (:Store)                        # source store
(:Decision) -[:TO]->   (:Store)                        # requesting store
(:Decision) -[:FOR]->  (:Product)
```

4 sample stores, 3 products, synthetic data seeded on first start.
Stores S1 (Downtown) and S4 (Uptown) are deliberately **not** directly
connected, so some rescues require a genuine 2-hop traversal.

## The decision query (the heart of the agent)

```cypher
MATCH path = (t:Store {id: $sid})-[:NEARBY*1..2]->(src:Store),
      (src)-[st:STOCKS]->(p:Product {id: $pid})
WHERE src.id <> $sid
  AND st.qty - $units >= st.min_keep      // never breach safety stock
  AND NOT src.id IN $rejected             // persistent rejection memory
WITH src, st,
     reduce(d = 0.0, r IN relationships(path) | d + r.km) AS total_km,
     [n IN nodes(path) | n.name] AS hops
RETURN src.id, src.name, st.qty, st.min_keep, total_km, hops
ORDER BY total_km ASC
LIMIT 1
```

Other queries used by the app:

```cypher
// rejection memory (survives refresh & restart — it lives in the graph)
MATCH (d:Decision {status:'rejected', target:$sid, product:$pid})-[:FROM]->(s:Store)
RETURN DISTINCT s.id

// reserve a unit (guarded so it can never breach the threshold)
MATCH (src:Store {id:$src})-[st:STOCKS]->(:Product {id:$pid})
WHERE st.qty - 1 >= st.min_keep  SET st.qty = st.qty - 1

// decision history
MATCH (d:Decision)-[:FROM]->(f), (d)-[:TO]->(t), (d)-[:FOR]->(p)
RETURN d.ts, d.status, f.name, t.name, p.name ORDER BY d.ts DESC
```

Try them yourself: `docker compose exec falkordb redis-cli GRAPH.QUERY stockrescue "<query>"`

## 2-minute demo script

1. **Setup** — "Downtown Market is out of Olive Oil. Watch the agent fix it."
2. Select **Downtown Market** + **Olive Oil 1L**, click **Find Stock**.
   → Agent recommends **Airport Plaza** (4.2 km), shows the highlighted
   graph path and the exact safety math.
3. Click **❌ Reject & Try Next** — "Pretend Airport's van broke down."
   → Agent instantly recommends the next-best store and shows a
   🧠 memory banner for the skipped one.
4. **Refresh the page** (or restart the app) and click Find Stock again
   → the rejection is still remembered. It's stored as a `Decision` node
   in FalkorDB, not in the session.
5. Click **✅ Reserve 1 Unit** → inventory updates live on both stores,
   and the decision lands in the history table.
6. Point out the safety rule: stores at `min_keep` are **never** offered,
   even when they technically have stock.
7. **Reset demo data** in the sidebar wipes and reseeds the graph.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit dashboard |
| `agent.py` | Rule-based agent + all Cypher queries |
| `compose.yaml` | FalkorDB + web app |
| `Dockerfile` | Web app image |
| `requirements.txt` | streamlit, falkordb, pandas |
