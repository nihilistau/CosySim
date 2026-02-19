"""
Real-time Test Monitoring Dashboard
Uses rich library for live terminal UI with metrics and progress tracking
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from contextlib import contextmanager
import time

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Warning: rich library not installed. Install with: pip install rich")


class TestMonitor:
    """Real-time monitoring dashboard for test execution"""
    
    def __init__(self, title: str = "Test Monitoring Dashboard"):
        self.title = title
        self.console = Console() if RICH_AVAILABLE else None
        self.current_test: Optional[str] = None
        self.test_start_time: Optional[float] = None
        self.metrics: Dict[str, Any] = {}
        self.test_history: List[Dict[str, Any]] = []
        self.live_display: Optional[Live] = None
        self.stats = {
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "total_duration": 0.0,
        }
    
    def start_test(self, test_name: str, metadata: Optional[Dict[str, Any]] = None):
        """Start monitoring a test"""
        self.current_test = test_name
        self.test_start_time = time.time()
        self.metrics = metadata or {}
        self.stats["tests_run"] += 1
        
        if not RICH_AVAILABLE:
            print(f"[START] {test_name}")
            return
        
        self.console.print(f"\n[bold cyan]> Starting:[/bold cyan] {test_name}")
    
    def end_test(self, status: str = "passed", conclusion: Optional[str] = None):
        """End current test and record results"""
        if self.current_test is None:
            return
        
        duration = time.time() - self.test_start_time if self.test_start_time else 0
        self.stats["total_duration"] += duration
        
        if status == "passed":
            self.stats["tests_passed"] += 1
        elif status == "failed":
            self.stats["tests_failed"] += 1
        
        test_record = {
            "name": self.current_test,
            "status": status,
            "duration": duration,
            "conclusion": conclusion,
            "metrics": self.metrics.copy(),
            "timestamp": datetime.now().isoformat(),
        }
        self.test_history.append(test_record)
        
        if not RICH_AVAILABLE:
            print(f"[{status.upper()}] {self.current_test} ({duration:.2f}s)")
            if conclusion:
                print(f"  {conclusion}")
            return
        
        status_color = "green" if status == "passed" else "red"
        self.console.print(
            f"[bold {status_color}]{'[PASS]' if status == 'passed' else '[FAIL]'} Completed:[/bold {status_color}] "
            f"{self.current_test} [dim]({duration:.2f}s)[/dim]"
        )
        if conclusion:
            self.console.print(f"  [dim]->[/dim] {conclusion}")
        
        self.current_test = None
        self.test_start_time = None
    
    def update_metric(self, key: str, value: Any):
        """Update a metric for current test"""
        self.metrics[key] = value
    
    def create_dashboard(self) -> Layout:
        """Create the live dashboard layout"""
        if not RICH_AVAILABLE:
            return None
        
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3)
        )
        
        # Header
        header = Panel(
            Text(self.title, justify="center", style="bold magenta"),
            border_style="magenta"
        )
        layout["header"].update(header)
        
        # Main area - split into stats and current test
        layout["main"].split_row(
            Layout(name="stats", ratio=1),
            Layout(name="current", ratio=2)
        )
        
        # Stats table
        stats_table = Table(title="Statistics", show_header=False, border_style="blue")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="yellow")
        stats_table.add_row("Tests Run", str(self.stats["tests_run"]))
        stats_table.add_row("Passed", f"[green]{self.stats['tests_passed']}[/green]")
        stats_table.add_row("Failed", f"[red]{self.stats['tests_failed']}[/red]")
        stats_table.add_row("Duration", f"{self.stats['total_duration']:.1f}s")
        if self.stats["tests_run"] > 0:
            avg_time = self.stats["total_duration"] / self.stats["tests_run"]
            stats_table.add_row("Avg Time", f"{avg_time:.2f}s")
        
        layout["stats"].update(Panel(stats_table, border_style="blue"))
        
        # Current test info
        if self.current_test:
            current_duration = time.time() - self.test_start_time if self.test_start_time else 0
            
            current_table = Table(title="Current Test", border_style="green")
            current_table.add_column("Property", style="cyan")
            current_table.add_column("Value", style="white")
            current_table.add_row("Name", self.current_test)
            current_table.add_row("Duration", f"{current_duration:.1f}s")
            
            if self.metrics:
                for key, value in self.metrics.items():
                    current_table.add_row(key, str(value))
            
            layout["current"].update(Panel(current_table, border_style="green"))
        else:
            layout["current"].update(
                Panel(
                    Text("No test running", justify="center", style="dim"),
                    border_style="dim"
                )
            )
        
        # Footer - recent tests
        footer_text = "Recent: "
        for test in self.test_history[-3:]:
            status_symbol = "[PASS]" if test["status"] == "passed" else "[FAIL]"
            color = "green" if test["status"] == "passed" else "red"
            footer_text += f"[{color}]{status_symbol}[/{color}] {test['name']} "
        
        layout["footer"].update(
            Panel(Text(footer_text, justify="center"), border_style="dim")
        )
        
        return layout
    
    @contextmanager
    def live_display_context(self, refresh_per_second: int = 4):
        """Context manager for live display"""
        if not RICH_AVAILABLE:
            yield None
            return
        
        with Live(
            self.create_dashboard(),
            refresh_per_second=refresh_per_second,
            console=self.console
        ) as live:
            self.live_display = live
            try:
                yield live
            finally:
                self.live_display = None
    
    def update_display(self):
        """Update the live display"""
        if self.live_display and RICH_AVAILABLE:
            self.live_display.update(self.create_dashboard())
    
    def print_summary(self):
        """Print final summary of all tests"""
        if not RICH_AVAILABLE:
            print("\n" + "="*60)
            print(f"Test Summary: {self.title}")
            print("="*60)
            print(f"Total Tests: {self.stats['tests_run']}")
            print(f"Passed: {self.stats['tests_passed']}")
            print(f"Failed: {self.stats['tests_failed']}")
            print(f"Total Duration: {self.stats['total_duration']:.2f}s")
            
            if self.test_history:
                print("\nTest Results:")
                for test in self.test_history:
                    status = "PASS" if test["status"] == "passed" else "FAIL"
                    print(f"  [{status}] {test['name']} ({test['duration']:.2f}s)")
                    if test.get("conclusion"):
                        print(f"        {test['conclusion']}")
            print("="*60)
            return
        
        self.console.print("\n")
        summary_table = Table(
            title=f"[bold]{self.title} - Summary[/bold]",
            border_style="magenta",
            show_lines=True
        )
        summary_table.add_column("Test", style="cyan", no_wrap=False)
        summary_table.add_column("Status", justify="center", width=10)
        summary_table.add_column("Duration", justify="right", width=12)
        summary_table.add_column("Conclusion", style="dim")
        
        for test in self.test_history:
            status_text = "[green][PASS][/green]" if test["status"] == "passed" else "[red][FAIL][/red]"
            duration_text = f"{test['duration']:.2f}s"
            conclusion = test.get("conclusion", "")
            summary_table.add_row(
                test["name"],
                status_text,
                duration_text,
                conclusion
            )
        
        self.console.print(summary_table)
        
        # Overall stats
        pass_rate = (
            self.stats["tests_passed"] / self.stats["tests_run"] * 100
            if self.stats["tests_run"] > 0 else 0
        )
        
        stats_panel = Panel(
            f"[cyan]Total:[/cyan] {self.stats['tests_run']} | "
            f"[green]Passed:[/green] {self.stats['tests_passed']} | "
            f"[red]Failed:[/red] {self.stats['tests_failed']} | "
            f"[yellow]Pass Rate:[/yellow] {pass_rate:.1f}% | "
            f"[magenta]Duration:[/magenta] {self.stats['total_duration']:.2f}s",
            title="Statistics",
            border_style="blue"
        )
        self.console.print(stats_panel)


class ProgressTracker:
    """Context manager for tracking progress of operations"""
    
    def __init__(self, description: str, total: Optional[int] = None):
        self.description = description
        self.total = total
        self.progress: Optional[Progress] = None
        self.task_id: Optional[TaskID] = None
        self.completed = 0
    
    def __enter__(self):
        if not RICH_AVAILABLE:
            print(f"[PROGRESS] {self.description}")
            return self
        
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        )
        self.progress.start()
        self.task_id = self.progress.add_task(
            self.description,
            total=self.total if self.total else 100
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.progress:
            self.progress.stop()
        elif not RICH_AVAILABLE:
            print(f"[DONE] {self.description}")
    
    def update(self, advance: int = 1, description: Optional[str] = None):
        """Update progress"""
        self.completed += advance
        if self.progress and self.task_id is not None:
            kwargs = {"advance": advance}
            if description:
                kwargs["description"] = description
            self.progress.update(self.task_id, **kwargs)
        elif not RICH_AVAILABLE and description:
            print(f"  {description}")
    
    def set_total(self, total: int):
        """Set or update the total"""
        self.total = total
        if self.progress and self.task_id is not None:
            self.progress.update(self.task_id, total=total)
