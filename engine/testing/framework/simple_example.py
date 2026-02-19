"""
Simple Example - Most Common Use Case
Quick copy-paste example for benchmarking
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from framework import ResultStore, TestMonitor, ReportGenerator
import time


def run_simple_benchmark():
    """Simple benchmark example - copy and adapt this"""
    
    # 1. Initialize
    store = ResultStore(output_dir="simple_results")
    monitor = TestMonitor(title="Simple Benchmark")
    
    # 2. Define your tests
    tests = [
        {"name": "Baseline Performance", "duration": 1.0},
        {"name": "Optimized Performance", "duration": 0.4},
    ]
    
    # 3. Run tests
    results = {}
    for test in tests:
        monitor.start_test(test["name"])
        
        # YOUR CODE HERE - replace this with your actual test
        time.sleep(test["duration"])
        test_result = {"latency_ms": test["duration"] * 1000}
        results[test["name"]] = test_result
        
        conclusion = f"Latency: {test_result['latency_ms']:.1f}ms"
        monitor.end_test("passed", conclusion)
        
        # Store result
        store.add_result(
            test_name=test["name"],
            hypothesis=f"{test['name']} meets performance targets",
            result=test_result
        )
    
    # 4. Add comparison (if you have baseline vs optimized)
    if len(results) >= 2:
        baseline = list(results.values())[0]
        optimized = list(results.values())[1]
        
        improvement = ((baseline["latency_ms"] - optimized["latency_ms"]) / 
                      baseline["latency_ms"] * 100)
        
        store.add_comparison(
            test_name="Overall Comparison",
            hypothesis="Optimized version is faster",
            baseline=baseline,
            variant=optimized,
            conclusion=f"PASSED: {improvement:.1f}% improvement"
        )
    
    # 5. Print summary
    monitor.print_summary()
    
    # 6. Generate HTML report
    generator = ReportGenerator.from_result_store(store)
    generator.set_metadata({
        "Device": "Your GPU",
        "Framework": "Your Framework",
    })
    
    report_path = generator.generate(
        title="Simple Benchmark Results",
        auto_open=False  # Set True to open in browser
    )
    
    print(f"\n[SUCCESS] Report saved: {report_path}")


if __name__ == "__main__":
    print("\nRunning Simple Benchmark Example\n")
    run_simple_benchmark()
