import subprocess
import pytest
import shutil
from pathlib import Path
import time

@pytest.fixture
def integration_env(tmp_path):
    """Sets up a minimal wiki structure for integration testing."""
    project_root = Path(__file__).parents[1]
    wiki_root = tmp_path / "test-wiki"
    
    # 1. Run Init (M1)
    subprocess.run([
        "python3", str(project_root / "src/wiki/init.py"),
        "IntegrationTest", "Test wiki for M14", str(wiki_root)
    ], check=True)
    
    return wiki_root, project_root

def test_end_to_end_pipeline(integration_env):
    wiki_root, project_root = integration_env
    
    # A. Entry Layer: Drop a file
    entry_file = wiki_root / "entry/alpha_source.md"
    entry_file.write_text("# Alpha Concept\nAlpha is the first letter and a test concept.")
    
    # B. Wiki Layer: Autoconvert (M2)
    subprocess.run(["bash", str(project_root / "src/wiki/autoconvert.sh"), str(wiki_root)], check=True)
    assert (wiki_root / "raw/alpha-source.md").exists()
    
    # C. Wiki Layer: Ingest (M3)
    # Note: Using stub agent for deterministic integration test
    env = {"LLMWIKI_TEST_STUB_AGENT": "1"}
    subprocess.run([
        "python3", "-m", "wiki.ingest", "alpha-source", "--wiki-root", str(wiki_root)
    ], check=True, cwd=str(project_root / "src"), env=env)
    
    assert (wiki_root / "wiki/sources/alpha-source.md").exists()
    
    # D. RAG Layer: Ingest (M8)
    # Use a local test config pointing to the temp wiki
    test_config_path = wiki_root / "test_config.yaml"
    shutil.copy(project_root / "config.yaml", test_config_path)
    
    # Adjust config to point to temp paths
    import yaml
    with open(test_config_path, 'r') as f:
        cfg_data = yaml.safe_load(f)
    
    cfg_data["paths"]["wiki_root"] = str(wiki_root / "wiki")
    cfg_data["paths"]["index_dir"] = str(wiki_root / "data/chroma")
    cfg_data["paths"]["manifest_path"] = str(wiki_root / "data/manifests/manifest.json")
    
    with open(test_config_path, 'w') as f:
        yaml.dump(cfg_data, f)
        
    env_rag = {"LLM_RAG_WIKI_TEST_STUB_EMBEDDER": "1"}
    subprocess.run([
        "python3", "-m", "rag.ingest", "--config", str(test_config_path)
    ], check=True, cwd=str(project_root / "src"), env=env_rag)
    
    assert (wiki_root / "data/manifests/manifest.json").exists()

    # E. RAG Layer: Retrieval (M9)
    result = subprocess.run([
        "python3", "-m", "rag.retrieve", "Alpha", "--config", str(test_config_path), "--format", "json"
    ], capture_output=True, text=True, check=True, cwd=str(project_root / "src"), env=env_rag)
    
    import json
    resp = json.loads(result.stdout)
    assert resp["status"] == "ok"
    assert len(resp["results"]) > 0
    
    print("\nIntegration Test PASSED: Entry -> Raw -> Wiki -> Chroma -> Retrieval")

if __name__ == "__main__":
    pytest.main([__file__])