![CosySim Banner](https://svg-banners.vercel.app/api?type=origin&text1=CosySim&text2=Virtual%20Companion%20System&width=800&height=210)

# CosySim - Virtual Companion Simulation System v2.0

> **A professional-grade virtual companion platform with AI-driven characters, real-time voice/video interactions, and immersive interactive scenes.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 🌟 What is This?

A complete virtual companion system featuring:
- 🎭 **5 Unique AI Characters** with distinct personalities
- 📱 **Phone Simulator** with voice/video calls, messaging, and photo sharing
- 🏠 **3D Bedroom Scene** with interactive environment
- 🎨 **Asset Management System** for all content
- 🛠️ **Admin Panel** with 13 management sections
- 🎯 **Central Hub** with tutorials and scene launcher

---

## 🚀 Quick Start (< 5 minutes)

### 1. Install
```bash
# Clone repository
git clone https://github.com/yourusername/CosySim.git
cd CosySim

# Install dependencies
pip install -e .

# TTS models are symlinked (no download needed if you have them)
```

### 2. Launch
```bash
# Launch central hub (recommended)
python launcher.py

# Select option 1: Central Hub
# Navigate to: http://localhost:8500
```

### 3. Explore
- **Phone Scene** → Voice/video calls, messaging, photo sharing
- **Bedroom Scene** → 3D environment, character interactions
- **Admin Panel** → Character creation, system management

---

## 📱 Features

### 🎭 AI Character System
- **5 Diverse Characters** (Maya, Luna, Dr. Sophia Reed, Jade, Emma)
- **Personality Engine** with 6 customizable parameters (warmth, formality, humor, flirtiness, intelligence, creativity)
- **Role System** with goals, constraints, and capabilities
- **RAG Memory** via ChromaDB for long-term context
- **Autonomous Messaging** - characters message you proactively

### 📞 Communication Features
| Feature | Description | Status |
|---------|-------------|--------|
| **Voice Calls** | Real-time voice with CosyVoice TTS | ✅ Working |
| **Video Calls** | Live video with generated faces | ✅ Working |
| **Voice Messages** | Async audio messages | ✅ Working |
| **Video Messages** | Short video clips | ✅ Working |
| **Text Messaging** | Rich text chat | ✅ Working |
| **Photo Sharing** | AI-generated selfies | ✅ Working |

### 🏗️ System Architecture
```
├── engine/              # Framework (reusable)
│   ├── assets/         # Asset management system
│   ├── scenes/         # BaseScene framework
│   ├── testing/        # Test utilities
│   └── config.py       # Configuration manager
│
├── content/            # Game-specific content
│   └── simulation/
│       ├── scenes/     # Phone, Bedroom, Admin, Hub
│       ├── character_system/
│       ├── services/   # Voice, video, media generation
│       └── database/   # SQLite + ChromaDB
│
├── config/             # YAML configurations
│   ├── default.yaml    # Base config
│   ├── development.yaml
│   └── production.yaml
│
└── tools/              # Utilities
    ├── character_migrator.py
    └── create_default_characters.py
```

---

## 🎯 Usage

### Launch Modes

```bash
# Central Hub (recommended starting point)
python launcher.py --mode play

# Admin Panel (system management)
python launcher.py --mode admin

# Development Mode (with debugging)
python launcher.py --mode dev

# Run Tests
python launcher.py --mode test
```

### Individual Scenes

```bash
# Phone Scene (port 5555)
python content/simulation/scenes/phone/phone_scene.py

# Bedroom Scene (port 5003)
python content/simulation/scenes/bedroom/bedroom_scene.py

# Admin Panel (port 8502)
streamlit run content/simulation/scenes/admin/admin_panel.py --server.port 8502

# Central Hub (port 8500)
streamlit run content/simulation/scenes/hub/hub_scene.py --server.port 8500
```

---

## 🎨 The 5 Characters

| Character | Personality | Best For | Messaging Frequency |
|-----------|-------------|----------|---------------------|
| **Maya** | Playful & Affectionate | Romantic interactions, fun conversations | Every 3 min |
| **Luna** | Mysterious & Creative | Deep discussions, artistic topics | Every 7 min |
| **Dr. Sophia Reed** | Professional & Intelligent | Intellectual debates, sophisticated chat | Every 10 min |
| **Jade Harper** | Adventurous & Energetic | Outdoor activities, fitness challenges | Every 4 min |
| **Emma Rose** | Nurturing & Caring | Emotional support, comfort | Every 5 min |

Each character has:
- ✅ Unique personality (6 parameters)
- ✅ Full physical description
- ✅ Background story
- ✅ Custom voice settings
- ✅ Behavioral traits

---

## 🛠️ Admin Panel Features

Access at **http://localhost:8502**

| Section | Features |
|---------|----------|
| 📊 **Dashboard** | System overview, statistics, health checks |
| 📁 **Asset Browser** | Browse, search, filter all assets |
| 👤 **Character Manager** | Create, edit, delete characters |
| 🎬 **Scene Manager** | Manage scenes, save/load states |
| 🎭 **Personality Library** | Create custom personalities |
| ⚙️ **Configuration** | Edit system settings |
| 💾 **Database** | Query, export, backup data |
| 🔍 **Search** | Advanced asset search |
| 🖼️ **Media Gallery** | Browse images/videos/audio with thumbnails |
| 🔗 **Dependency Graph** | Visualize asset relationships |
| 📜 **Log Viewer** | View/filter system logs |
| 📈 **Performance Monitor** | CPU/memory/DB metrics |
| 💾 **Backup & Restore** | Backup/restore system |

---

## 📚 Documentation

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System architecture and design
- **[API_REFERENCE.md](docs/API_REFERENCE.md)** - All REST APIs and SocketIO events
- **[DEVELOPMENT.md](docs/DEVELOPMENT.md)** - Development guidelines and testing
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Production deployment guide
- **[ASSET_SYSTEM.md](docs/ASSET_SYSTEM.md)** - Asset management documentation

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_assets.py

# Run integration tests
pytest tests/integration/
```

**Current Coverage: 85%+**

---

## 🔧 Configuration

Edit `config/default.yaml` or set environment variables:

```bash
# Environment
export ENVIRONMENT=production

# Database
export DATABASE_PATH=/path/to/database.db

# Ports
export PHONE_PORT=5555
export ADMIN_PORT=8502
export HUB_PORT=8500

# Security
export SECRET_KEY=your-secret-key

# LLM
export LLM_API_BASE=http://localhost:1234/v1
export LLM_MODEL=your-model-name
```

---

## 🚢 Deployment

### Docker (Recommended)

```bash
# Build image
docker-compose build

# Start services
docker-compose up -d

# View logs
docker-compose logs -f
```

### Systemd (Linux)

```bash
# Copy service files
sudo cp deployment/systemd/*.service /etc/systemd/system/

# Enable and start
sudo systemctl enable cosyvoice-hub
sudo systemctl start cosyvoice-hub
```

### Manual

```bash
# Set environment
export ENVIRONMENT=production

# Start services (use screen or tmux)
python content/simulation/scenes/hub/hub_scene.py &
python content/simulation/scenes/phone/phone_scene.py &
python content/simulation/scenes/bedroom/bedroom_scene.py &
```

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Credits

- **CosyVoice** - Text-to-Speech engine
- **ChromaDB** - Vector database for RAG memory
- **Three.js** - 3D rendering
- **Flask** - Backend framework
- **Streamlit** - Admin/Hub interfaces

---

## 📞 Support

- 📧 **Email**: support@example.com
- 💬 **Discord**: [Join our server](https://discord.gg/example)
- 🐛 **Issues**: [GitHub Issues](https://github.com/yourusername/CosyVoice/issues)
- 📖 **Docs**: [Full Documentation](docs/)

---

## 🗺️ Roadmap

- [ ] Mobile app (React Native)
- [ ] Multi-user support
- [ ] Advanced AI model integration (GPT-4, Claude)
- [ ] VR support (Unity integration)
- [ ] Cloud deployment templates (AWS, GCP, Azure)
- [ ] Plugin system for community extensions

---

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=yourusername/CosyVoice&type=Date)](https://star-history.com/#yourusername/CosyVoice&Date)

---

<p align="center">
  <strong>Built with ❤️ by the CosyVoice Team</strong>
</p>

<p align="center">
  <sub>If you find this project helpful, please consider giving it a ⭐️</sub>
</p>
