"""StockRescue decision agent.

A rule-based agent (no LLM) that uses FalkorDB graph queries to find the
best nearby store to rescue stock from. Every decision is driven by a real
multi-hop Cypher query, and every decision (accepted or rejected) is stored
back into the graph so the agent remembers it across sessions.
"""

import os
import time

from falkordb import FalkorDB

GRAPH_NAME = "stockrescue"

STORES = [
    {"id": "S1", "name": "Downtown Market"},
    {"id": "S2", "name": "Airport Plaza"},
    {"id": "S3", "name": "Harbor Point"},
    {"id": "S4", "name": "Uptown Corner"},
]

PRODUCTS = [
    {"id": "P1", "name": "Olive Oil 1L"},
    {"id": "P2", "name": "Oat Milk 6-pack"},
    {"id": "P3", "name": "Espresso Beans 500g"},
]

# Bidirectional road links between stores, in km.
# Note: S1 and S4 are NOT directly linked, so rescuing S1 from S4
# requires a real 2-hop graph traversal.
NEARBY = [
    ("S1", "S2", 4.2),
    ("S1", "S3", 7.5),
    ("S2", "S3", 3.1),
    ("S3", "S4", 5.0),
    ("S2", "S4", 9.8),
]

# (store, product, qty, min_keep). min_keep is the safety threshold the
# agent must never let a source store drop below.
STOCKS = [
    ("S1", "P1", 0, 2), ("S1", "P2", 5, 2), ("S1", "P3", 1, 1),
    ("S2", "P1", 9, 3), ("S2", "P2", 0, 2), ("S2", "P3", 3, 3),
    ("S3", "P1", 4, 3), ("S3", "P2", 12, 4), ("S3", "P3", 8, 2),
    ("S4", "P1", 6, 2), ("S4", "P2", 2, 2), ("S4", "P3", 0, 1),
]


