# CosyVoice Testing Framework

A comprehensive testing framework for benchmarking and performance analysis with real-time monitoring and HTML report generation.

## Components

### 1. ResultStore (`result_store.py`)
Manages benchmark results with structured storage and retrieval.

**Features:**
- Store test results with metadata
- Track comparisons between baseline and variants
- Session-based organization
- JSON export for persistence
- Query results by test name or session

**Usage:**
```python
from framework import ResultStore, TestHypothesis

# Initialize store
store = ResultStore(output_dir="test_results")

# Add single result
store.add_result(
    test_name="PyTorch Inference",
    hypothesis="PyTorch provides stable inference",
    result={"latency_ms": 245.3, "throughput": 4.08},
    metadata={"device": "cuda", "model": "CosyVoice"}
)

# Add comparison
store.add_comparison(
    test_name="PyTorch vs OpenVINO",
    hypothesis="OpenVINO is faster than PyTorch",
    baseline={"latency_ms": 245.3},
    variant={"latency_ms": 89.7},
    conclusion="PASSED: OpenVINO is 63% faster"
)

# Query results
session_results = store.get_session_results()
test_results = store.get_test_results("PyTorch Inference")
```

### 2. TestMonitor (`monitor.py`)
Real-time monitoring dashboard using the rich library.

**Features:**
- Live terminal dashboard with statistics
- Test progress tracking
- Metrics visualization
- Rich formatting (when available)
- Graceful fallback to simple output

**Usage:**
```python
from framework import TestMonitor, ProgressTracker

# Initialize monitor
monitor = TestMonitor(title="Benchmark Suite")

# Basic test monitoring
monitor.start_test("Inference Speed Test", metadata={"device": "cuda"})
# ... run test ...
monitor.end_test(status="passed", conclusion="Test completed successfully")

# With live dashboard
with monitor.live_display_context(refresh_per_second=4):
    monitor.start_test("Live Test")
    monitor.update_metric("progress", "50%")
    monitor.update_display()
    # ... continue test ...
    monitor.end_test(status="passed")
    monitor.update_display()

# Print summary
monitor.print_summary()

# Progress tracking
with ProgressTracker("Processing data", total=100) as progress:
    for i in range(100):
        # ... do work ...
        progress.update(1, f"Processing item {i+1}")
```

### 3. ReportGenerator (`report_generator.py`)
Generate interactive HTML reports with plotly charts.

**Features:**
- Interactive charts (performance comparison, sustained performance, metrics)
- Responsive HTML design with modern styling
- Auto-opens in browser
- Fallback to text reports when plotly unavailable
- Summary statistics cards
- Detailed tables for hypotheses and conclusions

**Usage:**
```python
from framework import ReportGenerator, ResultStore

# From ResultStore
store = ResultStore()
# ... add results ...

generator = ReportGenerator.from_result_store(store)
generator.set_metadata({
    "Device": "NVIDIA RTX 4090",
    "Python": "3.10.11",
    "Framework": "PyTorch 2.1.0"
})

report_path = generator.generate(
    title="CosyVoice Performance Benchmark",
    auto_open=True  # Opens in browser automatically
)

# Manual usage
generator = ReportGenerator(output_dir="reports")
generator.add_results([
    {
        "test_name": "Test 1",
        "hypothesis": "Hypothesis here",
        "result": {
            "type": "comparison",
            "baseline": {"latency_ms": 245.3},
            "variant": {"latency_ms": 89.7},
            "conclusion": "PASSED"
        }
    }
])
generator.generate(title="My Report")
```

## Installation

### Core Framework
The framework works with basic Python, but for full functionality install:

```bash
# Rich library for enhanced terminal UI
pip install rich

# Plotly for interactive HTML charts
pip install plotly
```

### Requirements
- Python 3.8+
- rich (optional, for live monitoring)
- plotly (optional, for HTML reports with charts)

## Complete Example

```python
from framework import ResultStore, TestMonitor, ReportGenerator
import time

# Initialize components
store = ResultStore(output_dir="benchmark_results")
monitor = TestMonitor(title="CosyVoice Benchmark")

# Run tests
tests = [
    {
        "name": "PyTorch Baseline",
        "hypothesis": "PyTorch provides consistent inference",
        "baseline": {"latency_ms": 245.3, "memory_mb": 2048}
    },
    {
        "name": "OpenVINO Optimized",
        "hypothesis": "OpenVINO reduces latency significantly",
        "variant": {"latency_ms": 89.7, "memory_mb": 450}
    }
]

for test in tests:
    monitor.start_test(test["name"])
    
    # Simulate test execution
    time.sleep(1.0)
    
    # Record results
    metrics = test.get("baseline") or test.get("variant")
    conclusion = f"Test passed: {metrics}"
    
    monitor.end_test("passed", conclusion)
    store.add_result(
        test_name=test["name"],
        hypothesis=test["hypothesis"],
        result={"metrics": metrics, "conclusion": conclusion}
    )

# Generate report
monitor.print_summary()
generator = ReportGenerator.from_result_store(store)
generator.set_metadata({
    "Device": "NVIDIA RTX 4090",
    "Framework": "CosyVoice v1.0"
})
generator.generate(title="Benchmark Report", auto_open=True)
```

## Demo

Run the demo to see all features:

```bash
python framework/demo.py
```

This demonstrates:
1. Basic test monitoring
2. Comparison testing
3. HTML report generation
4. Live monitoring dashboard

## Architecture

```
framework/
├── __init__.py           # Package exports
├── result_store.py       # Result storage and management
├── monitor.py            # Real-time monitoring
├── report_generator.py   # HTML report generation
├── demo.py               # Demo script
└── README.md             # This file
```

## Output Files

### JSON Results
Stored in `{output_dir}/results_{session_id}.json`:
```json
{
  "session_id": "20240101_120000",
  "created": "2024-01-01T12:00:00",
  "results": [
    {
      "result_id": "abc123",
      "test_name": "Test Name",
      "hypothesis": "Hypothesis here",
      "timestamp": "2024-01-01T12:00:00",
      "result": {...}
    }
  ]
}
```

### HTML Reports
Interactive reports with:
- Header with title and timestamp
- Summary statistics cards
- Performance comparison charts
- Sustained performance line charts
- Metrics comparison tables
- Test results table with hypotheses and conclusions
- Detailed metrics table

### Text Reports (Fallback)
Simple text-based reports when plotly is not available.

## Best Practices

1. **Session Management**: Create one ResultStore per benchmark session
2. **Hypotheses**: Write clear, testable hypotheses for each test
3. **Metadata**: Include relevant system info (device, framework versions)
4. **Live Monitoring**: Use live display for long-running tests
5. **Report Generation**: Generate reports after each benchmark session
6. **Error Handling**: Framework gracefully handles missing dependencies

## Error Handling

The framework includes robust error handling:
- Graceful degradation when rich/plotly are not available
- Fallback to simple text output
- Clear warning messages for missing dependencies
- Safe file I/O with proper encoding

## Version

Current version: **1.0.0**

## License

Part of the CosyVoice project.
