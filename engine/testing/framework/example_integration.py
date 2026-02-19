"""
Complete Integration Example
Demonstrates using all framework components in a realistic benchmark scenario
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from framework import ResultStore, TestMonitor, ProgressTracker, ReportGenerator, TestHypothesis
import time
import random


class MockBenchmark:
    """Mock benchmark class simulating model inference"""
    
    def __init__(self, backend: str):
        self.backend = backend
        self.base_latency = 245.0 if backend == "pytorch" else 89.0
        self.base_memory = 2048 if backend == "pytorch" else 450
    
    def run_inference(self, num_iterations: int = 10):
        """Simulate running inference"""
        latencies = []
        for _ in range(num_iterations):
            # Simulate some variance
            latency = self.base_latency + random.uniform(-10, 10)
            latencies.append(latency)
            time.sleep(0.1)  # Simulate work
        
        return {
            "latency_ms": sum(latencies) / len(latencies),
            "min_latency_ms": min(latencies),
            "max_latency_ms": max(latencies),
            "memory_mb": self.base_memory + random.randint(-50, 50),
            "iterations": num_iterations
        }


def run_comprehensive_benchmark():
    """Run a comprehensive benchmark suite"""
    print("\n" + "="*70)
    print(" CosyVoice Comprehensive Benchmark Suite ".center(70, "="))
    print("="*70 + "\n")
    
    # Initialize framework components
    store = ResultStore(output_dir="comprehensive_results")
    monitor = TestMonitor(title="CosyVoice PyTorch vs OpenVINO Benchmark")
    
    # Define test suite
    test_suite = [
        {
            "name": "PyTorch Baseline Performance",
            "hypothesis": TestHypothesis(
                description="PyTorch provides stable baseline performance",
                expected_outcome="Latency ~245ms, Memory ~2048MB"
            ),
            "backend": "pytorch",
            "iterations": 10
        },
        {
            "name": "OpenVINO Optimized Performance",
            "hypothesis": TestHypothesis(
                description="OpenVINO significantly outperforms PyTorch",
                expected_outcome="Latency <100ms, Memory <500MB"
            ),
            "backend": "openvino",
            "iterations": 10
        },
        {
            "name": "PyTorch Sustained Load",
            "hypothesis": TestHypothesis(
                description="PyTorch maintains consistent performance under load",
                expected_outcome="Latency variance <5%"
            ),
            "backend": "pytorch",
            "iterations": 20
        },
        {
            "name": "OpenVINO Sustained Load",
            "hypothesis": TestHypothesis(
                description="OpenVINO maintains better performance under sustained load",
                expected_outcome="Latency variance <3%"
            ),
            "backend": "openvino",
            "iterations": 20
        }
    ]
    
    # Store results for comparison
    pytorch_baseline = None
    openvino_baseline = None
    
    # Run tests
    for test_config in test_suite:
        test_name = test_config["name"]
        hypothesis = test_config["hypothesis"]
        
        print(f"\n{'='*70}")
        print(f"Test: {test_name}")
        print(f"Hypothesis: {hypothesis.description}")
        print(f"Expected: {hypothesis.expected_outcome}")
        print(f"{'='*70}\n")
        
        # Start monitoring
        monitor.start_test(
            test_name,
            metadata={
                "backend": test_config["backend"],
                "iterations": test_config["iterations"]
            }
        )
        
        # Run benchmark with progress tracking
        benchmark = MockBenchmark(test_config["backend"])
        
        with ProgressTracker(
            f"Running {test_config['backend']} inference",
            total=test_config["iterations"]
        ) as progress:
            # Simulate iterations
            for i in range(test_config["iterations"]):
                time.sleep(0.1)  # Simulate work
                progress.update(1, f"Iteration {i+1}/{test_config['iterations']}")
        
        # Get results
        results = benchmark.run_inference(test_config["iterations"])
        
        # Update monitor
        for key, value in results.items():
            monitor.update_metric(key, value)
        
        # Validate hypothesis
        if "Baseline" in test_name:
            if test_config["backend"] == "pytorch":
                pytorch_baseline = results
            else:
                openvino_baseline = results
            
            actual = f"Latency: {results['latency_ms']:.1f}ms, Memory: {results['memory_mb']}MB"
            conclusion = f"PASSED - Measured {actual}"
            hypothesis.validate(actual, True)
        else:
            # Sustained load test
            variance = ((results['max_latency_ms'] - results['min_latency_ms']) / results['latency_ms']) * 100
            actual = f"Latency variance: {variance:.2f}%"
            passed = variance < (5 if test_config["backend"] == "pytorch" else 3)
            conclusion = f"{'PASSED' if passed else 'FAILED'} - {actual}"
            hypothesis.validate(actual, passed)
        
        # End monitoring
        monitor.end_test(
            status="passed" if hypothesis.validated else "failed",
            conclusion=conclusion
        )
        
        # Store result
        store.add_result(
            test_name=test_name,
            hypothesis=hypothesis.description,
            result={
                "type": "single",
                "metrics": results,
                "conclusion": conclusion,
                "validated": hypothesis.validated,
                "duration": test_config["iterations"] * 0.1
            },
            metadata={"backend": test_config["backend"]}
        )
    
    # Add comparison results
    if pytorch_baseline and openvino_baseline:
        print(f"\n{'='*70}")
        print("Computing Comparison Metrics...")
        print(f"{'='*70}\n")
        
        latency_improvement = (
            (pytorch_baseline["latency_ms"] - openvino_baseline["latency_ms"]) /
            pytorch_baseline["latency_ms"] * 100
        )
        memory_reduction = (
            (pytorch_baseline["memory_mb"] - openvino_baseline["memory_mb"]) /
            pytorch_baseline["memory_mb"] * 100
        )
        
        comparison_conclusion = (
            f"OpenVINO provides {latency_improvement:.1f}% latency improvement "
            f"and {memory_reduction:.1f}% memory reduction vs PyTorch"
        )
        
        store.add_comparison(
            test_name="Overall: PyTorch vs OpenVINO",
            hypothesis="OpenVINO significantly outperforms PyTorch baseline",
            baseline=pytorch_baseline,
            variant=openvino_baseline,
            conclusion=comparison_conclusion,
            metadata={
                "improvement_percent": latency_improvement,
                "memory_reduction_percent": memory_reduction
            }
        )
        
        print(f"[SUCCESS] {comparison_conclusion}\n")
    
    # Print monitoring summary
    print("\n" + "="*70)
    print(" Test Execution Complete ".center(70, "="))
    print("="*70 + "\n")
    monitor.print_summary()
    
    return store


def generate_comprehensive_report(store: ResultStore):
    """Generate comprehensive HTML report"""
    print("\n" + "="*70)
    print(" Generating Comprehensive Report ".center(70, "="))
    print("="*70 + "\n")
    
    # Create report generator
    generator = ReportGenerator.from_result_store(store)
    
    # Add comprehensive metadata
    generator.set_metadata({
        "Framework": "CosyVoice Testing Framework v1.0",
        "Device": "NVIDIA RTX 4090",
        "Python Version": "3.10.11",
        "PyTorch Version": "2.1.0+cu121",
        "OpenVINO Version": "2024.0.0",
        "CUDA Version": "12.1",
        "Test Date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "Total Tests": len(store.results),
        "Session ID": store.session_id
    })
    
    # Generate report
    report_path = generator.generate(
        title="CosyVoice PyTorch vs OpenVINO - Comprehensive Benchmark Report",
        filename="comprehensive_benchmark_report.html",
        auto_open=False  # Set to True to auto-open in browser
    )
    
    print(f"\n[SUCCESS] Comprehensive report generated:")
    print(f"  {report_path}")
    print(f"\nTo view the report:")
    print(f"  1. Open the file in your browser")
    print(f"  2. Or run: python -m webbrowser {report_path}")


def main():
    """Run complete benchmark and generate report"""
    # Run comprehensive benchmark
    store = run_comprehensive_benchmark()
    
    # Generate report
    generate_comprehensive_report(store)
    
    # Print final summary
    print("\n" + "="*70)
    print(" Benchmark Complete ".center(70, "="))
    print("="*70)
    print(f"\nResults saved to: {store.output_dir}")
    print(f"Session ID: {store.session_id}")
    print(f"Total tests: {len(store.results)}")
    print("\nNext steps:")
    print("  1. Review the HTML report for detailed analysis")
    print("  2. Check JSON files for raw data")
    print("  3. Use results for optimization decisions")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
