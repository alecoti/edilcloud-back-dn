"""Global canonical-fact reconciliation, including facts in distant batches."""

from itertools import combinations

from .checkpoints import run_step
from .content import digest
from .intelligence_calls import specialist
from .intelligence_contracts import ReconciliationResult
from .intelligence_readers import bounded_batches, parallel_map


def canonical_card(fact):
    return {
        "fact_id": fact.id, "text": fact.text, "nature": fact.nature,
        "category": fact.category, "event_date": fact.event_date, "author": fact.author,
        "critical": fact.critical, "source_ids": sorted({r.source_id for r in fact.references}),
    }


def reconcile_global(job, facts, local, policy):
    """All canonical pairs meet in a bounded global window.

    Ordinary DEEP scopes use one global request. Huge scopes use all unordered
    pairs of bounded canonical groups, not just adjacent groups: an origin in
    group 1 and its outcome in group 7 must have a shared comparison. This
    exhaustive fallback costs quadratically in the number of groups; its
    checkpointed comparisons are observable and never silently sampled.
    """
    known = {f.id: f for f in facts}
    cards = [canonical_card(f) for f in facts]

    def execute(_step):
        parents = {f.id: f.id for f in facts}
        rejected_merges = set()

        def root(key):
            while parents[key] != key:
                parents[key] = parents[parents[key]]
                key = parents[key]
            return key

        def unify(left, right):
            a, b = known[left], known[right]
            if (a.nature, a.category, a.event_date) != (b.nature, b.category, b.event_date):
                # A proposed deduplication is advisory. Rejecting it must keep
                # both facts, not discard the complete paid analysis or infer
                # a relationship that the sources have not established.
                rejected_merges.add(tuple(sorted((left, right))))
                return
            first, second = sorted((root(left), root(right)))
            parents[second] = first

        conflicts = {tuple(sorted(pair)) for pair in local.get("conflicts", [])}
        related = set()
        for key, row in local["facts"].items():
            if key != row["canonical_fact_id"]:
                unify(key, row["canonical_fact_id"])
            related.update(tuple(sorted((key, other))) for other in row.get("related_fact_ids", []) if key != other)
        # Use canonical cards only. The full source/fact ledger stays intact.
        representatives = [card for card in cards if root(card["fact_id"]) == card["fact_id"]]
        groups = list(bounded_batches(representatives, max_characters=16000, max_items=24))
        windows = [groups[0]] if len(groups) == 1 else [a + b for a, b in combinations(groups, 2)]

        def compare(window):
            identifiers = {card["fact_id"] for card in window}
            result = specialist(
                job=job, key=f"reconcile_global:{digest(window)[:32]}", stage="document_reconcile_global",
                schema=ReconciliationResult, effort="high",
                data={"canonical_facts": window, "policy": policy,
                      "local_conflicts": [list(pair) for pair in conflicts if set(pair) <= identifiers]},
                instructions=(
                    "Riconcilia GLOBALMENTE questi CanonicalFact provenienti anche da lotti lontani. "
                    "Rendi conto di ciascun fact_id una volta. Collega con related_fact_ids l'origine, "
                    "le decisioni, le condizioni, gli esiti e le riaperture del medesimo evento, anche "
                    "quando hanno date o nature diverse. Conserva i fatti distinti e la cronologia. "
                    "canonical_fact_id diverso è ammesso soltanto per duplicati equivalenti per "
                    "significato, categoria, data e natura. Apertura e chiusura sono correlate, mai "
                    "duplicati. conflicts_with indica contraddizioni effettive, non la normale evoluzione. "
                    "Non inferire una verifica da una riparazione, né una chiusura in presenza di "
                    "condizioni ancora aperte. Tutti gli id devono appartenere a questa finestra."
                ),
            )
            if {r.fact_id for r in result.facts} != identifiers or len(result.facts) != len(identifiers):
                raise ValueError("La riconciliazione globale non esamina tutti i fatti assegnati.")
            for row in result.facts:
                if (row.canonical_fact_id not in identifiers or
                        (set(row.conflicts_with) | set(row.related_fact_ids)) - identifiers or not row.reason.strip()):
                    raise ValueError("Relazione globale con riferimenti o motivazioni non validi.")
            return result

        for result in parallel_map(compare, windows):
            for row in result.facts:
                if row.fact_id != row.canonical_fact_id:
                    unify(row.fact_id, row.canonical_fact_id)
                conflicts.update(tuple(sorted((row.fact_id, other))) for other in row.conflicts_with if other != row.fact_id)
                related.update(tuple(sorted((row.fact_id, other))) for other in row.related_fact_ids if other != row.fact_id)
        rows = {}
        for fact in facts:
            row = dict(local["facts"][fact.id])
            row.update(canonical_fact_id=root(fact.id),
                       conflicts_with=sorted({b if a == fact.id else a for a, b in conflicts if fact.id in (a, b)}),
                       related_fact_ids=sorted({b if a == fact.id else a for a, b in related if fact.id in (a, b)}))
            rows[fact.id] = row
        return {"facts": rows, "conflicts": [list(v) for v in sorted(conflicts)],
                "relations": [list(v) for v in sorted(related)], "global_complete": True,
                "rejected_merges": [{"fact_ids": list(pair), "reason": "different_nature_category_or_date"}
                                    for pair in sorted(rejected_merges)],
                "global_windows": len(windows), "canonical_facts": len({root(f.id) for f in facts})}

    return run_step(job=job, key="reconciliation_global", kind="reconciliation_global",
                    data={"cards": cards, "local": local, "policy": policy}, execute=execute,
                    contract_version="v3.2")
