# Pull fresh llama.cpp
cd D:\Files\customllama
git clone https://github.com/ggml-org/llama.cpp.git llama-cpp-prime
cd llama-cpp-prime

# Build with CUDA for your 2060
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75
cmake --build build --config Release -j

# Baseline perplexity (before any changes)
.\build\bin\Release\llama-perplexity.exe -m "D:\Files\Models\Dolphin3.0-Llama3.2-1B.Q8_0.gguf" -f wiki.test.raw --ctx-size 2048