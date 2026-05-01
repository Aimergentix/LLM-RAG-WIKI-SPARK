import yaml
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

@dataclass
class Persona:
    id: str
    kind: str  # character | domain
    name: str
    rules: List[str] = field(default_factory=list)
    style_weights: Dict[str, float] = field(default_factory=dict)
    version: str = "1.0.0"

@dataclass
class ActiveConfig:
    character: Optional[str] = None
    domains: List[str] = field(default_factory=list)

class PersonaStore:
    def __init__(self, root: Path):
        self.root = root
        self.active_path = root / "active.yaml"
        self.root.mkdir(parents=True, exist_ok=True)

    def load_persona(self, persona_id: str) -> Persona:
        path = self.root / f"{persona_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Persona {persona_id} not found at {path}")
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
            return Persona(**data)

    def list_personas(self, kind: Optional[str] = None) -> List[Persona]:
        results = []
        for f in self.root.glob("*.yaml"):
            if f.name == "active.yaml" or f.name == "meta_directives.yaml":
                continue
            with open(f, 'r') as fh:
                data = yaml.safe_load(fh)
                p = Persona(**data)
                if kind is None or p.kind == kind:
                    results.append(p)
        return results

    def get_active_config(self) -> ActiveConfig:
        if not self.active_path.exists():
            return ActiveConfig()
        with open(self.active_path, 'r') as f:
            data = yaml.safe_load(f) or {}
            return ActiveConfig(
                character=data.get("character"),
                domains=data.get("domains", [])
            )

    def set_active_character(self, persona_id: str):
        config = self.get_active_config()
        # Verify existence
        self.load_persona(persona_id) 
        config.character = persona_id
        self._save_active(config)

    def toggle_domain(self, persona_id: str):
        config = self.get_active_config()
        self.load_persona(persona_id)
        if persona_id in config.domains:
            config.domains.remove(persona_id)
        else:
            config.domains.append(persona_id)
        self._save_active(config)

    def load_meta_directives(self) -> List[str]:
        path = self.root / "meta_directives.yaml"
        if not path.exists():
            return []
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
            return data.get("meta_directives", [])

    def _save_active(self, config: ActiveConfig):
        tmp = self.active_path.with_suffix(".tmp")
        with open(tmp, 'w') as f:
            yaml.safe_dump(asdict(config), f)
        os.replace(tmp, self.active_path)