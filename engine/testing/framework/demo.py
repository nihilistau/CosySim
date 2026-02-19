"""
Demo script showing usage of the testing framework
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
from framework import ResultStore, TestMonitor, ProgressTracker, ReportGenerator


def demo_basic_usage():
    """Demonstrate basic usage of the framework"""
    print("\n" + "="*60)
    print("Demo: Basic Testing Framework Usage")
    print("="*60 + "\n")
    
    # Initialize components
    store = ResultStore(output_dir="demo_results")
    monitor = TestMonitor(title="Demo Benchmark Suite")
    
    # Simulate running tests
    tests = [
        {
            "name": "PyTorch Inference Speed",
            "hypothesis": "PyTorch baseline provides consistent inference times",
            "duration": 1.5,
            "metrics": {"latency_ms": 245.3, "throughput": 4.08}
        },
        {
            "name": "OpenVINO Inference Speed",
            "hypothesis": "OpenVINO provides faster inference than PyTorch",
            "duration": 1.2,
            "metrics": {"latency_ms": 89.7, "throughput": 11.15}
        },
        {
            "name": "Memory Usage Comparison",
            "hypothesis": "OpenVINO uses less memory than PyTorch",
            "duration": 0.8,
            "metrics": {"memory_mb": 450, "peak_memory_mb": 520}
        }
    ]
    
    for test in tests:
        # Start test monitoring
        monitor.start_test(test["name"], metadata=test["metrics"])
        
        # Simulate test execution
        with ProgressTracker(f"Running {test['name']}", total=10) as progress:
            for i in range(10):
                time.sleep(test["duration"] / 10)
                progress.update(1, f"Step {i+1}/10")
        
        # End test
        conclusion = f"Test passed with metrics: {test['metrics']}"
        monitor.end_test(status="passed", conclusion=conclusion)
        
        # Store result
        store.add_result(
            test_name=test["name"],
            hypothesis=test["hypothesis"],
            result={
                "type": "single",
                "metrics": test["metrics"],
                "conclusion": conclusion,
                "duration": test["duration"]
            }
        )
    
    # Print summary
    monitor.print_summary()
    
    return store


def demo_comparison_test():
    """Demonstrate comparison testing"""
    print("\n" + "="*60)
    print("Demo: Comparison Testing")
    print("="*60 + "\n")
    
    store = ResultStore(output_dir="demo_results")
    monitor = TestMonitor(title="Performance Comparison")
    
    # Simulate comparison tests
    comparisons = [
        {
            "name": "Latency: PyTorch vs OpenVINO",
            "hypothesis": "OpenVINO reduces latency by >50%",
            "baseline": {"latency_ms": 245.3, "std_dev": 12.4},
            "variant": {"latency_ms": 89.7, "std_dev": 4.2},
            "conclusion": "PASSED: OpenVINO reduces latency by 63.4%"
        },
        {
            "name": "Throughput: PyTorch vs OpenVINO",
            "hypothesis": "OpenVINO increases throughput by >2x",
            "baseline": {"throughput": 4.08, "requests_per_sec": 4.08},
            "variant": {"throughput": 11.15, "requests_per_sec": 11.15},
            "conclusion": "PASSED: OpenVINO increases throughput by 2.73x"
        },
        {
            "name": "Memory: PyTorch vs OpenVINO",
            "hypothesis": "OpenVINO reduces memory usage",
            "baseline": {"memory_mb": 2048, "peak_mb": 2450},
            "variant": {"memory_mb": 450, "peak_mb": 520},
            "conclusion": "PASSED: OpenVINO reduces memory by 78%"
        }
    ]
    
    for comp in comparisons:
        monitor.start_test(comp["name"])
        
        # Simulate test
        time.sleep(0.5)
        
        monitor.end_test(status="passed", conclusion=comp["conclusion"])
        
        # Store comparison
        store.add_comparison(
            test_name=comp["name"],
            hypothesis=comp["hypothesis"],
            baseline=comp["baseline"],
            variant=comp["variant"],
            conclusion=comp["conclusion"],
            metadata={"test_type": "performance_comparison"}
        )
    
    monitor.print_summary()
    
    return store


def demo_report_generation(store: ResultStore):
    """Demonstrate report generation"""
    print("\n" + "="*60)
    print("Demo: HTML Report Generation")
    print("="*60 + "\n")
    
    # Create report generator
    generator = ReportGenerator.from_result_store(store)
    
    # Add metadata
    generator.set_metadata({
        "Framework": "CosyVoice Testing Suite",
        "Version": "1.0.0",
        "Device": "NVIDIA RTX 4090",
        "Python": "3.10.11"
    })
    
    # Generate report
    report_path = generator.generate(
        title="CosyVoice Benchmark Results",
        auto_open=False  # Set to True to auto-open in browser
    )
    
    print(f"\nReport generated at: {report_path}")


def demo_live_monitoring():
    """Demonstrate live monitoring dashboard"""
    print("\n" + "="*60)
    print("Demo: Live Monitoring Dashboard")
    print("="*60 + "\n")
    
    monitor = TestMonitor(title="Live Performance Monitoring")
    
    tests = [
        {"name": "Quick Test 1", "duration": 2.0},
        {"name": "Quick Test 2", "duration": 1.5},
        {"name": "Quick Test 3", "duration": 2.5},
    ]
    
    # Run with live display
    try:
        with monitor.live_display_context(refresh_per_second=4):
            for test in tests:
                monitor.start_test(test["name"], metadata={"status": "running"})
                monitor.update_display()
                
                # Simulate work
                steps = 10
                for i in range(steps):
                    time.sleep(test["duration"] / steps)
                    monitor.update_metric("progress", f"{((i+1)/steps)*100:.0f}%")
                    monitor.update_display()
                
                monitor.end_test(status="passed", conclusion="Test completed successfully")
                monitor.update_display()
                
                time.sleep(0.5)
    except Exception as e:
        print(f"Live display not available: {e}")
        print("Falling back to standard output...")
        
        # Fallback without live display
        for test in tests:
            monitor.start_test(test["name"])
            time.sleep(test["duration"])
            monitor.end_test(status="passed", conclusion="Test completed successfully")
    
    monitor.print_summary()


def main():
    """Run all demos"""
    print("\n" + "="*70)
    print(" CosyVoice Testing Framework - Demo Suite ".center(70, "="))
    print("="*70)
    
    # Demo 1: Basic usage
    store1 = demo_basic_usage()
    time.sleep(1)
    
    # Demo 2: Comparison testing
    store2 = demo_comparison_test()
    time.sleep(1)
    
    # Demo 3: Report generation
    demo_report_generation(store2)
    time.sleep(1)
    
    # Demo 4: Live monitoring (optional, may not work without rich)
    demo_live_monitoring()
    
    print("\n" + "="*70)
    print(" Demo Complete ".center(70, "="))
    print("="*70)
    print("\nCheck the 'demo_results' directory for generated files.")


if __name__ == "__main__":
    main()
