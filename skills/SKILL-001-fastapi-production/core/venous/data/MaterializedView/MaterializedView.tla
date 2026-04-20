---- MODULE MaterializedView ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Keys, MaxSeq
VARIABLES appliedSeq, viewRows, sourceLog, schemaVersion, viewSchema, pendingRebuild

TypeOK ==
    /\ appliedSeq \in 0..MaxSeq
    /\ viewRows \subseteq Keys
    /\ sourceLog \in Seq(Keys)
    /\ schemaVersion \in 1..3
    /\ viewSchema \in (1..3) \cup {0}   \* 0 = not-yet-materialized
    /\ pendingRebuild \in BOOLEAN

Init ==
    /\ appliedSeq = 0
    /\ viewRows = {}
    /\ sourceLog = <<>>
    /\ schemaVersion = 1
    /\ viewSchema = 0
    /\ pendingRebuild = FALSE

\* The source stream appends a new event for some key.
SourceEmit(k) ==
    /\ Len(sourceLog) < MaxSeq
    /\ sourceLog' = Append(sourceLog, k)
    /\ UNCHANGED <<appliedSeq, viewRows, schemaVersion, viewSchema, pendingRebuild>>

\* Apply the next event from the source. Only allowed when NOT pendingRebuild.
\* Progress is bounded by appliedSeq < Len(sourceLog).
Apply ==
    /\ appliedSeq < Len(sourceLog)
    /\ ~pendingRebuild
    /\ appliedSeq' = appliedSeq + 1
    /\ viewRows' = viewRows \cup {sourceLog[appliedSeq + 1]}
    /\ viewSchema' = schemaVersion
    /\ UNCHANGED <<sourceLog, schemaVersion, pendingRebuild>>

\* Duplicate / out-of-order delivery — must dedupe.
ApplyDuplicate ==
    /\ appliedSeq > 0
    /\ ~pendingRebuild
    /\ UNCHANGED <<appliedSeq, viewRows, sourceLog, schemaVersion, viewSchema, pendingRebuild>>

\* Rebuild: regenerate state from the source log. Clears the view, replays all events.
Rebuild ==
    LET newRows == {sourceLog[i] : i \in 1..Len(sourceLog)}
    IN  /\ viewRows' = newRows
        /\ appliedSeq' = Len(sourceLog)
        /\ viewSchema' = schemaVersion
        /\ pendingRebuild' = FALSE
        /\ UNCHANGED <<sourceLog, schemaVersion>>

\* Schema evolution: bump declared version, mark pendingRebuild.
EvolveSchema ==
    /\ schemaVersion < 3
    /\ schemaVersion' = schemaVersion + 1
    /\ pendingRebuild' = TRUE
    /\ UNCHANGED <<appliedSeq, viewRows, sourceLog, viewSchema>>

Next ==
    \/ \E k \in Keys: SourceEmit(k)
    \/ Apply
    \/ ApplyDuplicate
    \/ Rebuild
    \/ EvolveSchema

Spec == Init /\ [][Next]_<<appliedSeq, viewRows, sourceLog, schemaVersion, viewSchema, pendingRebuild>>

\* Safety: view convergence — rows are always a subset of the keys ever emitted
\* (MV-INV-01 determinism: view is pure function of the ordered source prefix).
ViewSubsetOfSource ==
    viewRows \subseteq {sourceLog[i] : i \in 1..Len(sourceLog)}

\* Safety: appliedSeq never exceeds source length (MV-INV-01 monotonicity).
AppliedSeqBounded == appliedSeq <= Len(sourceLog)

\* Safety: MV-INV-02 — after Rebuild, the view equals the full source projection,
\* i.e. the view is NOT the system of record.
RebuildIsComplete ==
    (~pendingRebuild /\ viewSchema = schemaVersion /\ appliedSeq = Len(sourceLog)) =>
        viewRows = {sourceLog[i] : i \in 1..Len(sourceLog)}

\* Safety: MV-INV-04 — while pendingRebuild is true, viewSchema lags
\* declared schemaVersion, i.e. query should refuse (enforced at impl).
SchemaEvolutionGated ==
    pendingRebuild => (viewSchema < schemaVersion \/ viewSchema = 0)

====
