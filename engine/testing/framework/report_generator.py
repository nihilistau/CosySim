"""
HTML Report Generator
Generates interactive HTML reports with plotly charts for benchmark results
"""
from typing import Dict, Any, List, Optional
from pathlib import Path
import json
from datetime import datetime
import webbrowser

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("Warning: plotly not installed. Install with: pip install plotly")


class ReportGenerator:
    """Generate HTML reports with interactive charts"""
    
    def __init__(self, output_dir: str = "test_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.results: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}
    
    def add_results(self, results: List[Dict[str, Any]]):
        """Add results to report"""
        self.results.extend(results)
    
    def set_metadata(self, metadata: Dict[str, Any]):
        """Set report metadata"""
        self.metadata = metadata
    
    def generate(
        self,
        title: str = "Benchmark Report",
        filename: Optional[str] = None,
        auto_open: bool = True
    ) -> Path:
        """Generate complete HTML report"""
        if not PLOTLY_AVAILABLE:
            return self._generate_simple_report(title, filename)
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.html"
        
        filepath = self.output_dir / filename
        
        # Create HTML structure
        html_content = self._build_html(title)
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"Report generated: {filepath}")
        
        if auto_open:
            try:
                webbrowser.open(filepath.as_uri())
            except Exception as e:
                print(f"Could not auto-open browser: {e}")
        
        return filepath
    
    def _build_html(self, title: str) -> str:
        """Build complete HTML structure"""
        # Generate charts
        charts_html = self._generate_charts()
        
        # Generate tables
        tables_html = self._generate_tables()
        
        # Build HTML
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
            font-weight: 700;
        }}
        .header .subtitle {{
            margin-top: 10px;
            opacity: 0.9;
            font-size: 1.1em;
        }}
        .content {{
            padding: 40px;
        }}
        .section {{
            margin-bottom: 50px;
        }}
        .section h2 {{
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            margin-bottom: 25px;
            font-size: 1.8em;
        }}
        .chart-container {{
            margin: 30px 0;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            background: #fafafa;
        }}
        .chart-title {{
            font-size: 1.3em;
            font-weight: 600;
            color: #444;
            margin-bottom: 15px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-radius: 8px;
            overflow: hidden;
        }}
        thead {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        th, td {{
            padding: 15px;
            text-align: left;
        }}
        th {{
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85em;
            letter-spacing: 0.5px;
        }}
        tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        tr:hover {{
            background: #e3f2fd;
        }}
        .status-pass {{
            color: #28a745;
            font-weight: 600;
        }}
        .status-fail {{
            color: #dc3545;
            font-weight: 600;
        }}
        .metadata {{
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            padding: 20px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .metadata-item {{
            margin: 8px 0;
            color: #555;
        }}
        .metadata-label {{
            font-weight: 600;
            color: #333;
        }}
        .footer {{
            text-align: center;
            padding: 30px;
            background: #f8f9fa;
            color: #666;
            font-size: 0.9em;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        .stat-value {{
            font-size: 2.5em;
            font-weight: 700;
            margin: 10px 0;
        }}
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <div class="subtitle">Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        </div>
        
        <div class="content">
            {self._generate_metadata_section()}
            {self._generate_stats_section()}
            {charts_html}
            {tables_html}
        </div>
        
        <div class="footer">
            <p>Generated by CosyVoice Testing Framework v1.0</p>
            <p>Report created at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>
    </div>
</body>
</html>"""
        return html
    
    def _generate_metadata_section(self) -> str:
        """Generate metadata section HTML"""
        if not self.metadata:
            return ""
        
        items = []
        for key, value in self.metadata.items():
            items.append(
                f'<div class="metadata-item">'
                f'<span class="metadata-label">{key}:</span> {value}'
                f'</div>'
            )
        
        return f"""
        <div class="section">
            <h2>Test Configuration</h2>
            <div class="metadata">
                {''.join(items)}
            </div>
        </div>
        """
    
    def _generate_stats_section(self) -> str:
        """Generate statistics cards"""
        total_tests = len(self.results)
        passed = sum(1 for r in self.results if r.get("result", {}).get("conclusion", "").lower().find("pass") >= 0)
        failed = total_tests - passed
        
        total_duration = sum(
            r.get("result", {}).get("duration", 0) for r in self.results
        )
        
        return f"""
        <div class="section">
            <h2>Summary Statistics</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Total Tests</div>
                    <div class="stat-value">{total_tests}</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%);">
                    <div class="stat-label">Passed</div>
                    <div class="stat-value">{passed}</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #dc3545 0%, #fd7e14 100%);">
                    <div class="stat-label">Failed</div>
                    <div class="stat-value">{failed}</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #6c757d 0%, #495057 100%);">
                    <div class="stat-label">Total Duration</div>
                    <div class="stat-value">{total_duration:.1f}s</div>
                </div>
            </div>
        </div>
        """
    
    def _generate_charts(self) -> str:
        """Generate all charts"""
        if not self.results or not PLOTLY_AVAILABLE:
            return ""
        
        charts = []
        
        # Performance comparison bar chart
        perf_chart = self._create_performance_comparison()
        if perf_chart:
            charts.append(self._wrap_chart(perf_chart, "Performance Comparison"))
        
        # Sustained performance line chart
        sustained_chart = self._create_sustained_performance()
        if sustained_chart:
            charts.append(self._wrap_chart(sustained_chart, "Sustained Performance Over Time"))
        
        # Metrics comparison
        metrics_chart = self._create_metrics_comparison()
        if metrics_chart:
            charts.append(self._wrap_chart(metrics_chart, "Key Metrics Comparison"))
        
        if not charts:
            return ""
        
        return f"""
        <div class="section">
            <h2>Performance Visualizations</h2>
            {''.join(charts)}
        </div>
        """
    
    def _create_performance_comparison(self) -> Optional[str]:
        """Create performance comparison bar chart"""
        # Extract performance metrics from results
        test_names = []
        baseline_values = []
        variant_values = []
        
        for result in self.results:
            res_data = result.get("result", {})
            if res_data.get("type") == "comparison":
                test_names.append(result.get("test_name", "Unknown"))
                baseline = res_data.get("baseline", {})
                variant = res_data.get("variant", {})
                
                # Try to extract numeric performance metric
                baseline_val = baseline.get("latency_ms") or baseline.get("duration") or baseline.get("time") or 0
                variant_val = variant.get("latency_ms") or variant.get("duration") or variant.get("time") or 0
                
                baseline_values.append(baseline_val)
                variant_values.append(variant_val)
        
        if not test_names:
            return None
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name='Baseline',
            x=test_names,
            y=baseline_values,
            marker_color='#667eea'
        ))
        fig.add_trace(go.Bar(
            name='Optimized',
            x=test_names,
            y=variant_values,
            marker_color='#28a745'
        ))
        
        fig.update_layout(
            barmode='group',
            xaxis_title='Test',
            yaxis_title='Time (ms)',
            template='plotly_white',
            height=500,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        return fig.to_html(include_plotlyjs=False, div_id="perf_comparison")
    
    def _create_sustained_performance(self) -> Optional[str]:
        """Create sustained performance line chart"""
        # Group results by test name and plot over time
        test_groups = {}
        
        for result in self.results:
            test_name = result.get("test_name", "Unknown")
            if test_name not in test_groups:
                test_groups[test_name] = []
            
            res_data = result.get("result", {})
            duration = res_data.get("duration") or res_data.get("latency_ms") or 0
            test_groups[test_name].append({
                "timestamp": result.get("timestamp", ""),
                "duration": duration
            })
        
        if not test_groups:
            return None
        
        fig = go.Figure()
        
        for test_name, data_points in test_groups.items():
            iterations = list(range(1, len(data_points) + 1))
            durations = [d["duration"] for d in data_points]
            
            fig.add_trace(go.Scatter(
                x=iterations,
                y=durations,
                mode='lines+markers',
                name=test_name,
                line=dict(width=2),
                marker=dict(size=8)
            ))
        
        fig.update_layout(
            xaxis_title='Iteration',
            yaxis_title='Duration (ms)',
            template='plotly_white',
            height=500,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        return fig.to_html(include_plotlyjs=False, div_id="sustained_perf")
    
    def _create_metrics_comparison(self) -> Optional[str]:
        """Create metrics comparison chart"""
        # Extract various metrics
        metrics_data = {}
        
        for result in self.results:
            test_name = result.get("test_name", "Unknown")
            res_data = result.get("result", {})
            
            if res_data.get("type") == "comparison":
                baseline = res_data.get("baseline", {})
                variant = res_data.get("variant", {})
                
                # Collect all numeric metrics
                for key in baseline.keys():
                    if isinstance(baseline.get(key), (int, float)):
                        if key not in metrics_data:
                            metrics_data[key] = {"tests": [], "baseline": [], "variant": []}
                        
                        metrics_data[key]["tests"].append(test_name)
                        metrics_data[key]["baseline"].append(baseline.get(key, 0))
                        metrics_data[key]["variant"].append(variant.get(key, 0))
        
        if not metrics_data:
            return None
        
        # Create subplots for each metric
        num_metrics = len(metrics_data)
        if num_metrics == 0:
            return None
        
        rows = (num_metrics + 1) // 2
        cols = 2 if num_metrics > 1 else 1
        
        fig = make_subplots(
            rows=rows,
            cols=cols,
            subplot_titles=list(metrics_data.keys())
        )
        
        row, col = 1, 1
        for metric_name, data in metrics_data.items():
            fig.add_trace(
                go.Bar(name='Baseline', x=data["tests"], y=data["baseline"], marker_color='#667eea'),
                row=row, col=col
            )
            fig.add_trace(
                go.Bar(name='Optimized', x=data["tests"], y=data["variant"], marker_color='#28a745'),
                row=row, col=col
            )
            
            col += 1
            if col > cols:
                col = 1
                row += 1
        
        fig.update_layout(
            height=300 * rows,
            template='plotly_white',
            showlegend=True
        )
        
        return fig.to_html(include_plotlyjs=False, div_id="metrics_comparison")
    
    def _wrap_chart(self, chart_html: str, title: str) -> str:
        """Wrap chart HTML in container"""
        return f"""
        <div class="chart-container">
            <div class="chart-title">{title}</div>
            {chart_html}
        </div>
        """
    
    def _generate_tables(self) -> str:
        """Generate result tables"""
        if not self.results:
            return ""
        
        # Hypothesis and conclusions table
        hypothesis_rows = []
        for result in self.results:
            test_name = result.get("test_name", "Unknown")
            hypothesis = result.get("hypothesis", "N/A")
            res_data = result.get("result", {})
            conclusion = res_data.get("conclusion", "N/A")
            
            # Determine status
            status_class = "status-pass" if "pass" in conclusion.lower() else "status-fail"
            status_text = "[PASS]" if "pass" in conclusion.lower() else "[FAIL]"
            
            hypothesis_rows.append(f"""
                <tr>
                    <td>{test_name}</td>
                    <td>{hypothesis}</td>
                    <td>{conclusion}</td>
                    <td class="{status_class}">{status_text}</td>
                </tr>
            """)
        
        hypothesis_table = f"""
        <div class="section">
            <h2>Test Results</h2>
            <table>
                <thead>
                    <tr>
                        <th>Test Name</th>
                        <th>Hypothesis</th>
                        <th>Conclusion</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(hypothesis_rows)}
                </tbody>
            </table>
        </div>
        """
        
        # Detailed metrics table
        metrics_rows = []
        for result in self.results:
            test_name = result.get("test_name", "Unknown")
            res_data = result.get("result", {})
            
            if res_data.get("type") == "comparison":
                baseline = res_data.get("baseline", {})
                variant = res_data.get("variant", {})
                
                baseline_str = ", ".join(f"{k}: {v}" for k, v in baseline.items() if isinstance(v, (int, float)))
                variant_str = ", ".join(f"{k}: {v}" for k, v in variant.items() if isinstance(v, (int, float)))
                
                # Calculate improvement
                if baseline.get("latency_ms") and variant.get("latency_ms"):
                    improvement = ((baseline["latency_ms"] - variant["latency_ms"]) / baseline["latency_ms"]) * 100
                    improvement_str = f"{improvement:+.1f}%"
                else:
                    improvement_str = "N/A"
                
                metrics_rows.append(f"""
                    <tr>
                        <td>{test_name}</td>
                        <td>{baseline_str}</td>
                        <td>{variant_str}</td>
                        <td>{improvement_str}</td>
                    </tr>
                """)
        
        if metrics_rows:
            metrics_table = f"""
            <div class="section">
                <h2>Detailed Metrics</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Test Name</th>
                            <th>Baseline Metrics</th>
                            <th>Optimized Metrics</th>
                            <th>Improvement</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(metrics_rows)}
                    </tbody>
                </table>
            </div>
            """
        else:
            metrics_table = ""
        
        return hypothesis_table + metrics_table
    
    def _generate_simple_report(self, title: str, filename: Optional[str] = None) -> Path:
        """Generate simple text report when plotly not available"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.txt"
        
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"{title}\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            if self.metadata:
                f.write("Metadata:\n")
                for key, value in self.metadata.items():
                    f.write(f"  {key}: {value}\n")
                f.write("\n")
            
            f.write("Results:\n")
            f.write("-" * 80 + "\n")
            for result in self.results:
                f.write(f"\nTest: {result.get('test_name', 'Unknown')}\n")
                f.write(f"Hypothesis: {result.get('hypothesis', 'N/A')}\n")
                res_data = result.get('result', {})
                f.write(f"Conclusion: {res_data.get('conclusion', 'N/A')}\n")
                if res_data.get('type') == 'comparison':
                    f.write(f"Baseline: {res_data.get('baseline', {})}\n")
                    f.write(f"Variant: {res_data.get('variant', {})}\n")
                f.write("-" * 80 + "\n")
        
        print(f"Simple report generated: {filepath}")
        return filepath
    
    @classmethod
    def from_result_store(cls, result_store, output_dir: Optional[str] = None):
        """Create report generator from ResultStore"""
        generator = cls(output_dir or result_store.output_dir)
        generator.add_results(result_store.get_session_results())
        generator.set_metadata({
            "session_id": result_store.session_id,
            "total_tests": len(result_store.results)
        })
        return generator
