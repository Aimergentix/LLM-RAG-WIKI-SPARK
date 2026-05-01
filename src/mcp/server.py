from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.store import PersonaStore
from mcp.compiler import compile_profile # Assumed from M12

# Initialize FastMCP server
mcp = FastMCP("LLM-RAG-WIKI Persona Server")

# Initialize store pointing to the personas directory
# Paths are resolved relative to the project root
REPO_ROOT = Path(__file__).parents[2]
store = PersonaStore(REPO_ROOT / "personas")

@mcp.resource("persona://current")
def get_current_profile() -> str:
    """Returns the compiled runtime profile for the currently active personas."""
    active = store.get_active_config()
    active_personas = []
    
    if active.character:
        active_personas.append(store.load_persona(active.character))
    
    for domain_id in active.domains:
        active_personas.append(store.load_persona(domain_id))
        
    meta_directives = store.load_meta_directives()
    
    # M12 Compiler logic: Merges personas into a dense prose profile
    return compile_profile(active_personas, meta_directives)

@mcp.resource("persona://list")
def list_available_personas() -> str:
    """Lists all available character and domain personas."""
    personas = store.list_personas()
    output = ["Available Personas:"]
    for p in personas:
        output.append(f"- [{p.kind}] {p.id}: {p.name} (v{p.version})")
    return "\n".join(output)

@mcp.tool()
def activate_persona(persona_id: str) -> str:
    """Sets the primary character persona."""
    try:
        store.set_active_character(persona_id)
        return f"Success: Character set to {persona_id}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def toggle_domain(domain_id: str) -> str:
    """Toggles a domain persona on or off."""
    try:
        store.toggle_domain(domain_id)
        return f"Success: Toggled domain {domain_id}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    # Start the server (stdio transport)
    mcp.run()