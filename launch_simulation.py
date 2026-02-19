"""
Quick Launch Script for Virtual Companion System
"""
import sys
import subprocess


def launch_dashboard():
    """Launch the Streamlit dashboard"""
    print("\n🚀 Launching Dashboard...")
    print("Opening in browser: http://localhost:8501\n")
    subprocess.run(["streamlit", "run", "simulation/scenes/dashboard/dashboard_v2.py"])


def launch_phone():
    """Launch the phone scene"""
    print("\n📱 Launching Phone Scene...")
    print("Opening in browser: http://localhost:5555\n")
    subprocess.run(["python", "simulation/scenes/phone/phone_scene.py"])


def launch_bedroom():
    """Launch the bedroom scene"""
    print("\n🏠 Launching Bedroom Scene...")
    print("Opening in browser: http://localhost:5556\n")
    subprocess.run(["python", "simulation/scenes/bedroom/bedroom_scene.py"])


def launch_all():
    """Launch all scenes"""
    print("\n🚀 Launching All Scenes...")
    print("Dashboard: http://localhost:8501")
    print("Phone: http://localhost:5555")
    print("Bedroom: http://localhost:5556\n")
    
    import multiprocessing
    
    processes = []
    
    # Launch dashboard
    p1 = multiprocessing.Process(target=lambda: subprocess.run(
        ["streamlit", "run", "simulation/scenes/dashboard/dashboard_v2.py"]
    ))
    processes.append(p1)
    
    # Launch phone
    p2 = multiprocessing.Process(target=lambda: subprocess.run(
        ["python", "simulation/scenes/phone/phone_scene.py"]
    ))
    processes.append(p2)
    
    # Launch bedroom
    p3 = multiprocessing.Process(target=lambda: subprocess.run(
        ["python", "simulation/scenes/bedroom/bedroom_scene.py"]
    ))
    processes.append(p3)
    
    for p in processes:
        p.start()
    
    print("✅ All scenes launched! Press Ctrl+C to stop all.\n")
    
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\n⏹️ Stopping all scenes...")
        for p in processes:
            p.terminate()


def test_system():
    """Test the system"""
    print("\n🧪 Running System Tests...\n")
    subprocess.run(["python", "simulation/test_system.py"])


def install_deps():
    """Install dependencies"""
    print("\n📦 Installing Dependencies...\n")
    subprocess.run(["pip", "install", "-r", "simulation/requirements.txt"])
    print("\n✅ Dependencies installed!")


def main():
    print("=" * 50)
    print("🎮 VIRTUAL COMPANION SYSTEM")
    print("=" * 50)
    print("\nSelect an option:")
    print("1. Launch Dashboard (Character Management)")
    print("2. Launch Phone Scene (Phone Interface)")
    print("3. Launch Bedroom Scene (3D Environment)")
    print("4. Launch All Scenes")
    print("5. Test System")
    print("6. Install/Update Dependencies")
    print("7. Exit")
    print()
    
    choice = input("Enter choice (1-7): ").strip()
    
    if choice == "1":
        launch_dashboard()
    elif choice == "2":
        launch_phone()
    elif choice == "3":
        launch_bedroom()
    elif choice == "4":
        launch_all()
    elif choice == "5":
        test_system()
    elif choice == "6":
        install_deps()
    elif choice == "7":
        print("Goodbye!")
        sys.exit(0)
    else:
        print("\n❌ Invalid choice. Please run the script again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
