# Testing Framework - Quick Start Guide

## Installation

### Option 1: Basic Setup (No dependencies)
The framework works without any external dependencies, using simple text output.

```bash
# No installation needed - works out of the box!
python framework/demo.py
```

### Option 2: Full Setup (With enhanced features)
Install optional dependencies for enhanced UI and interactive reports:

```bash
# Install rich for beautiful terminal UI
pip install rich

# Install plotly for interactive HTML charts
pip install plotly

# Or install both at once
pip install rich plotly
```

## Quick Examples

### 1. Basic Test Monitoring

```python
from framework import TestMonitor

monitor = TestMonitor(title="My Benchmark")

# Run a test
monitor.start_test("PyTorch Inference")
# ... your test code ...
monitor.end_test(status="passed", conclusion="Inference successful")

# Print summary
monitor.print_summary()
```

### 2. Store Test Results

```python
from framework import ResultStore

store = ResultStore(output_dir="my_results")

# Add a test result
store.add_result(
    test_name="Latency Test",
    hypothesis="OpenVINO is faster than PyTorch",
    result={"latency_ms": 89.7, "throughput": 11.15}
)

# Add a comparison
store.add_comparison(
    test_name="PyTorch vs OpenVINO",
    hypothesis="OpenVINO provides >50% improvement",
    baseline={"latency_ms": 245.3},
    variant={"latency_ms": 89.7},
    conclusion="PASSED: 63% improvement"
)
```

### 3. Generate HTML Report

```python
from framework import ReportGenerator, ResultStore

# Create or load results
store = ResultStore()
# ... add results ...

# Generate report
generator = ReportGenerator.from_result_store(store)
generator.set_metadata({
    "Device": "NVIDIA RTX 4090",
    "Framework": "PyTorch 2.1.0"
})

report_path = generator.generate(
    title="Benchmark Results",
    auto_open=True  # Opens in browser
)
```

### 4. Progress Tracking

```python
from framework import ProgressTracker

with ProgressTracker("Processing data", total=100) as progress:
    for i in range(100):
        # Do work
        progress.update(1, f"Item {i+1}/100")
```

### 5. Complete Example

```python
from framework import ResultStore, TestMonitor, ReportGenerator

# Setup
store = ResultStore(output_dir="results")
monitor = TestMonitor(title="Performance Benchmark")

# Run tests
monitor.start_test("Inference Speed")
# ... run your test ...
results = {"latency_ms": 89.7, "memory_mb": 450}
monitor.end_test("passed", "Test completed successfully")

# Store results
store.add_result(
    test_name="Inference Speed",
    hypothesis="System meets performance targets",
    result=results
)

# Generate report
monitor.print_summary()
generator = ReportGenerator.from_result_store(store)
generator.generate(title="Results", auto_open=True)
```

## Running Demos

### Demo 1: Basic Framework Demo
Shows all basic features with simple examples.

```bash
python framework/demo.py
```

### Demo 2: Comprehensive Integration
Shows complete benchmark workflow with realistic scenarios.

```bash
python framework/example_integration.py
```

## Output Files

### JSON Results
Located in `{output_dir}/results_{session_id}.json`

Contains all test results, hypotheses, and metadata in structured format.

### HTML Reports
Located in `{output_dir}/report_{timestamp}.html`

Interactive reports with:
- Summary statistics
- Performance comparison charts
- Sustained performance graphs
- Detailed tables
- Hypothesis validation

### Text Reports (Fallback)
Generated when plotly is not available.

Simple text format with all test results and conclusions.

## Best Practices

1. **Session Management**
   - One ResultStore per benchmark session
   - Use descriptive output directory names

2. **Test Naming**
   - Use clear, descriptive test names
   - Group related tests with common prefixes

3. **Hypotheses**
   - Write specific, measurable hypotheses
   - Include expected outcomes
   - Validate against actual results

4. **Metadata**
   - Include system info (device, versions)
   - Add test configuration details
   - Document test parameters

5. **Reporting**
   - Generate reports after each session
   - Include relevant metadata
   - Review both charts and tables

## Troubleshooting

### "Warning: rich library not installed"
Optional warning. Framework works without rich, using simple text output.
To enable enhanced UI: `pip install rich`

### "Warning: plotly not installed"
Optional warning. Reports will be generated as text instead of HTML.
To enable interactive charts: `pip install plotly`

### Unicode/Encoding Errors
The framework now uses ASCII-safe characters to avoid encoding issues.
If you still see issues, ensure your terminal supports UTF-8.

### Import Errors
Make sure you're running from the project root directory:
```bash
cd C:\Files\Models\CosyVoice
python framework/demo.py
```

## API Reference

### TestMonitor
- `start_test(name, metadata)` - Start monitoring a test
- `end_test(status, conclusion)` - End test and record results
- `update_metric(key, value)` - Update test metric
- `print_summary()` - Print final summary
- `live_display_context()` - Context manager for live updates

### ResultStore
- `add_result(test_name, hypothesis, result, metadata)` - Add test result
- `add_comparison(test_name, hypothesis, baseline, variant, conclusion)` - Add comparison
- `get_session_results()` - Get all results from current session
- `get_test_results(test_name)` - Get results for specific test
- `export_summary()` - Export summary statistics

### ReportGenerator
- `add_results(results)` - Add results to report
- `set_metadata(metadata)` - Set report metadata
- `generate(title, filename, auto_open)` - Generate HTML report
- `from_result_store(store)` - Create from ResultStore

### ProgressTracker
- `update(advance, description)` - Update progress
- `set_total(total)` - Set/update total

## Support

For issues or questions:
1. Check the README.md in the framework directory
2. Review the example scripts
3. Check output directory for generated files

## Version

Current version: **1.0.0**

Framework files:
- `__init__.py` - Package initialization (319 bytes)
- `result_store.py` - Result storage (4,742 bytes)
- `monitor.py` - Real-time monitoring (11,553 bytes)
- `report_generator.py` - HTML reports (22,108 bytes)
- `demo.py` - Demo script (7,541 bytes)
- `example_integration.py` - Integration example (9,741 bytes)
- `README.md` - Documentation (7,611 bytes)
- `QUICK_START.md` - This file

Total framework size: ~64 KB
