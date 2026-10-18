# I Taught a Graph Database to Rescue Out-of-Stock Stores

*Built in a weekend for FalkorDB Graph Hacks 2026.*

Every retail chain has this problem: Store A is out of olive oil, Store B — ten minutes away — has nine bottles collecting dust. The transfer never happens, because no one can see both facts in one place, and because naively pulling stock from Store B might leave *it* empty tomorrow.

For Graph Hacks 2026 I built **StockRescue**: a small dashboard where you pick a store and a missing product, and an agent finds the nearest store that can safely spare a unit, explains *why*, and remembers your decisions. Repo: https://github.com/jayasinghthakur/stockrescue

## Why a graph database?

Because this problem *is* a graph. Stores connect to stores by road distance. Stores connect to products with a quantity and a safety threshold. Decisions connect to all of them:

```
(:Store)-[:NEARBY {km}]->(:Store)
(:Store)-[:STOCKS {qty, min_keep}]->(:Product)
(:Decision)-[:FROM]->(:Store), -[:TO]->(:Store), -[:FOR]->(:Product)
```

In a relational database, "find the nearest store with safe surplus, possibly two hops away" is a pile of self-joins. In FalkorDB it's one Cypher query:

```cypher
MATCH path = (t:Store {id: $sid})-[:NEARBY*1..2]->(src:Store),
      (src)-[st:STOCKS]->(p:Product {id: $pid})
WHERE st.qty - 1 >= st.min_keep        // never breach safety stock
  AND NOT src.id IN $rejected          // skip sources I rejected before
WITH src, st,
     reduce(d = 0.0, r IN relationships(path) | d + r.km) AS total_km
RETURN src, st.qty, total_km
ORDER BY total_km LIMIT 1
```

That one query is the whole "AI". It's a rule-based agent — no LLM, and I'm not pretending otherwise. The intelligence lives in the graph model, not in a prompt.

## My favorite trick: memory as graph data

When you reject a recommendation ("that store's van broke down"), the app doesn't stash it in session state. It creates a `Decision` node in the graph. Future queries filter those sources out — which means the agent's memory survives page refreshes, app restarts, even container restarts. Persistence came free with the data model.

## What I learned

- **Push logic into the query.** My first draft filtered stores in Python. Moving the safety check into `WHERE` made it impossible for *any* code path to recommend draining a store.
- **FalkorDB is friction-free.** One Docker image, Redis protocol, a three-line Python client. Variable-length paths, `reduce()`, and list comprehensions all just worked.
- **Explainability is the demo.** Showing the highlighted road path and the sentence "Harbor Point is 7.5 km away and keeps 3 ≥ its safety minimum" landed better than any accuracy claim.

The whole thing is ~550 lines: Streamlit, FalkorDB, Docker Compose. `docker compose up --build` and it's running at localhost:8501. Go break a supply chain and let a graph fix it.
