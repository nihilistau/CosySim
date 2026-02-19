"""
Result Storage System
Stores benchmark results in structured JSON format with metadata
"""
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import hashlib


class ResultStore:
    """Stores and manages benchmark results"""
    
    def __init__(self, output_dir: str = "test_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.results: List[Dict[str, Any]] = []
        
    def add_result(
        self,
        test_name: str,
        hypothesis: str,
        result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a test result"""
        result_id = hashlib.md5(
            f"{test_name}_{time.time()}".encode()
        ).hexdigest()[:8]
        
        record = {
            "result_id": result_id,
            "test_name": test_name,
            "hypothesis": hypothesis,
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "result": result,
            "metadata": metadata or {},
        }
        
        self.results.append(record)
        self._save()
        return result_id
    
    def add_comparison(
        self,
        test_name: str,
        hypothesis: str,
        baseline: Dict[str, Any],
        variant: Dict[str, Any],
        conclusion: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a comparison result"""
        result = {
            "type": "comparison",
            "baseline": baseline,
            "variant": variant,
            "conclusion": conclusion,
        }
        return self.add_result(test_name, hypothesis, result, metadata)
    
    def get_session_results(self) -> List[Dict[str, Any]]:
        """Get all results from current session"""
        return [r for r in self.results if r["session_id"] == self.session_id]
    
    def get_test_results(self, test_name: str) -> List[Dict[str, Any]]:
        """Get all results for a specific test"""
        return [r for r in self.results if r["test_name"] == test_name]
    
    def _save(self):
        """Save results to JSON file"""
        filepath = self.output_dir / f"results_{self.session_id}.json"
        with open(filepath, 'w') as f:
            json.dump({
                "session_id": self.session_id,
                "created": datetime.now().isoformat(),
                "results": self.results,
            }, f, indent=2)
    
    @classmethod
    def load_session(cls, session_id: str, output_dir: str = "test_results") -> "ResultStore":
        """Load a previous session"""
        store = cls(output_dir)
        filepath = store.output_dir / f"results_{session_id}.json"
        
        if not filepath.exists():
            raise FileNotFoundError(f"Session {session_id} not found")
        
        with open(filepath) as f:
            data = json.load(f)
            store.results = data["results"]
            store.session_id = session_id
        
        return store
    
    def export_summary(self) -> Dict[str, Any]:
        """Export summary statistics"""
        return {
            "session_id": self.session_id,
            "total_tests": len(self.results),
            "tests_by_name": self._count_by_field("test_name"),
            "latest_result": self.results[-1] if self.results else None,
        }
    
    def _count_by_field(self, field: str) -> Dict[str, int]:
        """Count results by field value"""
        counts = {}
        for r in self.results:
            value = r.get(field, "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts


class TestHypothesis:
    """Represents a test hypothesis"""
    
    def __init__(
        self,
        description: str,
        expected_outcome: str,
        variables: Optional[Dict[str, Any]] = None
    ):
        self.description = description
        self.expected_outcome = expected_outcome
        self.variables = variables or {}
        self.actual_outcome: Optional[str] = None
        self.validated: Optional[bool] = None
    
    def validate(self, actual_outcome: str, matches: bool):
        """Validate hypothesis against actual outcome"""
        self.actual_outcome = actual_outcome
        self.validated = matches
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "description": self.description,
            "expected": self.expected_outcome,
            "actual": self.actual_outcome,
            "validated": self.validated,
            "variables": self.variables,
        }