class StockRescueAgent:
    def __init__(self):
        host = os.environ.get("FALKORDB_HOST", "localhost")
        port = int(os.environ.get("FALKORDB_PORT", "6379"))
        self.db = FalkorDB(host=host, port=port)
        self.graph = self.db.select_graph(GRAPH_NAME)
        self._seed_if_empty()

    # ---------------------------------------------------------------- setup

    def _seed_if_empty(self):
        res = self.graph.query("MATCH (s:Store) RETURN count(s) AS c")
        if res.result_set and res.result_set[0][0] > 0:
            return
        self.seed()

    def seed(self):
        for s in STORES:
            self.graph.query(
                "CREATE (:Store {id: $id, name: $name})", s)
        for p in PRODUCTS:
            self.graph.query(
                "CREATE (:Product {id: $id, name: $name})", p)
        for a, b, km in NEARBY:
            self.graph.query(
                """MATCH (a:Store {id: $a}), (b:Store {id: $b})
                   CREATE (a)-[:NEARBY {km: $km}]->(b),
                          (b)-[:NEARBY {km: $km}]->(a)""",
                {"a": a, "b": b, "km": km})
        for sid, pid, qty, min_keep in STOCKS:
            self.graph.query(
                """MATCH (s:Store {id: $sid}), (p:Product {id: $pid})
                   CREATE (s)-[:STOCKS {qty: $qty, min_keep: $mk}]->(p)""",
                {"sid": sid, "pid": pid, "qty": qty, "mk": min_keep})

    def reset(self):
        """Wipe the whole graph (including decision memory) and reseed."""
        try:
            self.graph.delete()
        except Exception:
            pass  # graph may not exist yet
        self.graph = self.db.select_graph(GRAPH_NAME)
        self.seed()

    # --------------------------------------------------------------- lookups

    def stores(self):
        res = self.graph.query(
            "MATCH (s:Store) RETURN s.id, s.name ORDER BY s.id")
        return [{"id": r[0], "name": r[1]} for r in res.result_set]

    def products(self):
        res = self.graph.query(
            "MATCH (p:Product) RETURN p.id, p.name ORDER BY p.id")
        return [{"id": r[0], "name": r[1]} for r in res.result_set]

    def inventory(self):
        res = self.graph.query(
            """MATCH (s:Store)-[st:STOCKS]->(p:Product)
               RETURN s.name, p.name, st.qty, st.min_keep
               ORDER BY s.id, p.id""")
        return [{"Store": r[0], "Product": r[1], "Qty": r[2],
                 "Safety min": r[3]} for r in res.result_set]

    def road_network(self):
        """All NEARBY links (deduplicated) for drawing the store graph."""
        res = self.graph.query(
            """MATCH (a:Store)-[n:NEARBY]->(b:Store)
               WHERE a.id < b.id
               RETURN a.name, b.name, n.km""")
        return [(r[0], r[1], r[2]) for r in res.result_set]

    def rejected_sources(self, store_id, product_id):
        """Source stores previously rejected for this store+product.

        This is the agent's persistent memory: it lives in the graph,
        so it survives page refreshes and app restarts.
        """
        res = self.graph.query(
            """MATCH (d:Decision {status: 'rejected', target: $sid,
                                  product: $pid})-[:FROM]->(s:Store)
               RETURN DISTINCT s.id""",
            {"sid": store_id, "pid": product_id})
        return [r[0] for r in res.result_set]

    # ----------------------------------------------------------- the agent

    def find_stock(self, store_id, product_id, units=1):
        """Find the best source store via a multi-hop graph traversal.

        Walks NEARBY links up to 2 hops from the target store, keeps only
        sources whose stock stays at or above its safety threshold after
        giving up `units`, skips sources this agent was told to reject
        before, and picks the shortest total road distance.
        """
        rejected = self.rejected_sources(store_id, product_id)
        res = self.graph.query(
            """MATCH path = (t:Store {id: $sid})-[:NEARBY*1..2]->(src:Store),
                     (src)-[st:STOCKS]->(p:Product {id: $pid})
               WHERE src.id <> $sid
                 AND st.qty - $units >= st.min_keep
                 AND NOT src.id IN $rejected
               WITH src, st,
                    reduce(d = 0.0, r IN relationships(path) | d + r.km)
                        AS total_km,
                    [n IN nodes(path) | n.name] AS hops
               RETURN src.id, src.name, st.qty, st.min_keep, total_km, hops
               ORDER BY total_km ASC, src.id ASC
               LIMIT 1""",
            {"sid": store_id, "pid": product_id, "units": units,
             "rejected": rejected})
        if not res.result_set:
            return None
        r = res.result_set[0]
        return {
            "source_id": r[0],
            "source_name": r[1],
            "qty": r[2],
            "min_keep": r[3],
            "distance_km": round(r[4], 1),
            "path": r[5],          # store names along the road path
            "skipped": rejected,   # sources excluded by rejection memory
            "reason": (
                f"{r[1]} is the closest store ({round(r[4], 1)} km via "
                f"{' → '.join(r[5])}) that can give up {units} unit(s) and "
                f"still keep {r[2] - units} ≥ its safety minimum of {r[3]}."
            ),
        }

    def reserve(self, store_id, source_id, product_id, reason, units=1):
        """Transfer `units` from source to target and record the decision."""
        self.graph.query(
            """MATCH (src:Store {id: $src})-[st:STOCKS]->(:Product {id: $pid})
               WHERE st.qty - $units >= st.min_keep
               SET st.qty = st.qty - $units""",
            {"src": source_id, "pid": product_id, "units": units})
        self.graph.query(
            """MATCH (t:Store {id: $sid})-[st:STOCKS]->(:Product {id: $pid})
               SET st.qty = st.qty + $units""",
            {"sid": store_id, "pid": product_id, "units": units})
        self._record(store_id, source_id, product_id,
                     "accepted", reason, units)

    def reject(self, store_id, source_id, product_id, units=1):
        """Remember that this source was rejected for this store+product."""
        self._record(store_id, source_id, product_id, "rejected",
                     "Rejected by operator; excluded from future "
                     "recommendations for this store and product.", units)

    def _record(self, store_id, source_id, product_id, status, reason, units):
        self.graph.query(
            """MATCH (f:Store {id: $src}), (t:Store {id: $sid}),
                     (p:Product {id: $pid})
               CREATE (d:Decision {status: $status, target: $sid,
                                   product: $pid, units: $units,
                                   reason: $reason, ts: $ts})
               CREATE (d)-[:FROM]->(f), (d)-[:TO]->(t), (d)-[:FOR]->(p)""",
            {"src": source_id, "sid": store_id, "pid": product_id,
             "status": status, "reason": reason, "units": units,
             "ts": int(time.time() * 1000)})

    def history(self):
        res = self.graph.query(
            """MATCH (d:Decision)-[:FROM]->(f:Store),
                     (d)-[:TO]->(t:Store), (d)-[:FOR]->(p:Product)
               RETURN d.ts, d.status, f.name, t.name, p.name, d.units
               ORDER BY d.ts DESC""")
        out = []
        for ts, status, f, t, p, units in res.result_set:
            when = time.strftime("%Y-%m-%d %H:%M:%S",
                                 time.localtime(ts / 1000))
            out.append({"When": when, "Decision": status,
                        "From": f, "To": t, "Product": p, "Units": units})
        return out
