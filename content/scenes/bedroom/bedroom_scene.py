"""
3D Bedroom Scene - Flask Server with SocketIO
Handles scene state, character interactions, and real-time updates
Now with asset-based character system
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from typing import Optional
import sqlite3
import json
from datetime import datetime
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from engine.scenes.base_scene import BaseScene
from engine.assets import CharacterAsset
from content.simulation.database.db import Database
from content.simulation.character_system.character import Character


class BedroomScene(BaseScene):
    """
    3D Bedroom Scene with asset-based character system
    Inherits from BaseScene for character/asset management
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 5003):
        # Initialize BaseScene first
        super().__init__(scene_name="bedroom", host=host, port=port)
        
        # Initialize database
        self.db = Database()
        
        # Scene state
        self.scene_state = {
            'time_of_day': 'afternoon',
            'character_position': {'x': 0, 'y': 0, 'z': 0},
            'character_animation': 'idle',
            'lighting': {
                'ambient': 0.6,
                'directional': 0.8,
                'color': '#ffffff'
            },
            'active_character_id': None
        }
        
        # Active character instance (for compatibility)
        self.active_character: Optional[Character] = None
        
        # Lighting presets
        self.lighting_presets = {
            'morning': {
                'ambient': 0.7,
                'directional': 0.9,
                'color': '#e8f4f8'
            },
            'afternoon': {
                'ambient': 0.6,
                'directional': 0.8,
                'color': '#fff8e8'
            },
            'evening': {
                'ambient': 0.4,
                'directional': 0.5,
                'color': '#ffb088'
            },
            'night': {
                'ambient': 0.2,
                'directional': 0.3,
                'color': '#6688cc'
            }
        }
        
        # Flask app
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static")
        )
        self.app.config['SECRET_KEY'] = 'bedroom_scene_secret_key_2024'
        CORS(self.app)
        
        # Socket.IO for real-time communication
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", manage_session=False)
        
        # Initialize lighting
        self.update_lighting_for_time('afternoon')
        
        # Setup routes
        self._setup_routes()
        self._setup_socketio()
    
    def update_lighting_for_time(self, time_of_day: str):
        """Update lighting based on time of day"""
        self.scene_state['lighting'] = self.lighting_presets.get(
            time_of_day, 
            self.lighting_presets['afternoon']
        )
    
    def _asset_to_character(self, char_asset: CharacterAsset) -> Character:
        """
        Convert CharacterAsset to Character object for compatibility
        This maintains compatibility with existing services
        """
        # Try to load existing character from database
        try:
            char = Character.load(char_asset.id, db=self.db)
            if char:
                return char
        except:
            pass
        
        # Create new character in database from asset
        char_id_new = self.db.create_character(
            name=char_asset.name,
            age=char_asset.age or 25,
            sex=char_asset.gender or 'female',
            hair_color=char_asset.hair_color or 'brown',
            eye_color=char_asset.eye_color or 'brown',
            height=char_asset.height or '5\'6"',
            body_type=char_asset.build or 'slim',
            personality_id=char_asset.personality_id,
            metadata={
                'description': char_asset.description,
                'backstory': char_asset.attributes.get('backstory', ''),
                'voice_profile': char_asset.voice_profile,
                'relationship_level': char_asset.relationships.get('user', 0.5),
                'from_asset': True,
                'asset_id': char_asset.id
            }
        )
        
        # Update character ID in database to match asset ID if needed
        if char_id_new != char_asset.id:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE characters SET id = ? WHERE id = ?", (char_asset.id, char_id_new))
                cursor.execute("UPDATE character_states SET character_id = ? WHERE character_id = ?", (char_asset.id, char_id_new))
                conn.commit()
        
        # Load and return
        return Character.load(char_asset.id, db=self.db)
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            """Render bedroom scene"""
            return render_template('bedroom_ui.html')
        
        @self.app.route('/api/scene/state', methods=['GET'])
        def get_scene_state():
            """Get current scene state"""
            return jsonify(self.scene_state)
        
        @self.app.route('/api/scene/time', methods=['POST'])
        def set_time_of_day():
            """Set time of day"""
            data = request.json
            time_of_day = data.get('time', 'afternoon')
            self.scene_state['time_of_day'] = time_of_day
            self.update_lighting_for_time(time_of_day)
            
            # Broadcast to all clients
            self.socketio.emit('time_changed', {
                'time': time_of_day,
                'lighting': self.scene_state['lighting']
            })
            
            return jsonify({'success': True, 'state': self.scene_state})
        
        @self.app.route('/api/character/interact', methods=['POST'])
        def character_interact():
            """Handle character interaction"""
            data = request.json
            interaction_type = data.get('type', 'wave')
            
            # Set character animation
            animations = {
                'talk': 'talking',
                'hug': 'hugging',
                'wave': 'waving',
                'kiss': 'kissing'
            }
            
            animation = animations.get(interaction_type, 'idle')
            self.scene_state['character_animation'] = animation
            
            # Broadcast to all clients
            self.socketio.emit('character_animation', {
                'animation': animation,
                'type': interaction_type
            })
            
            # Store interaction in database
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO interactions (type, timestamp, data)
                        VALUES (?, ?, ?)
                    ''', (interaction_type, datetime.now().isoformat(), json.dumps(data)))
                    conn.commit()
            except Exception as e:
                print(f"Database error: {e}")
            
            # Reset animation after delay
            def reset_animation():
                import time
                time.sleep(3)
                self.scene_state['character_animation'] = 'idle'
                self.socketio.emit('character_animation', {
                    'animation': 'idle',
                    'type': 'reset'
                })
            
            from threading import Thread
            Thread(target=reset_animation, daemon=True).start()
            
            return jsonify({
                'success': True,
                'animation': animation,
                'message': f'Character is {animation}!'
            })
        
        @self.app.route('/api/character/position', methods=['POST'])
        def update_character_position():
            """Update character position"""
            data = request.json
            position = data.get('position', {'x': 0, 'y': 0, 'z': 0})
            self.scene_state['character_position'] = position
            
            # Broadcast to all clients
            self.socketio.emit('character_moved', {
                'position': position
            })
            
            return jsonify({'success': True, 'position': position})
        
        @self.app.route('/api/history', methods=['GET'])
        def get_history():
            """Get conversation history"""
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT * FROM conversations
                        ORDER BY timestamp DESC
                        LIMIT 50
                    ''')
                    rows = cursor.fetchall()
                
                history = [dict(row) for row in rows]
                return jsonify({'success': True, 'history': history})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})
        
        # ============= CHARACTER MANAGEMENT ROUTES =============
        
        @self.app.route('/api/characters/list', methods=['GET'])
        def list_characters():
            """List all characters (from both asset system and database)"""
            # Get characters from asset system
            asset_characters = []
            try:
                search_results = self.asset_manager.search(asset_type='character', limit=100)
                for result in search_results:
                    char_asset = self.asset_manager.load('character', result['id'])
                    asset_characters.append({
                        'id': char_asset.id,
                        'name': char_asset.name,
                        'description': char_asset.description,
                        'source': 'asset'
                    })
            except Exception as e:
                print(f"Error loading asset characters: {e}")
            
            # Get characters from database (legacy)
            db_characters = self.db.get_all_characters()
            for char in db_characters:
                char['source'] = 'database'
            
            # Combine both
            all_characters = asset_characters + db_characters
            return jsonify({'characters': all_characters})
        
        @self.app.route('/api/character/set', methods=['POST'])
        def set_character():
            """Set active character (legacy database)"""
            data = request.json
            char_id = data.get('character_id')
            
            if not char_id:
                return jsonify({'error': 'No character_id provided'}), 400
            
            try:
                self.active_character = Character.load(char_id, db=self.db)
                if not self.active_character:
                    return jsonify({'error': 'Character not found'}), 404
                
                self.scene_state['active_character_id'] = char_id
                
                # Broadcast character change
                self.socketio.emit('character_changed', {
                    'character_id': char_id,
                    'character_name': self.active_character.name
                })
                
                return jsonify({
                    'success': True,
                    'character': {
                        'id': self.active_character.id,
                        'name': self.active_character.name
                    }
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/character/load_asset', methods=['POST'])
        def load_character_asset():
            """Load character from asset system"""
            data = request.json
            char_id = data.get('character_id')
            
            if not char_id:
                return jsonify({'error': 'No character_id provided'}), 400
            
            try:
                # Load character asset
                char_asset = self.load_character(char_id)
                
                # Create or update Character wrapper for compatibility
                self.active_character = self._asset_to_character(char_asset)
                self.scene_state['active_character_id'] = char_id
                
                # Broadcast character change
                self.socketio.emit('character_changed', {
                    'character_id': char_id,
                    'character_name': char_asset.name
                })
                
                return jsonify({
                    'success': True,
                    'character': {
                        'id': char_asset.id,
                        'name': char_asset.name,
                        'description': char_asset.description
                    }
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/character/info', methods=['GET'])
        def get_character_info():
            """Get active character info"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            return jsonify({
                'id': self.active_character.id,
                'name': self.active_character.name,
                'age': self.active_character.age,
                'mood': self.active_character.mood,
                'relationship_level': self.active_character.relationship_level
            })
        
        # ============= SCENE SAVE/LOAD ROUTES =============
        
        @self.app.route('/api/scene/save', methods=['POST'])
        def save_scene_route():
            """Save current scene state"""
            data = request.json
            name = data.get('name')
            
            # Save additional settings
            self.scene_config['settings'] = {
                'time_of_day': self.scene_state['time_of_day'],
                'character_position': self.scene_state['character_position'],
                'lighting': self.scene_state['lighting']
            }
            
            try:
                scene_id = self.save_scene(name)
                return jsonify({'success': True, 'scene_id': scene_id})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/scene/load', methods=['POST'])
        def load_scene_route():
            """Load scene from asset"""
            data = request.json
            scene_id = data.get('scene_id')
            
            if not scene_id:
                return jsonify({'error': 'No scene_id provided'}), 400
            
            try:
                self.load_scene(scene_id)
                
                # Restore scene settings
                settings = self.scene_config.get('settings', {})
                if 'time_of_day' in settings:
                    self.scene_state['time_of_day'] = settings['time_of_day']
                    self.update_lighting_for_time(settings['time_of_day'])
                if 'character_position' in settings:
                    self.scene_state['character_position'] = settings['character_position']
                
                # Load first character as active if available
                if self.active_characters:
                    first_char_id = list(self.active_characters.keys())[0]
                    char_asset = self.active_characters[first_char_id]
                    self.active_character = self._asset_to_character(char_asset)
                    self.scene_state['active_character_id'] = first_char_id
                
                # Broadcast scene loaded
                self.socketio.emit('scene_loaded', {
                    'scene_id': scene_id,
                    'state': self.scene_state
                })
                
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/scene/list', methods=['GET'])
        def list_scenes():
            """List all saved scenes"""
            try:
                scenes = self.asset_manager.search(asset_type='scene', limit=100)
                return jsonify({'scenes': scenes})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    
    def _setup_socketio(self):
        """Setup SocketIO event handlers"""
    def _setup_socketio(self):
        """Setup SocketIO event handlers"""
        
        @self.socketio.on('connect')
        def handle_connect():
            """Handle client connection"""
            print('Client connected')
            emit('scene_state', self.scene_state)
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handle client disconnection"""
            print('Client disconnected')
        
        @self.socketio.on('request_state')
        def handle_request_state():
            """Send current scene state to client"""
            emit('scene_state', self.scene_state)
        
        @self.socketio.on('chat_message')
        def handle_chat_message(data):
            """Handle chat messages"""
            message = data.get('message', '')
            
            # Store in database
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO conversations (user_message, timestamp)
                        VALUES (?, ?)
                    ''', (message, datetime.now().isoformat()))
                    conn.commit()
            except Exception as e:
                print(f"Database error: {e}")
            
            # Broadcast to all clients
            emit('chat_message', {
                'message': message,
                'timestamp': datetime.now().isoformat()
            }, broadcast=True)
            
            # Trigger character talking animation
            self.scene_state['character_animation'] = 'talking'
            emit('character_animation', {
                'animation': 'talking',
                'type': 'talk'
            }, broadcast=True)
    
    def start(self) -> None:
        """Start the bedroom scene server"""
        print("Starting 3D Bedroom Scene Server...")
        print(f"Access at: http://{self.host}:{self.port}")
        self.socketio.run(
            self.app, 
            host=self.host, 
            port=self.port, 
            debug=True, 
            allow_unsafe_werkzeug=True
        )
    
    def stop(self) -> None:
        """Stop the bedroom scene server"""
        print("Stopping 3D Bedroom Scene Server...")
        # Flask-SocketIO doesn't have a clean stop method
        # The server will be stopped when the process exits


if __name__ == '__main__':
    scene = BedroomScene(host='0.0.0.0', port=5003)
    scene.start()
