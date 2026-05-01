"""M12 Persona Compiler.

Transforms validated Persona and MetaDirective objects into deterministic,
token-optimized runtime profiles ("The Crusher").
"""

import hashlib
import json
from typing import Any, Dict, List

import yaml
from .store import Persona, MetaDirective

class PersonaCompiler:
    """Implements token-optimized compilation per MASTER §15."""

    VERSION = "v1"  # Profile schema version

    def compile_dense(self, personas: List[Persona], meta_directives: List[MetaDirective]) -> str:
        """Produces the ultra-dense string (current.txt)."""
        # Precedence: Meta-Directives -> Personas
        
        # 1. Collect Meta IDs
        meta_ids = ",".join(m.id for m in sorted(meta_directives, key=lambda x: x.priority, reverse=True))
        
        # 2. Collect Persona IDs by kind
        chars = [p.id for p in personas if p.kind == "character"]
        doms = [p.id for p in personas if p.kind == "domain"]
        
        # 3. Consolidate Rules (Deduplicated, deterministic order)
        all_rules = []
        # Meta rules first
        for m in sorted(meta_directives, key=lambda x: x.priority, reverse=True):
            if m.rule not in all_rules:
                all_rules.append(m.rule)
        # Persona rules
        for p in personas:
            for r in p.rules:
                if r not in all_rules:
                    all_rules.append(r)

        # 4. Hash for staleness check
        full_content = f"{meta_ids}|{','.join(chars)}|{','.join(doms)}|{all_rules}"
        content_hash = hashlib.sha256(full_content.encode()).hexdigest()[:8]

        # 5. Assemble "Crushed" String
        # Format: <P_CTX:v{version}|Meta:[ids]|Char:id|Dom:[ids]|Rules:[...]|Hash:8>
        meta_part = f"Meta:[{meta_ids}]" if meta_ids else "Meta:none"
        char_part = f"Char:{chars[0]}" if chars else "Char:none"
        dom_part = f"Dom:[{','.join(doms)}]" if doms else "Dom:none"
        
        # Compact rules: join with semicolons, strip trailing periods to save tokens
        compact_rules = ";".join(r.rstrip('.') for r in all_rules)
        
        return f"<P_CTX:{self.VERSION}|{meta_part}|{char_part}|{dom_part}|Rules:{compact_rules}|Hash:{content_hash}>"

    def compile_structured(self, personas: List[Persona], meta_directives: List[MetaDirective]) -> Dict[str, Any]:
        """Produces the structured JSON profile (current.json)."""
        return {
            "schema_version": self.VERSION,
            "meta_directives": [
                {"id": m.id, "priority": m.priority, "rule": m.rule}
                for m in sorted(meta_directives, key=lambda x: x.priority, reverse=True)
            ],
            "personas": [
                {
                    "id": p.id,
                    "kind": p.kind,
                    "name": p.name,
                    "version": p.version,
                    "rules": p.rules,
                    "style_weights": p.style_weights
                } for p in personas
            ],
            "summary": {
                "character": next((p.id for p in personas if p.kind == "character"), None),
                "domains": [p.id for p in personas if p.kind == "domain"]
            }
        }

    def compile_debug(self, personas: List[Persona], meta_directives: List[MetaDirective]) -> str:
        """Produces human-readable debug YAML (current.debug.yaml)."""
        data = self.compile_structured(personas, meta_directives)
        return yaml.dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)

    def generate_all(self, personas: List[Persona], meta_directives: List[MetaDirective]) -> Dict[str, str]:
        """Convenience wrapper to generate all three formats."""
        return {
            "dense": self.compile_dense(personas, meta_directives),
            "json": json.dumps(self.compile_structured(personas, meta_directives), indent=2),
            "debug": self.compile_debug(personas, meta_directives)
        }

def main():
    """Basic CLI for testing compilation logic."""
    import sys
    from pathlib import Path
    from .store import PersonaStore

    if len(sys.argv) < 2:
        print("Usage: python -m mcp.compiler <persona_id_1> [persona_id_2] ...")
        sys.exit(1)

    store = PersonaStore(Path.cwd())
    compiler = PersonaCompiler()
    
    try:
        personas = [store.load_persona(pid) for pid in sys.argv[1:]]
        metas = store.load_meta_directives()
        
        outputs = compiler.generate_all(personas, metas)
        print("--- ULTRA DENSE ---")
        print(outputs["dense"])
    except Exception as e:
        print(f"[ERR_RUNTIME] Compilation failed: {e}")
        sys.exit(5)

if __name__ == "__main__":
    main()