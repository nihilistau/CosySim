# 🎮 Scene Launch Guide - Step by Step

## ✅ Dependencies Fixed!

**Status:** All import paths corrected, ComfyUI made optional

---

## 🚀 Scene 1: Dashboard (RUNNING NOW!)

**Port:** 8501  
**Type:** Streamlit app  
**Status:** ✅ Launched successfully

**Launch command:**
```bash
streamlit run content\simulation\scenes\dashboard\dashboard_v2.py --server.port 8501
```

**What it does:**
- Character management interface
- View all 5 characters (Sophia, Emma, Isabella, Olivia, Mia)
- Character details and stats

**To stop:** Ctrl+C in terminal or close browser

---

## 📱 Scene 2: Phone Scene

**Port:** 5555  
**Type:** Flask app  
**Best for:** Messaging, voice/video calls, gallery

**Launch command:**
```bash
cd C:\Files\Models\CosySim
python -m content.simulation.scenes.phone.phone_scene
```

**What it does:**
- Android phone interface
- Text messaging with characters
- Voice and video calls
- Photo gallery
- Notifications

**Features:**
- Real-time messaging
- Character AI responses
- Media sharing
- Call simulation

---

## 🛏️ Scene 3: Bedroom Scene

**Port:** 5003  
**Type:** Flask app  
**Best for:** Interactive 3D environment

**Launch command:**
```bash
python -m content.simulation.scenes.bedroom.bedroom_scene
```

**What it does:**
- Interactive bedroom environment
- Character presence
- Ambient interactions
- Scene customization

---

## 🏠 Scene 4: Central Hub

**Port:** 8500  
**Type:** Streamlit app  
**Best for:** Tutorial and scene launcher

**Launch command:**
```bash
streamlit run content\simulation\scenes\hub\hub_scene.py --server.port 8500
```

**What it does:**
- Central control panel
- Scene launcher
- Asset browser
- System tutorials
- Quick access to all scenes

---

## 🛠️ Scene 5: Admin Panel

**Port:** 8502  
**Type:** Flask app  
**Best for:** System management

**Launch command:**
```bash
python -m content.scenes.admin.admin_panel
```

**What it does:**
- 13 management sections
- Database management
- Asset management
- Character configuration
- System settings
- Logs and monitoring

---

## 🎯 Launch Order (Recommended)

For first-time exploration:

1. **Dashboard** (8501) ✅ - Start here to see characters
2. **Phone Scene** (5555) - Try messaging
3. **Hub** (8500) - See the control center
4. **Bedroom** (5003) - Experience the environment
5. **Admin Panel** (8502) - Advanced management

---

## 🔧 Troubleshooting

### Port Already in Use
```bash
# Kill process on port
netstat -ano | findstr :5555
taskkill /PID <process_id> /F
```

### Import Errors
All fixed! But if you see any:
```bash
cd C:\Files\Models\CosySim
python fix_imports_auto.py
```

### Streamlit Issues
```bash
streamlit cache clear
```

### Module Not Found
```bash
# Make sure you're in the right directory
cd C:\Files\Models\CosySim

# Check Python path
python -c "import sys; print(sys.path)"
```

---

## 📝 Quick Launch Script

Save this as `launch_all.ps1`:

```powershell
# Launch all scenes at once
cd C:\Files\Models\CosySim

# Start Dashboard
Start-Process powershell -ArgumentList "-NoExit", "-Command", "streamlit run content\simulation\scenes\dashboard\dashboard_v2.py --server.port 8501"

# Start Phone Scene
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m content.simulation.scenes.phone.phone_scene"

# Start Hub
Start-Process powershell -ArgumentList "-NoExit", "-Command", "streamlit run content\simulation\scenes\hub\hub_scene.py --server.port 8500"

Write-Host "All scenes launching!"
Write-Host "Dashboard: http://localhost:8501"
Write-Host "Phone:     http://localhost:5555"
Write-Host "Hub:       http://localhost:8500"
```

---

## 🎨 Scene Features Summary

| Scene | Port | Type | Best For | Complexity |
|-------|------|------|----------|------------|
| Dashboard | 8501 | Streamlit | Character mgmt | ⭐ Simple |
| Phone | 5555 | Flask | Messaging & calls | ⭐⭐ Medium |
| Hub | 8500 | Streamlit | Central control | ⭐⭐ Medium |
| Bedroom | 5003 | Flask | 3D environment | ⭐⭐⭐ Complex |
| Admin | 8502 | Flask | System management | ⭐⭐⭐ Advanced |

---

## 💡 Tips

- **Start with Dashboard** - Simple, visual, shows your characters
- **Then Phone Scene** - Most interactive, fun to try messaging
- **Use Hub** - Central launcher for quick access
- **Explore Admin** - When you want to dig deeper
- **Try Bedroom last** - Most complex scene

---

## 🔄 Switching Scenes

1. **Stop current scene** - Ctrl+C in terminal
2. **Launch new scene** - Use command from this guide
3. **Or run multiple** - Use launch_all.ps1 script

---

## ✨ Next Steps After Launching

1. **Explore Dashboard** (running now!)
   - See all 5 characters
   - View their personalities
   
2. **Try Phone Scene**
   - Send a message to a character
   - Try a voice call
   - Check the gallery

3. **Configure in Admin**
   - Adjust settings
   - View system stats
   - Manage assets

4. **Launch All Together**
   - Experience full system
   - Switch between scenes
   - See integration

---

**Happy exploring! 🚀**

Currently running: Dashboard on http://localhost:8501
