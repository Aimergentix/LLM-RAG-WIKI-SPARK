import logging
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict

from rag.config import load_config, Config
from rag.retrieve import query_rag, RetrievalResponse
from rag.embedder import SentenceTransformersEmbedder
from rag._query_store import ChromaQueryAdapter

logger = logging.getLogger("rag.eval")

@dataclass
class EvalResult:
    case_id: str
    passed: bool
    actual_status: str
    message: str

def run_evals(cfg: Config, cases_path: Path) -> List[EvalResult]:
    with open(cases_path, 'r') as f:
        data = yaml.safe_load(f)
    
    cases = data.get("cases", [])
    results = []
    
    # Initialize production backends
    embedder = SentenceTransformersEmbedder(cfg.embedding.model_id)
    adapter = ChromaQueryAdapter(cfg.paths.index_dir, cfg.domain.name)
    
    for case in cases:
        case_id = case["id"]
        query = case["query"]
        expected_status = case.get("expected_status")
        
        resp = query_rag(cfg, query, embedder=embedder, adapter=adapter)
        
        passed = True
        messages = []
        
        # 1. Check Status
        if expected_status and resp.status != expected_status:
            passed = False
            messages.append(f"Expected status {expected_status}, got {resp.status}")
            
        # 2. Check Sources (for positive cases)
        expected_sources = case.get("expected_sources", [])
        actual_sources = [r.source for r in resp.results]
        for src in expected_sources:
            if src not in actual_sources:
                passed = False
                messages.append(f"Missing expected source: {src}")
                
        # 3. Check Injection Marker Safety
        if case.get("must_contain_withheld_marker"):
            has_marker = any("[content withheld" in r.excerpt for r in resp.results)
            if not has_marker and resp.status == "ok":
                passed = False
                messages.append("Failed to withhold prompt-injection marker text")

        results.append(EvalResult(
            case_id=case_id,
            passed=passed,
            actual_status=resp.status,
            message="; ".join(messages) if messages else "PASS"
        ))
        
    return results

def print_report(results: List[EvalResult]):
    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    
    print("\n" + "="*50)
    print(f"RAG EVALUATION REPORT: {passed_count}/{total} PASSED")
    print("="*50)
    
    for r in results:
        status_icon = "✅" if r.passed else "❌"
        print(f"{status_icon} [{r.case_id}] {r.actual_status}: {r.message}")
    print("="*50 + "\n")

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--cases", type=Path, default=Path("tests/eval_cases.yaml"))
    args = parser.parse_args()
    
    try:
        cfg = load_config(args.config)
        results = run_evals(cfg, args.cases)
        print_report(results)
        
        if not all(r.passed for r in results):
            sys.exit(1)
    except Exception as e:
        print(f"Eval Runner Error: {e}")
        sys.exit(1)