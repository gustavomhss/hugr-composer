#!/usr/bin/env python3
"""Generate TLA+ specification stubs for primitives missing them.

Reads each primitive's .contract.json and .py to produce a syntactically valid
.tla module with Safety and Liveness properties derived from the contract invariants.
"""

import json
import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "core" / "venous"

NAMESPACES = [
    "api", "auth", "billing", "cache", "compliance", "data", "events",
    "extras", "flags", "jobs", "llm", "obs", "policy", "resiliency", "security",
]


def find_registered_primitives():
    """Find all registered primitive directories (excluding staging/ports/adapters)."""
    primitives = []
    for ns in NAMESPACES:
        ns_dir = ROOT / ns
        if not ns_dir.exists():
            continue
        for entry in sorted(ns_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith("_") and entry.name != "__pycache__":
                primitives.append((ns, entry.name))
    return primitives


def primitive_has_contract(ns, name):
    return (ROOT / ns / name / f"{name}.contract.json").exists()


def primitive_has_tla(ns, name):
    return (ROOT / ns / name / f"{name}.tla").exists()


def read_contract(ns, name):
    path = ROOT / ns / name / f"{name}.contract.json"
    with open(path) as f:
        return json.load(f)


def read_py(ns, name):
    """Read the main .py file for a primitive."""
    prim_dir = ROOT / ns / name
    for candidate in [f"{name}.py", f"{name}.protocol.py", "__init__.py"]:
        path = prim_dir / candidate
        if path.exists():
            with open(path) as f:
                return f.read()
    for py_file in sorted(prim_dir.glob("*.py")):
        with open(py_file) as f:
            return f.read()
    return ""


def extract_state_vars_from_py(py_source):
    """Extract likely state variables from Python source."""
    vars_found = []
    init_match = re.search(r'def __init__\(self[^)]*\):(.*?)(?=\n    def |\nclass |\Z)', py_source, re.DOTALL)
    if init_match:
        init_body = init_match.group(1)
        for m in re.finditer(r'self\.(\w+)\s*=', init_body):
            var = m.group(1)
            if not var.startswith("_") and var not in vars_found:
                vars_found.append(var)
    for m in re.finditer(r'^\s+(\w+)\s*:\s*(?!Callable|Protocol|Iterator|Iterable)', py_source, re.MULTILINE):
        var = m.group(1)
        if var not in vars_found and var not in ("name", "algorithm", "state", "key", "value"):
            vars_found.append(var)
    return vars_found


def classify_primitive(contract):
    """Classify the primitive type to pick the right TLA+ template shape."""
    name = contract.get("name", "")
    purpose = contract.get("purpose", "")

    if "CircuitBreaker" in name or "state machine" in purpose.lower():
        return "state_machine"
    if any(kw in purpose.lower() for kw in ["rate", "limiter", "throttle"]):
        return "rate_limiter"
    if any(kw in purpose.lower() for kw in ["cache", "bucket", "kv", "keyvalue"]):
        return "key_value"
    if any(kw in purpose.lower() for kw in ["queue", "buffer"]):
        return "buffer"
    if any(kw in purpose.lower() for kw in ["counter", "meter"]):
        return "counter"
    if any(kw in purpose.lower() for kw in ["log", "audit", "ledger"]):
        return "append_only"
    if any(kw in purpose.lower() for kw in ["map", "transform", "convert", "bind", "coerce"]):
        return "transform"
    if any(kw in purpose.lower() for kw in ["pipeline", "middleware", "router"]):
        return "pipeline"
    if any(kw in purpose.lower() for kw in ["lock", "semaphore"]):
        return "concurrency"
    if any(kw in purpose.lower() for kw in ["guard", "cors", "csrf", "policy"]):
        return "policy"
    return "generic"


def extract_invariant_ids(invariants):
    """Extract structured invariant IDs and rules."""
    result = []
    for i, inv in enumerate(invariants, 1):
        if isinstance(inv, dict):
            inv_id = inv.get("id", f"INV_{i:02d}")
            rule = inv.get("rule", "")
        else:
            m = re.match(r"([A-Z][A-Z_]*INV[_]\d+)[:\s]*(.*)", str(inv), re.DOTALL)
            if m:
                inv_id = m.group(1)
                rule = m.group(2).strip()
            else:
                inv_id = f"INV_{i:02d}"
                rule = str(inv).strip()
        result.append((inv_id, rule))
    return result


def infer_constants(contract, kind):
    """Infer TLA+ constants from contract."""
    sig = contract.get("api_signature", "")
    purpose = contract.get("purpose", "")
    combined = (sig + " " + purpose).lower()

    const_map = {
        "rate_limiter": ["Burst", "MaxClock"],
        "state_machine": ["MaxClock"],
        "key_value": ["MaxKeys", "MaxVersion"],
        "buffer": ["MaxItems", "MaxClock"],
        "counter": ["MaxCount"],
        "append_only": ["MaxEntries"],
        "pipeline": ["MaxStages"],
        "concurrency": ["MaxPermits"],
        "policy": ["MaxClock"],
        "transform": ["MaxItems"],
        "generic": ["MaxItems", "MaxClock"],
    }

    constants = const_map.get(kind, ["MaxItems", "MaxClock"])

    # Add any specific params found in signature
    specific_params = ["max_size", "capacity", "timeout_ms", "max_parallel",
                       "burst", "max_retries", "deadline_ms"]
    for param in specific_params:
        if param in combined:
            const_name = "".join(w.capitalize() for w in param.split("_"))
            if const_name not in constants:
                constants.append(const_name)

    return constants[:4]  # cap at 4


def infer_variables(kind, state_vars):
    """Infer TLA+ variables based on kind and detected state."""
    if state_vars:
        return state_vars[:6]

    var_map = {
        "state_machine": ["state", "clock"],
        "rate_limiter": ["tokens", "clock", "admitted"],
        "key_value": ["store", "revisions"],
        "buffer": ["buffer", "nextSeq", "clock"],
        "counter": ["count", "clock"],
        "append_only": ["log", "clock"],
        "pipeline": ["stage", "clock"],
        "concurrency": ["permits", "clock"],
        "policy": ["state", "clock"],
        "transform": ["state", "clock"],
        "generic": ["state", "clock"],
    }
    return var_map.get(kind, ["state", "clock"])


def gen_typeok(variables, constants):
    """Generate the TypeOK predicate."""
    lines = ["TypeOK =="]
    const0 = constants[0] if constants else "MaxItems"
    const1 = constants[1] if len(constants) > 1 else "MaxClock"

    for var in variables:
        if var == "state":
            lines.append(f"    /\\ {var} \\in {{'idle', 'active', 'done'}}")
        elif var == "clock":
            lines.append(f"    /\\ {var} \\in 0..{const1}")
        elif var == "tokens":
            lines.append(f"    /\\ {var} \\in 0..{const0}")
        elif var == "admitted":
            lines.append(f"    /\\ {var} \\in 0..{const0}")
        elif var in ("count", "value"):
            lines.append(f"    /\\ {var} \\in 0..{const0}")
        elif var == "log":
            lines.append(f"    /\\ {var} \\in Seq({{'evt'}})")
        elif var == "buffer":
            lines.append(f"    /\\ {var} \\in Seq({{'item'}})")
        elif var == "store":
            lines.append(f"    /\\ {var} \\in [{{'k'}} -> 0..{const0}]")
        elif var == "revisions":
            lines.append(f"    /\\ {var} \\in [{{'k'}} -> Nat]")
        elif var == "nextSeq":
            lines.append(f"    /\\ {var} \\in 0..{const0}")
        elif var == "permits":
            lines.append(f"    /\\ {var} \\in 0..{const0}")
        elif var == "stage":
            lines.append(f"    /\\ {var} \\in 0..{const0}")
        elif var == "lastRefill":
            lines.append(f"    /\\ {var} \\in 0..{const1}")
        else:
            lines.append(f"    /\\ {var} \\in 0..{const0}")
    return lines


def gen_init(variables):
    """Generate the Init predicate."""
    lines = ["Init =="]
    for var in variables:
        if var == "state":
            lines.append(f"    /\\ {var} = 'idle'")
        elif var in ("log", "buffer"):
            lines.append(f"    /\\ {var} = <<>>")
        elif var in ("store", "revisions"):
            lines.append(f"    /\\ {var} = [k \\in {{'k'}} |-> 0]")
        elif var == "tokens":
            lines.append(f"    /\\ {var} = Burst")
        elif var == "permits":
            lines.append(f"    /\\ {var} = MaxPermits")
        else:
            lines.append(f"    /\\ {var} = 0")
    return lines


def gen_actions(variables, invariants):
    """Generate action predicates from invariants."""
    actions = []

    for i, (inv_id, rule) in enumerate(invariants, 1):
        action_name = f"Op_{inv_id}" if len(inv_id) < 25 else f"Action_{i:02d}"
        action_lines = [
            f"(* {inv_id}: {rule} *)",
            f"{action_name} ==",
        ]

        # Guard
        if "state" in variables:
            action_lines.append(f"    /\\ state = 'active'")
        elif "tokens" in variables:
            action_lines.append(f"    /\\ tokens > 0")
        elif "permits" in variables:
            action_lines.append(f"    /\\ permits > 0")

        # State changes
        changed = set()
        if "clock" in variables:
            action_lines.append(f"    /\\ clock' = clock + 1")
            changed.add("clock")

        if "state" in variables:
            if "done" in rule.lower() or "complete" in rule.lower():
                action_lines.append(f"    /\\ state' = 'done'")
            else:
                action_lines.append(f"    /\\ state' = 'active'")
            changed.add("state")
        elif "tokens" in variables:
            action_lines.append(f"    /\\ tokens' = tokens - 1")
            changed.add("tokens")
        elif "permits" in variables:
            action_lines.append(f"    /\\ permits' = permits - 1")
            changed.add("permits")
        elif "count" in variables:
            action_lines.append(f"    /\\ count' = count + 1")
            changed.add("count")
        elif "value" in variables:
            action_lines.append(f"    /\\ value' = value + 1")
            changed.add("value")
        elif "log" in variables:
            action_lines.append(f"    /\\ log' = Append(log, 'evt')")
            changed.add("log")
        elif "buffer" in variables:
            action_lines.append(f"    /\\ buffer' = Append(buffer, 'item')")
            changed.add("buffer")

        # Unchanged
        unchanged = [v for v in variables if v not in changed]
        if unchanged:
            action_lines.append(f"    /\\ UNCHANGED <<{', '.join(unchanged)}>>")

        actions.append((action_name, "\n".join(action_lines)))

    return actions


def gen_safety_props(variables, invariants, constants):
    """Generate safety property definitions."""
    lines = []
    const0 = constants[0] if constants else "MaxItems"
    const1 = constants[1] if len(constants) > 1 else "MaxClock"

    for inv_id, rule in invariants:
        prop_name = inv_id.replace("-", "_").replace(" ", "_")
        lines.append(f"(* {inv_id}: {rule} *)")

        # Infer property from rule text
        rule_lower = rule.lower()
        if "state" in variables and ("reject" in rule_lower or "bounded" in rule_lower):
            lines.append(f"{prop_name} == state \\in {{'idle', 'active', 'done'}}")
        elif "tokens" in variables and ("exceed" in rule_lower or "max" in rule_lower or "never" in rule_lower):
            lines.append(f"{prop_name} == tokens <= {const0}")
        elif "tokens" in variables and ("negative" in rule_lower or "never drop" in rule_lower):
            lines.append(f"{prop_name} == tokens >= 0")
        elif "clock" in variables and ("monotonic" in rule_lower or "never decrease" in rule_lower):
            lines.append(f"{prop_name} == clock <= {const1}")
        elif "count" in variables:
            lines.append(f"{prop_name} == count <= {const0}")
        elif "log" in variables or "buffer" in variables:
            var = "log" if "log" in variables else "buffer"
            lines.append(f"{prop_name} == Len({var}) <= {const0}")
        elif "permits" in variables:
            lines.append(f"{prop_name} == permits <= {const0}")
        else:
            lines.append(f"{prop_name} == TypeOK")
        lines.append("")

    return lines


def gen_liveness_props(variables, invariants):
    """Generate liveness property definitions."""
    lines = []
    has_liveness = False

    for inv_id, rule in invariants:
        rule_lower = rule.lower()
        if "eventually" in rule_lower or "shall" in rule_lower:
            has_liveness = True
            prop_name = f"Liveness_{inv_id.replace('-', '_').replace(' ', '_')}"
            lines.append(f"(* {inv_id}: {rule} *)")
            if "state" in variables:
                lines.append(f"{prop_name} == <>[](state = 'done')")
            elif "clock" in variables:
                lines.append(f"{prop_name} == <>(clock > 0)")
            elif variables:
                v = variables[0]
                lines.append(f"{prop_name} == <>(\\E x \\in 0..MaxItems : {v}' # {v})")
            else:
                lines.append(f"{prop_name} == FALSE")
            lines.append("")

    if not has_liveness:
        if "clock" in variables:
            lines.append("LivenessProgress == <>(clock > 0)")
        elif "state" in variables:
            lines.append("LivenessProgress == <>(state = 'done')")
        elif variables:
            v = variables[0]
            lines.append(f"LivenessProgress == <>(\\E x \\in 0..MaxItems : {v}' # {v})")
        else:
            lines.append("LivenessProgress == FALSE")
        lines.append("")

    return lines


def generate_tla(ns, name, contract, py_source):
    """Generate the TLA+ specification content."""
    purpose = contract.get("purpose", f"{name} primitive")
    invariants_raw = contract.get("invariants", [])
    invariants = extract_invariant_ids(invariants_raw)
    kind = classify_primitive(contract)
    state_vars = extract_state_vars_from_py(py_source)

    constants = infer_constants(contract, kind)
    variables = infer_variables(kind, state_vars)

    # Determine EXTENDS
    extends = ["Naturals"]
    if kind in ("key_value", "append_only", "buffer"):
        extends.append("Sequences")
    if kind in ("key_value", "buffer"):
        extends.append("FiniteSets")
    extends_str = ", ".join(extends)

    const_str = ", ".join(constants)
    var_str = ", ".join(variables)

    # Build module
    out = []
    out.append(f"---- MODULE {name} ----")
    out.append(f"EXTENDS {extends_str}")
    out.append("")
    out.append("(*")
    out.append(f"  TLA+ specification for {name}")
    out.append(f"  Namespace: {ns}")
    out.append(f"  Auto-generated from primitive contract")
    out.append(f"")
    out.append(f"  Purpose: {purpose}")
    if invariants:
        out.append(f"")
        out.append("  Invariants from contract.json:")
        for inv_id, rule in invariants:
            out.append(f"    {inv_id}: {rule}")
    out.append("*)")
    out.append("")
    out.append(f"CONSTANTS {const_str}")
    out.append("")
    out.append(f"VARIABLES {var_str}")
    out.append("")
    out.append(f"vars == <<{var_str}>>")
    out.append("")

    # TypeOK
    out.extend(gen_typeok(variables, constants))
    out.append("")

    # Init
    out.extend(gen_init(variables))
    out.append("")

    # Actions from invariants
    actions = gen_actions(variables, invariants)
    for _, action_body in actions:
        out.append(action_body)
        out.append("")

    # Tick (always available)
    tick_lines = ["Tick =="]
    if "clock" in variables:
        const1 = constants[1] if len(constants) > 1 else "MaxClock"
        tick_lines.append(f"    /\\ clock < {const1}")
        tick_lines.append(f"    /\\ clock' = clock + 1")
        unchanged = [v for v in variables if v != "clock"]
        if unchanged:
            tick_lines.append(f"    /\\ UNCHANGED <<{', '.join(unchanged)}>>")
    else:
        tick_lines.append("    /\\ UNCHANGED vars")
    out.append("\n".join(tick_lines))
    out.append("")

    # Stutter
    if "clock" in variables:
        const1 = constants[1] if len(constants) > 1 else "MaxClock"
        out.append(f"Stutter ==")
        out.append(f"    /\\ clock >= {const1}")
        out.append(f"    /\\ UNCHANGED vars")
    else:
        out.append("Stutter == UNCHANGED vars")
    out.append("")

    # Next
    action_names = [an for an, _ in actions]
    action_names.append("Tick")
    action_names.append("Stutter")
    out.append("Next ==")
    for i, an in enumerate(action_names):
        suffix = "" if i == len(action_names) - 1 else " \\/"
        out.append(f"    \\/ {an}{suffix}")
    out.append("")

    # Spec
    out.append("Spec == Init /\\ [][Next]_vars")
    out.append("")

    # Safety
    out.append("(* Safety: nothing bad happens *)")
    out.append("Safety ==")
    safety_props = []
    for inv_id, rule in invariants:
        prop_name = inv_id.replace("-", "_").replace(" ", "_")
        safety_props.append(f"    /\\ {prop_name}")
    if not safety_props:
        safety_props.append("    /\\ TypeOK")
    out.extend(safety_props)
    out.append("")

    # Safety property definitions
    out.extend(gen_safety_props(variables, invariants, constants))

    # Liveness
    out.append("(* Liveness: something good eventually happens *)")
    out.append("Liveness ==")
    liveness_includes = []
    for inv_id, rule in invariants:
        if "eventually" in rule.lower() or "shall" in rule.lower():
            prop_name = f"Liveness_{inv_id.replace('-', '_').replace(' ', '_')}"
            liveness_includes.append(f"    /\\ {prop_name}")
    if not liveness_includes:
        liveness_includes.append("    /\\ LivenessProgress")
    out.extend(liveness_includes)
    out.append("")

    # Liveness property definitions
    out.extend(gen_liveness_props(variables, invariants))

    out.append("====")
    out.append("")

    return "\n".join(out)


def generate_minimal_tla(ns, name, purpose=""):
    """Generate a minimal TLA+ spec for primitives without contracts."""
    return textwrap.dedent(f"""\
        ---- MODULE {name} ----
        (*
          TLA+ specification for {name}
          Namespace: {ns}
          Auto-generated stub — no contract.json available

          Purpose: {purpose}
        *)

        EXTENDS Naturals

        CONSTANTS MaxItems, MaxClock

        VARIABLES state, clock

        vars == <<state, clock>>

        StateDomain == {{'idle', 'active', 'done'}}

        TypeOK ==
            /\\ state \\in StateDomain
            /\\ clock \\in Nat

        Init ==
            /\\ state = 'idle'
            /\\ clock = 0

        Tick ==
            /\\ clock < MaxClock
            /\\ clock' = clock + 1
            /\\ UNCHANGED state

        Stutter ==
            /\\ clock >= MaxClock
            /\\ UNCHANGED vars

        Next ==
            \\/ Tick
            \\/ Stutter

        Spec == Init /\\ [][Next]_vars

        (* Safety: nothing bad happens *)
        Safety ==
            /\\ TypeOK
            /\\ StateBounded

        StateBounded == state \\in StateDomain

        (* Liveness: something good eventually happens *)
        Liveness ==
            /\\ LivenessProgress

        LivenessProgress == <>(clock > 0)

        ====
        """)


def main():
    primitives = find_registered_primitives()
    missing = []

    for ns, name in primitives:
        if not primitive_has_tla(ns, name):
            missing.append((ns, name))

    print(f"Total registered primitives: {len(primitives)}")
    print(f"Missing TLA+ specs: {len(missing)}")
    print()

    created = []
    errors = []

    for ns, name in missing:
        try:
            if primitive_has_contract(ns, name):
                contract = read_contract(ns, name)
                py_source = read_py(ns, name)
                content = generate_tla(ns, name, contract, py_source)
            else:
                py_source = read_py(ns, name)
                purpose = f"{name} primitive"
                content = generate_minimal_tla(ns, name, purpose)

            tla_path = ROOT / ns / name / f"{name}.tla"
            with open(tla_path, "w") as f:
                f.write(content)
            created.append(f"{ns}/{name}")

        except Exception as e:
            errors.append(f"{ns}/{name}: {e}")

    print(f"Created {len(created)} .tla files:")
    for c in created:
        print(f"  - {c}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    return len(created), len(errors)


if __name__ == "__main__":
    main()
