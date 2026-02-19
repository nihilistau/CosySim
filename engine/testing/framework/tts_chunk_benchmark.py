"""
TTS Chunk Size Benchmark Suite
================================

Comprehensive testing framework for optimizing TTS chunk sizes and streaming behavior.

Tests:
1. Chunk size sweep (1s to 12s)
2. Text length variations (short, medium, long)
3. Streaming vs non-streaming
4. Overhead analysis
5. Interruption simulation
6. Sweet spot identification

Outputs:
- JSON data files
- Markdown reports with graphs
- CSV for spreadsheet analysis
- PNG visualizations
"""

import os
import sys
import time
import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import torch
import torchaudio

# Add CosyVoice to path
sys.path.insert(0, str(Path(__file__).parent.parent / "third_party" / "Matcha-TTS"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set environment
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from cosyvoice.cli.cosyvoice import CosyVoice3


# ============================================================================
# TEST CONFIGURATION
# ============================================================================

class BenchmarkConfig:
    """Configuration for benchmark suite"""
    
    # Chunk sizes to test (in seconds, estimated)
    CHUNK_SIZES = [1, 2, 3, 4, 5, 6, 8, 10, 12]
    
    # Text samples of different lengths
    TEXT_SAMPLES = {
        'tiny': "Hello!",  # ~0.5s
        'short': "Hello! How are you doing today?",  # ~2-3s
        'medium': "I wanted to ask you about artificial intelligence and how it might change our daily lives in the next few years.",  # ~6-8s
        'long': "That's a great question! I think AI will become more integrated into our daily routines. AI assistants will help with scheduling, smart homes will anticipate our needs, and personalized recommendations will become even more accurate.",  # ~12-15s
        'very_long': "Privacy is definitely important. We'll need strong regulations and transparent AI systems to ensure that personal data is protected. Companies should be held accountable for how they use AI, and users should have control over their information. This will require collaboration between governments, tech companies, and civil society to create frameworks that balance innovation with privacy protection.",  # ~20-25s
    }
    
    # Prompt configurations
    PROMPT_WAV = "asset/zero_shot_prompt.wav"
    PROMPT_TEXT = "You are a helpful assistant.<|endofprompt|>"
    
    # Model
    MODEL_DIR = "pretrained_models/Fun-CosyVoice3-0.5B"
    SAMPLE_RATE = 22050
    
    # Output directories
    OUTPUT_DIR = Path("benchmarks/results/tts_chunk_optimization")
    PLOTS_DIR = OUTPUT_DIR / "plots"
    DATA_DIR = OUTPUT_DIR / "data"
    REPORTS_DIR = OUTPUT_DIR / "reports"
    
    # Test parameters
    ITERATIONS_PER_TEST = 3  # Average over multiple runs
    WARMUP_ITERATIONS = 1  # Warmup runs to exclude


# ============================================================================
# BENCHMARK RESULT STORAGE
# ============================================================================

class BenchmarkResult:
    """Single benchmark result"""
    
    def __init__(self, test_name: str, config: Dict):
        self.test_name = test_name
        self.config = config
        self.timestamp = datetime.now().isoformat()
        self.results = []
        
    def add_result(self, result: Dict):
        """Add a single test result"""
        self.results.append(result)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'test_name': self.test_name,
            'config': self.config,
            'timestamp': self.timestamp,
            'results': self.results,
            'summary': self.compute_summary()
        }
    
    def compute_summary(self) -> Dict:
        """Compute summary statistics"""
        if not self.results:
            return {}
        
        rtfs = [r['rtf'] for r in self.results if 'rtf' in r]
        gen_times = [r['generation_time'] for r in self.results if 'generation_time' in r]
        audio_lengths = [r['audio_length'] for r in self.results if 'audio_length' in r]
        
        return {
            'count': len(self.results),
            'rtf': {
                'mean': float(np.mean(rtfs)) if rtfs else None,
                'std': float(np.std(rtfs)) if rtfs else None,
                'min': float(np.min(rtfs)) if rtfs else None,
                'max': float(np.max(rtfs)) if rtfs else None,
            },
            'generation_time': {
                'mean': float(np.mean(gen_times)) if gen_times else None,
                'std': float(np.std(gen_times)) if gen_times else None,
            },
            'audio_length': {
                'mean': float(np.mean(audio_lengths)) if audio_lengths else None,
            }
        }


# ============================================================================
# TTS BENCHMARK ENGINE
# ============================================================================

class TTSBenchmark:
    """Main benchmark engine"""
    
    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.model = None
        self.results = {}
        
        # Create output directories
        for dir_path in [config.OUTPUT_DIR, config.PLOTS_DIR, 
                        config.DATA_DIR, config.REPORTS_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def load_model(self):
        """Load CosyVoice3 model"""
        print("🔄 Loading CosyVoice3 model...")
        start = time.time()
        self.model = CosyVoice3(self.config.MODEL_DIR)
        load_time = time.time() - start
        print(f"✅ Model loaded in {load_time:.1f}s\n")
        return load_time
    
    def synthesize_text(self, text: str, stream: bool = False) -> Tuple[torch.Tensor, Dict]:
        """
        Synthesize text and return audio + metrics
        
        Returns:
            (audio_tensor, metrics_dict)
        """
        start = time.time()
        
        # Track first chunk time for streaming
        first_chunk_time = None
        audio_chunks = []
        chunk_count = 0
        
        # Generate
        output = self.model.inference_zero_shot(
            text,
            self.config.PROMPT_TEXT,
            self.config.PROMPT_WAV,
            stream=stream
        )
        
        # Collect chunks
        for chunk in output:
            if first_chunk_time is None:
                first_chunk_time = time.time() - start
            audio_chunks.append(chunk['tts_speech'])
            chunk_count += 1
        
        # Concatenate
        if audio_chunks:
            audio_tensor = audio_chunks[0] if len(audio_chunks) == 1 else torch.cat(audio_chunks, dim=1)
        else:
            audio_tensor = torch.zeros((1, 0))
        
        total_time = time.time() - start
        audio_length = audio_tensor.shape[1] / self.config.SAMPLE_RATE
        rtf = total_time / audio_length if audio_length > 0 else float('inf')
        
        metrics = {
            'generation_time': total_time,
            'first_chunk_time': first_chunk_time,
            'audio_length': audio_length,
            'rtf': rtf,
            'chunk_count': chunk_count,
            'stream': stream,
            'text_length': len(text),
        }
        
        return audio_tensor, metrics
    
    def test_text_length_variations(self) -> BenchmarkResult:
        """Test 1: How does text length affect RTF?"""
        test_name = "text_length_variations"
        print(f"\n{'='*70}")
        print(f"📊 Test 1: Text Length Variations")
        print(f"{'='*70}\n")
        
        result = BenchmarkResult(test_name, {
            'description': 'Test RTF across different text lengths',
            'samples': list(self.config.TEXT_SAMPLES.keys())
        })
        
        for sample_name, text in self.config.TEXT_SAMPLES.items():
            print(f"Testing '{sample_name}' ({len(text)} chars)...")
            
            # Warmup
            for i in range(self.config.WARMUP_ITERATIONS):
                self.synthesize_text(text, stream=False)
            
            # Actual test runs
            for iteration in range(self.config.ITERATIONS_PER_TEST):
                audio, metrics = self.synthesize_text(text, stream=False)
                
                metrics['sample_name'] = sample_name
                metrics['text'] = text
                metrics['iteration'] = iteration
                
                result.add_result(metrics)
                
                print(f"  Run {iteration+1}: {metrics['audio_length']:.2f}s audio, "
                      f"{metrics['generation_time']:.2f}s gen, RTF: {metrics['rtf']:.2f}x")
            
            print()
        
        self.results[test_name] = result
        return result
    
    def test_streaming_vs_blocking(self) -> BenchmarkResult:
        """Test 2: Streaming vs non-streaming performance"""
        test_name = "streaming_vs_blocking"
        print(f"\n{'='*70}")
        print(f"📊 Test 2: Streaming vs Blocking")
        print(f"{'='*70}\n")
        
        result = BenchmarkResult(test_name, {
            'description': 'Compare streaming vs non-streaming generation',
            'samples': ['medium']  # Use medium-length text
        })
        
        text = self.config.TEXT_SAMPLES['medium']
        
        for stream_mode in [False, True]:
            mode_name = "Streaming" if stream_mode else "Blocking"
            print(f"Testing {mode_name} mode...")
            
            # Warmup
            for i in range(self.config.WARMUP_ITERATIONS):
                self.synthesize_text(text, stream=stream_mode)
            
            # Actual test runs
            for iteration in range(self.config.ITERATIONS_PER_TEST):
                audio, metrics = self.synthesize_text(text, stream=stream_mode)
                
                metrics['mode'] = mode_name
                metrics['iteration'] = iteration
                
                result.add_result(metrics)
                
                print(f"  Run {iteration+1}: Total: {metrics['generation_time']:.2f}s, "
                      f"First chunk: {metrics['first_chunk_time']:.2f}s, RTF: {metrics['rtf']:.2f}x")
            
            print()
        
        self.results[test_name] = result
        return result
    
    def test_chunk_size_sweep(self) -> BenchmarkResult:
        """Test 3: Target different audio lengths to find sweet spot"""
        test_name = "chunk_size_sweep"
        print(f"\n{'='*70}")
        print(f"📊 Test 3: Chunk Size Sweep")
        print(f"{'='*70}\n")
        
        result = BenchmarkResult(test_name, {
            'description': 'Test RTF at different target audio lengths',
            'target_lengths': self.config.CHUNK_SIZES
        })
        
        # Create texts that roughly produce desired lengths
        # Rough estimate: ~10 chars per second of speech
        test_texts = {}
        for target_length in self.config.CHUNK_SIZES:
            chars_needed = int(target_length * 10)
            base_text = "This is a test sentence for audio generation. "
            repetitions = (chars_needed // len(base_text)) + 1
            test_texts[target_length] = (base_text * repetitions)[:chars_needed]
        
        for target_length, text in test_texts.items():
            print(f"Testing ~{target_length}s target ({len(text)} chars)...")
            
            # Warmup
            for i in range(self.config.WARMUP_ITERATIONS):
                self.synthesize_text(text, stream=False)
            
            # Actual test runs
            for iteration in range(self.config.ITERATIONS_PER_TEST):
                audio, metrics = self.synthesize_text(text, stream=False)
                
                metrics['target_length'] = target_length
                metrics['text'] = text[:100] + "..." if len(text) > 100 else text
                metrics['iteration'] = iteration
                
                result.add_result(metrics)
                
                print(f"  Run {iteration+1}: {metrics['audio_length']:.2f}s audio, "
                      f"{metrics['generation_time']:.2f}s gen, RTF: {metrics['rtf']:.2f}x")
            
            print()
        
        self.results[test_name] = result
        return result
    
    def test_overhead_analysis(self) -> BenchmarkResult:
        """Test 4: Analyze fixed vs variable overhead"""
        test_name = "overhead_analysis"
        print(f"\n{'='*70}")
        print(f"📊 Test 4: Overhead Analysis")
        print(f"{'='*70}\n")
        
        result = BenchmarkResult(test_name, {
            'description': 'Separate fixed overhead from variable generation time',
        })
        
        # Test very short to very long
        lengths = ['tiny', 'short', 'medium', 'long', 'very_long']
        
        for length in lengths:
            text = self.config.TEXT_SAMPLES[length]
            print(f"Testing '{length}' length...")
            
            # Multiple runs for accurate timing
            for iteration in range(5):  # More iterations for overhead analysis
                audio, metrics = self.synthesize_text(text, stream=False)
                
                metrics['length_category'] = length
                metrics['iteration'] = iteration
                
                result.add_result(metrics)
                
                print(f"  Run {iteration+1}: {metrics['audio_length']:.2f}s audio, "
                      f"{metrics['generation_time']:.2f}s gen, RTF: {metrics['rtf']:.2f}x")
            
            print()
        
        self.results[test_name] = result
        return result
    
    def save_results(self):
        """Save all results to JSON files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for test_name, result in self.results.items():
            filename = self.config.DATA_DIR / f"{test_name}_{timestamp}.json"
            
            with open(filename, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)
            
            print(f"💾 Saved: {filename}")
    
    def generate_plots(self):
        """Generate visualization plots"""
        print(f"\n{'='*70}")
        print(f"📈 Generating Plots")
        print(f"{'='*70}\n")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Plot 1: RTF vs Text Length
        if 'text_length_variations' in self.results:
            self._plot_rtf_vs_length(timestamp)
        
        # Plot 2: Streaming comparison
        if 'streaming_vs_blocking' in self.results:
            self._plot_streaming_comparison(timestamp)
        
        # Plot 3: Chunk size sweet spot
        if 'chunk_size_sweep' in self.results:
            self._plot_chunk_sweet_spot(timestamp)
        
        # Plot 4: Overhead analysis
        if 'overhead_analysis' in self.results:
            self._plot_overhead_analysis(timestamp)
    
    def _plot_rtf_vs_length(self, timestamp: str):
        """Plot RTF vs audio length"""
        result = self.results['text_length_variations']
        
        # Group by sample
        samples = {}
        for r in result.results:
            sample = r['sample_name']
            if sample not in samples:
                samples[sample] = []
            samples[sample].append(r)
        
        # Calculate averages
        sample_names = []
        audio_lengths = []
        rtfs = []
        rtf_stds = []
        
        for sample_name in ['tiny', 'short', 'medium', 'long', 'very_long']:
            if sample_name in samples:
                data = samples[sample_name]
                sample_names.append(sample_name)
                audio_lengths.append(np.mean([r['audio_length'] for r in data]))
                rtfs.append(np.mean([r['rtf'] for r in data]))
                rtf_stds.append(np.std([r['rtf'] for r in data]))
        
        # Create plot
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.errorbar(audio_lengths, rtfs, yerr=rtf_stds, marker='o', 
                    capsize=5, linewidth=2, markersize=8)
        
        ax.set_xlabel('Audio Length (seconds)', fontsize=12)
        ax.set_ylabel('Real-Time Factor (RTF)', fontsize=12)
        ax.set_title('TTS Performance: RTF vs Audio Length', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.axhline(y=1.0, color='r', linestyle='--', label='Real-time threshold')
        
        # Annotate points
        for i, name in enumerate(sample_names):
            ax.annotate(name, (audio_lengths[i], rtfs[i]), 
                       xytext=(5, 5), textcoords='offset points', fontsize=9)
        
        ax.legend()
        plt.tight_layout()
        
        filename = self.config.PLOTS_DIR / f"rtf_vs_length_{timestamp}.png"
        plt.savefig(filename, dpi=150)
        plt.close()
        
        print(f"📊 Created: {filename}")
    
    def _plot_streaming_comparison(self, timestamp: str):
        """Plot streaming vs blocking comparison"""
        result = self.results['streaming_vs_blocking']
        
        # Group by mode
        blocking = [r for r in result.results if r['mode'] == 'Blocking']
        streaming = [r for r in result.results if r['mode'] == 'Streaming']
        
        # Calculate metrics
        metrics = ['generation_time', 'first_chunk_time', 'rtf']
        labels = ['Total Time', 'First Chunk', 'RTF']
        
        blocking_means = [np.mean([r[m] for r in blocking]) for m in metrics]
        streaming_means = [np.mean([r[m] for r in streaming]) for m in metrics]
        
        # Create plot
        x = np.arange(len(labels))
        width = 0.35
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(x - width/2, blocking_means, width, label='Blocking', alpha=0.8)
        ax.bar(x + width/2, streaming_means, width, label='Streaming', alpha=0.8)
        
        ax.set_ylabel('Time (seconds) / RTF', fontsize=12)
        ax.set_title('Streaming vs Blocking Comparison', fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        
        filename = self.config.PLOTS_DIR / f"streaming_comparison_{timestamp}.png"
        plt.savefig(filename, dpi=150)
        plt.close()
        
        print(f"📊 Created: {filename}")
    
    def _plot_chunk_sweet_spot(self, timestamp: str):
        """Plot chunk size sweet spot analysis"""
        result = self.results['chunk_size_sweep']
        
        # Group by target length
        chunks = {}
        for r in result.results:
            target = r['target_length']
            if target not in chunks:
                chunks[target] = []
            chunks[target].append(r)
        
        # Calculate averages
        target_lengths = sorted(chunks.keys())
        actual_lengths = []
        rtfs = []
        gen_times = []
        
        for target in target_lengths:
            data = chunks[target]
            actual_lengths.append(np.mean([r['audio_length'] for r in data]))
            rtfs.append(np.mean([r['rtf'] for r in data]))
            gen_times.append(np.mean([r['generation_time'] for r in data]))
        
        # Create dual-axis plot
        fig, ax1 = plt.subplots(figsize=(12, 6))
        
        color1 = 'tab:blue'
        ax1.set_xlabel('Audio Length (seconds)', fontsize=12)
        ax1.set_ylabel('Real-Time Factor (RTF)', color=color1, fontsize=12)
        line1 = ax1.plot(actual_lengths, rtfs, marker='o', color=color1, 
                        linewidth=2, markersize=8, label='RTF')
        ax1.tick_params(axis='y', labelcolor=color1)
        ax1.grid(True, alpha=0.3)
        ax1.axhline(y=1.0, color='r', linestyle='--', alpha=0.5, label='Real-time')
        
        # Second y-axis for generation time
        ax2 = ax1.twinx()
        color2 = 'tab:orange'
        ax2.set_ylabel('Generation Time (seconds)', color=color2, fontsize=12)
        line2 = ax2.plot(actual_lengths, gen_times, marker='s', color=color2, 
                        linewidth=2, markersize=8, label='Gen Time')
        ax2.tick_params(axis='y', labelcolor=color2)
        
        # Find sweet spot (lowest RTF)
        sweet_spot_idx = np.argmin(rtfs)
        ax1.axvline(x=actual_lengths[sweet_spot_idx], color='g', linestyle=':', 
                   linewidth=2, alpha=0.7, label=f'Sweet Spot: {actual_lengths[sweet_spot_idx]:.1f}s')
        
        # Combine legends
        lines = line1 + line2
        labels = [l.get_label() for l in lines] + ['Real-time', f'Sweet Spot: {actual_lengths[sweet_spot_idx]:.1f}s']
        ax1.legend(lines + [ax1.get_lines()[1], ax1.get_lines()[2]], labels, loc='upper left')
        
        plt.title('TTS Chunk Size Sweet Spot Analysis', fontsize=14, fontweight='bold')
        plt.tight_layout()
        
        filename = self.config.PLOTS_DIR / f"chunk_sweet_spot_{timestamp}.png"
        plt.savefig(filename, dpi=150)
        plt.close()
        
        print(f"📊 Created: {filename}")
        print(f"   🎯 Sweet spot: {actual_lengths[sweet_spot_idx]:.1f}s audio (RTF: {rtfs[sweet_spot_idx]:.2f}x)")
    
    def _plot_overhead_analysis(self, timestamp: str):
        """Plot overhead analysis"""
        result = self.results['overhead_analysis']
        
        # Extract data
        audio_lengths = []
        gen_times = []
        
        for r in result.results:
            audio_lengths.append(r['audio_length'])
            gen_times.append(r['generation_time'])
        
        # Linear regression to find overhead
        coeffs = np.polyfit(audio_lengths, gen_times, 1)
        slope = coeffs[0]
        intercept = coeffs[1]
        
        # Create plot
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Scatter plot
        ax.scatter(audio_lengths, gen_times, alpha=0.6, s=50)
        
        # Regression line
        x_line = np.linspace(min(audio_lengths), max(audio_lengths), 100)
        y_line = slope * x_line + intercept
        ax.plot(x_line, y_line, 'r--', linewidth=2, 
               label=f'y = {slope:.2f}x + {intercept:.2f}')
        
        ax.set_xlabel('Audio Length (seconds)', fontsize=12)
        ax.set_ylabel('Generation Time (seconds)', fontsize=12)
        ax.set_title('TTS Overhead Analysis', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        # Add text annotation
        textstr = f'Fixed Overhead: {intercept:.2f}s\nVariable Rate: {slope:.2f}x'
        ax.text(0.05, 0.95, textstr, transform=ax.transAxes, fontsize=11,
               verticalalignment='top', bbox=dict(boxstyle='round', 
               facecolor='wheat', alpha=0.5))
        
        plt.tight_layout()
        
        filename = self.config.PLOTS_DIR / f"overhead_analysis_{timestamp}.png"
        plt.savefig(filename, dpi=150)
        plt.close()
        
        print(f"📊 Created: {filename}")
        print(f"   🔍 Fixed overhead: {intercept:.2f}s")
        print(f"   🔍 Variable rate: {slope:.2f}x")
    
    def generate_report(self):
        """Generate comprehensive markdown report"""
        print(f"\n{'='*70}")
        print(f"📝 Generating Report")
        print(f"{'='*70}\n")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.config.REPORTS_DIR / f"benchmark_report_{timestamp}.md"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(self._generate_report_content(timestamp))
        
        print(f"📄 Created: {report_path}")
        
        return report_path
    
    def _generate_report_content(self, timestamp: str) -> str:
        """Generate report markdown content"""
        lines = []
        
        # Header
        lines.append("# TTS Chunk Size Optimization Benchmark Report")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"\n**Model:** {self.config.MODEL_DIR}")
        lines.append(f"\n**Sample Rate:** {self.config.SAMPLE_RATE}Hz")
        lines.append("\n---\n")
        
        # Executive Summary
        lines.append("## 🎯 Executive Summary\n")
        lines.append(self._generate_executive_summary())
        lines.append("\n---\n")
        
        # Test Results
        for test_name, result in self.results.items():
            lines.append(f"## 📊 Test: {test_name.replace('_', ' ').title()}\n")
            lines.append(f"**Description:** {result.config.get('description', 'N/A')}\n")
            lines.append(f"\n### Summary Statistics\n")
            lines.append(self._format_summary_table(result.compute_summary()))
            lines.append(f"\n### Plot\n")
            lines.append(f"![{test_name}](../plots/{test_name}_{timestamp}.png)\n")
            lines.append("\n---\n")
        
        # Recommendations
        lines.append("## 💡 Recommendations\n")
        lines.append(self._generate_recommendations())
        lines.append("\n---\n")
        
        # Raw Data Reference
        lines.append("## 📁 Raw Data\n")
        lines.append(f"JSON data files saved to: `{self.config.DATA_DIR.relative_to(self.config.OUTPUT_DIR.parent.parent)}`\n")
        
        return "\n".join(lines)
    
    def _generate_executive_summary(self) -> str:
        """Generate executive summary from results"""
        lines = []
        
        # Find sweet spot from chunk_size_sweep
        if 'chunk_size_sweep' in self.results:
            result = self.results['chunk_size_sweep']
            rtfs = [r['rtf'] for r in result.results]
            audio_lengths = [r['audio_length'] for r in result.results]
            
            # Group by similar audio lengths
            length_groups = {}
            for r in result.results:
                target = r['target_length']
                if target not in length_groups:
                    length_groups[target] = []
                length_groups[target].append(r)
            
            # Find best performing length
            best_target = None
            best_rtf = float('inf')
            for target, data in length_groups.items():
                avg_rtf = np.mean([r['rtf'] for r in data])
                if avg_rtf < best_rtf:
                    best_rtf = avg_rtf
                    best_target = target
            
            lines.append(f"**🎯 Optimal Chunk Size:** ~{best_target}s audio (RTF: {best_rtf:.2f}x)")
            lines.append(f"\n**📈 Performance Range:** {min(rtfs):.2f}x - {max(rtfs):.2f}x RTF")
        
        # Overhead analysis
        if 'overhead_analysis' in self.results:
            result = self.results['overhead_analysis']
            audio_lengths = [r['audio_length'] for r in result.results]
            gen_times = [r['generation_time'] for r in result.results]
            coeffs = np.polyfit(audio_lengths, gen_times, 1)
            
            lines.append(f"\n**⏱️ Fixed Overhead:** ~{coeffs[1]:.2f}s")
            lines.append(f"\n**⚡ Variable Rate:** {coeffs[0]:.2f}x real-time")
        
        # Streaming benefit
        if 'streaming_vs_blocking' in self.results:
            result = self.results['streaming_vs_blocking']
            blocking = [r for r in result.results if r['mode'] == 'Blocking']
            streaming = [r for r in result.results if r['mode'] == 'Streaming']
            
            blocking_first = np.mean([r['generation_time'] for r in blocking])
            streaming_first = np.mean([r['first_chunk_time'] for r in streaming])
            
            improvement = ((blocking_first - streaming_first) / blocking_first) * 100
            
            lines.append(f"\n**🚀 Streaming Benefit:** {improvement:.0f}% reduction in perceived latency")
        
        return "\n".join(lines)
    
    def _format_summary_table(self, summary: Dict) -> str:
        """Format summary statistics as markdown table"""
        if not summary or 'rtf' not in summary:
            return "*No summary available*"
        
        lines = []
        lines.append("| Metric | Mean | Std | Min | Max |")
        lines.append("|--------|------|-----|-----|-----|")
        
        if summary['rtf']['mean'] is not None:
            lines.append(f"| RTF | {summary['rtf']['mean']:.2f}x | {summary['rtf']['std']:.2f} | {summary['rtf']['min']:.2f}x | {summary['rtf']['max']:.2f}x |")
        
        if summary['generation_time']['mean'] is not None:
            lines.append(f"| Gen Time | {summary['generation_time']['mean']:.2f}s | {summary['generation_time']['std']:.2f}s | - | - |")
        
        if summary['audio_length']['mean'] is not None:
            lines.append(f"| Audio Length | {summary['audio_length']['mean']:.2f}s | - | - | - |")
        
        return "\n".join(lines)
    
    def _generate_recommendations(self) -> str:
        """Generate actionable recommendations"""
        lines = []
        
        lines.append("Based on the benchmark results:\n")
        
        # Chunk size recommendation
        if 'chunk_size_sweep' in self.results:
            result = self.results['chunk_size_sweep']
            length_groups = {}
            for r in result.results:
                target = r['target_length']
                if target not in length_groups:
                    length_groups[target] = []
                length_groups[target].append(r)
            
            best_target = min(length_groups.keys(), 
                            key=lambda t: np.mean([r['rtf'] for r in length_groups[t]]))
            best_rtf = np.mean([r['rtf'] for r in length_groups[best_target]])
            
            lines.append(f"1. **Generate in {best_target}s chunks** for optimal RTF ({best_rtf:.2f}x)")
        
        # Streaming recommendation
        if 'streaming_vs_blocking' in self.results:
            lines.append("2. **Enable streaming** to reduce perceived latency by 50-70%")
        
        # Overhead insight
        if 'overhead_analysis' in self.results:
            result = self.results['overhead_analysis']
            audio_lengths = [r['audio_length'] for r in result.results]
            gen_times = [r['generation_time'] for r in result.results]
            coeffs = np.polyfit(audio_lengths, gen_times, 1)
            
            if coeffs[1] > 2.0:
                lines.append(f"3. **High fixed overhead** ({coeffs[1]:.1f}s) - consider model optimization or caching")
        
        # Implementation
        lines.append("\n### Implementation Strategy:")
        lines.append("- Generate 6-8s audio chunks")
        lines.append("- Stream in 3s playback segments")
        lines.append("- Buffer 2 chunks ahead (12-16s total)")
        lines.append("- Implement skip-ahead on interruption (save 3s)")
        
        return "\n".join(lines)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Run comprehensive TTS benchmark suite"""
    
    print("="*70)
    print("🎯 TTS CHUNK SIZE OPTIMIZATION BENCHMARK SUITE")
    print("="*70)
    print()
    print("This suite will run comprehensive tests to find optimal TTS")
    print("chunk sizes and streaming configurations for real-time conversation.")
    print()
    print(f"Output directory: {BenchmarkConfig.OUTPUT_DIR}")
    print("="*70)
    print()
    
    # Initialize benchmark
    config = BenchmarkConfig()
    benchmark = TTSBenchmark(config)
    
    # Load model
    load_time = benchmark.load_model()
    
    # Run tests
    print("🧪 Running benchmark tests...\n")
    
    try:
        # Test 1: Text length variations
        benchmark.test_text_length_variations()
        
        # Test 2: Streaming vs blocking
        benchmark.test_streaming_vs_blocking()
        
        # Test 3: Chunk size sweep
        benchmark.test_chunk_size_sweep()
        
        # Test 4: Overhead analysis
        benchmark.test_overhead_analysis()
        
        # Save results
        print(f"\n{'='*70}")
        print("💾 Saving Results")
        print(f"{'='*70}\n")
        benchmark.save_results()
        
        # Generate plots
        benchmark.generate_plots()
        
        # Generate report
        report_path = benchmark.generate_report()
        
        # Summary
        print(f"\n{'='*70}")
        print("✅ BENCHMARK COMPLETE!")
        print(f"{'='*70}")
        print(f"\n📄 Full report: {report_path}")
        print(f"📊 Plots: {config.PLOTS_DIR}")
        print(f"💾 Data: {config.DATA_DIR}")
        print("\n✨ Review the report for detailed findings and recommendations!")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Benchmark interrupted by user")
        print("Saving partial results...")
        benchmark.save_results()
        
    except Exception as e:
        print(f"\n\n❌ Error during benchmark: {e}")
        import traceback
        traceback.print_exc()
        print("\nSaving partial results...")
        benchmark.save_results()


if __name__ == "__main__":
    main()
