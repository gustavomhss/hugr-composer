"""
SKILL-001 Module Loader

Loads core + relevant modules based on user story analysis.
The orchestrator calls load_skill(user_story) and gets back a SkillPack
with assembled knowledge, tools, and examples.
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

SKILL_ROOT = Path(__file__).parent


@dataclass
class ModuleInfo:
    """Metadata about a skill module from manifest.yaml."""
    name: str
    description: str
    keywords: list[str]
    knowledge_path: Path
    models_path: Path | None
    tools_dir: Path | None


@dataclass
class LoadedModule:
    """A loaded module with its knowledge content and tool functions."""
    name: str
    knowledge: str
    tools: dict[str, Callable] = field(default_factory=dict)


@dataclass
class SkillPack:
    """The assembled skill pack ready to inject into a worker agent."""
    knowledge: str  # Combined KNOWLEDGE.md content (core + modules)
    tools: dict[str, Callable]  # All tool functions (core + modules)
    modules_loaded: list[str]  # Names of modules that were loaded


def load_manifest() -> dict:
    """Load the skill manifest."""
    manifest_path = SKILL_ROOT / "manifest.yaml"
    with open(manifest_path) as f:
        return yaml.safe_load(f)


def get_available_modules() -> dict[str, ModuleInfo]:
    """Get all available modules from manifest."""
    manifest = load_manifest()
    modules = {}
    for name, config in manifest.get("modules", {}).items():
        modules[name] = ModuleInfo(
            name=name,
            description=config.get("description", ""),
            keywords=config.get("keywords", []),
            knowledge_path=SKILL_ROOT / config["knowledge"],
            models_path=SKILL_ROOT / config["models"] if config.get("models") else None,
            tools_dir=SKILL_ROOT / config["tools"] if config.get("tools") else None,
        )
    return modules


def detect_modules(user_story: str) -> list[str]:
    """
    Detect which modules are relevant for a user story.

    Uses keyword matching against the manifest.
    Returns module names sorted by relevance (most keyword matches first).

    Examples:
        "Build a payment API with Stripe webhooks and JWT auth"
        → ["payments", "auth", "security"]

        "Add WebSocket chat with Redis pub/sub"
        → ["websockets", "caching"]

        "Deploy FastAPI to Kubernetes with monitoring"
        → ["deployment", "observability"]
    """
    story_lower = user_story.lower()
    modules = get_available_modules()

    scores: dict[str, int] = {}
    for name, info in modules.items():
        score = 0
        for keyword in info.keywords:
            # Match whole words to avoid false positives
            pattern = r'\b' + re.escape(keyword) + r'\b'
            matches = len(re.findall(pattern, story_lower))
            score += matches
        if score > 0:
            scores[name] = score

    # Sort by score descending
    return sorted(scores.keys(), key=lambda k: scores[k], reverse=True)


def load_module(name: str) -> LoadedModule:
    """
    Load a single module's knowledge and tools.

    Knowledge is read from KNOWLEDGE.md.
    Tools are imported from the tools/ directory.
    """
    if name == "core":
        knowledge_path = SKILL_ROOT / "core" / "KNOWLEDGE.md"
        tools_dir = SKILL_ROOT / "core" / "tools"
    else:
        modules = get_available_modules()
        if name not in modules:
            raise ValueError(f"Unknown module: {name}. Available: {list(modules.keys())}")
        info = modules[name]
        knowledge_path = info.knowledge_path
        tools_dir = info.tools_dir

    # Load knowledge
    knowledge = ""
    if knowledge_path.exists():
        knowledge = knowledge_path.read_text()

    # Discover tool functions
    tools: dict[str, Callable] = {}
    if tools_dir and tools_dir.exists():
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                # Import the module
                module_path = py_file.relative_to(SKILL_ROOT)
                module_dotpath = str(module_path).replace("/", ".").replace(".py", "")
                mod = importlib.import_module(module_dotpath)

                # Collect all public functions (tool functions)
                for attr_name in dir(mod):
                    if attr_name.startswith("_"):
                        continue
                    attr = getattr(mod, attr_name)
                    if callable(attr) and hasattr(attr, "__module__") and attr.__module__ == mod.__name__:
                        tool_name = f"{name}_{attr_name}" if name != "core" else attr_name
                        tools[tool_name] = attr
            except (ImportError, AttributeError) as e:
                # Module not ready yet — skip silently
                pass

    return LoadedModule(name=name, knowledge=knowledge, tools=tools)


def load_skill(user_story: str) -> SkillPack:
    """
    Main entry point. Assembles a skill pack for a given user story.

    1. Always loads core knowledge + tools
    2. Detects relevant modules from user story
    3. Loads each relevant module's knowledge + tools
    4. Returns assembled SkillPack

    Example:
        pack = load_skill("Build a payment API with Stripe webhooks and JWT auth")
        # pack.modules_loaded == ["core", "payments", "auth", "security"]
        # pack.knowledge == core + payments + auth + security KNOWLEDGE.md
        # pack.tools == core tools + payments tools + auth tools + security tools
    """
    # Always load core
    core = load_module("core")

    # Detect and load relevant modules
    relevant_names = detect_modules(user_story)
    modules = [load_module(name) for name in relevant_names]

    # Assemble knowledge: core first, then modules in relevance order
    knowledge_parts = [core.knowledge]
    for mod in modules:
        if mod.knowledge:
            knowledge_parts.append(f"\n\n---\n\n# Module: {mod.name.upper()}\n\n{mod.knowledge}")

    # Merge tools (core tools can be overridden by module tools)
    all_tools = dict(core.tools)
    for mod in modules:
        all_tools.update(mod.tools)

    return SkillPack(
        knowledge="\n".join(knowledge_parts),
        tools=all_tools,
        modules_loaded=["core"] + relevant_names,
    )


# ─── CLI ───

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python loader.py <user_story>")
        print("       python loader.py modules")
        print("       python loader.py detect '<user story>'")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "modules":
        modules = get_available_modules()
        for name, info in modules.items():
            print(f"  {name:20s} — {info.description}")
            print(f"  {'':20s}   keywords: {', '.join(info.keywords[:5])}...")

    elif cmd == "detect":
        story = " ".join(sys.argv[2:])
        detected = detect_modules(story)
        print(f"User story: {story}")
        print(f"Modules:    {', '.join(detected) if detected else '(none — only core)'}")

    else:
        story = " ".join(sys.argv[1:])
        pack = load_skill(story)
        print(f"Modules loaded: {pack.modules_loaded}")
        print(f"Knowledge size: {len(pack.knowledge)} chars")
        print(f"Tools: {list(pack.tools.keys())}")
