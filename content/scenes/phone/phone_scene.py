"""
Phone Scene - Android Phone Simulation
Main interface for phone-based interactions
"""
from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO, emit
from typing import Dict, List, Optional
import sys
from pathlib import Path
from datetime import datetime
import uuid
import os
import random
import threading
import requests as http_requests
from werkzeug.utils import secure_filename

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database
from content.simulation.database.rag import RAGMemory
from content.simulation.character_system.character import Character
from content.simulation.services.media_generator import MediaGenerator
from content.simulation.services.autonomous_messenger import AutonomousMessenger
from content.simulation.services.voice_call import VoiceCallHandler
from content.simulation.services.voice_message import VoiceMessageGenerator
from content.simulation.services.video_call import VideoCallHandler
from content.simulation.services.video_message import VideoMessageGenerator
from content.scenes.phone.apps.gallery import Gallery
from content.scenes.phone.apps.video_messages import VideoMessagesApp
from content.scenes.phone.apps.voice_messages import VoiceMessagesApp
from engine.scenes.base_scene import BaseScene
from engine.assets import CharacterAsset
from content.simulation.services.llm_service import get_llm_service
from content.simulation.services.anonymous_character import create_anonymous_character, AnonymousCharacter
from engine.logging import install_logger, get_logs


class PhoneScene(BaseScene):
    """
    Phone scene manager - handles phone UI and interactions
    Inherits from BaseScene for asset management
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 5555):
        # Initialize BaseScene first
        super().__init__(scene_name="phone", host=host, port=port)
        
        # Initialize database and RAG
        self.db = Database()
        self.rag = RAGMemory()
        
        # Initialize media services
        self.media_generator = MediaGenerator()
        self.gallery = Gallery(self.db)
        self.video_messages_app = VideoMessagesApp(self.db)
        self.voice_messages_app = VoiceMessagesApp(self.db)
        
        # Initialize voice services (TTS/STT models loaded on demand)
        self.voice_call_handler = VoiceCallHandler(db=self.db, socketio=None)  # socketio set later
        self.voice_message_generator = VoiceMessageGenerator(db=self.db)
        
        # Initialize video services
        self.video_call_handler = VideoCallHandler(
            media_gen=self.media_generator,
            voice_handler=self.voice_call_handler,
            db=self.db,
            socketio=None  # socketio set later
        )
        self.video_message_generator = VideoMessageGenerator(
            media_gen=self.media_generator,
            voice_gen=self.voice_message_generator,
            db=self.db
        )
        
        # Ensure media directory exists
        self.media_dir = Path(__file__).parent.parent.parent / "media"
        self.media_dir.mkdir(exist_ok=True)
        
        # Initialize autonomous messenger (will be started later with socketio)
        self.autonomous_messenger = None

        # Anonymous stranger character
        self.anon_char: Optional[AnonymousCharacter] = None
        try:
            self.anon_char = create_anonymous_character(self.db)
        except Exception as _e:
            print(f"[PhoneScene] Anonymous character init failed: {_e}")
        
        # Flask app
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static")
        )
        self.app.config['SECRET_KEY'] = 'virtual_companion_secret'
        self.app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
        
        # Socket.IO for real-time communication
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", manage_session=False)
        
        # Connect voice and video services to socketio
        self.voice_call_handler.socketio = self.socketio
        self.video_call_handler.socketio = self.socketio
        
        # Active character
        self.active_character: Optional[Character] = None
        
        # Control-panel settings (configurable at runtime)
        self.settings: Dict = {
            "message_timeout": 180,   # seconds for LLM text response
            "audio_timeout":   600,   # seconds for voice generation
            "video_timeout":   600,   # seconds for video generation
            "custom_llm_context": "",  # prepended to system prompt
            "autonomous_frequency": "moderate",
        }
        
        # Active-request tracking for cancel button
        self._cancel_event = threading.Event()
        self._active_request_in_progress = False
        
        # Install ring-buffer logger so the terminal can stream logs
        install_logger()
        
        # Current conversation state
        self.current_chain_id = None
        self.typing_indicator = False
        
        # Setup routes
        self._setup_routes()
        self._setup_socketio()
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            """Phone home screen"""
            return render_template('phone_ui.html')
        
        @self.app.route('/video_call')
        def video_call():
            """Video call screen"""
            return render_template('video_call.html')
        
        @self.app.route('/api/character/set', methods=['POST'])
        def set_character():
            """Set active character"""
            data = request.json
            char_id = data.get('character_id')
            
            if not char_id:
                return jsonify({'error': 'No character_id provided'}), 400
            
            try:
                self.active_character = Character.load(char_id, db=self.db)
                if not self.active_character:
                    return jsonify({'error': 'Character not found'}), 404
                
                # Auto-register character for autonomous messaging
                if self.autonomous_messenger and self.autonomous_messenger.enabled:
                    self.autonomous_messenger.register_character(
                        character_id=char_id,
                        frequency='moderate',
                        time_range=(8, 23),
                        enable_photos=True
                    )
                
                return jsonify({
                    'success': True,
                    'character': {
                        'id': self.active_character.id,
                        'name': self.active_character.name
                    }
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/character/info', methods=['GET'])
        def get_character_info():
            """Get active character info — full payload for the character editor"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            return jsonify(self.active_character.to_dict())
        
        @self.app.route('/api/messages/history', methods=['GET'])
        def get_message_history():
            """Get conversation history"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            limit = request.args.get('limit', 50, type=int)
            chain_id = request.args.get('chain_id')
            
            if chain_id:
                # Get specific conversation chain
                interactions = self.db.get_interaction_chain(chain_id)
            else:
                # Get recent conversations
                conversations = self.active_character.get_conversation_history(limit=10)
                interactions = []
                for conv in conversations:
                    for msg in conv['messages']:
                        interactions.append({
                            'role': msg['role'],
                            'content': msg['content'],
                            'timestamp': msg['timestamp']
                        })
            
            return jsonify({'messages': interactions})
        
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
                
                # Auto-register for autonomous messaging
                if self.autonomous_messenger and self.autonomous_messenger.enabled:
                    self.autonomous_messenger.register_character(
                        character_id=char_id,
                        frequency='moderate',
                        time_range=(8, 23),
                        enable_photos=True
                    )
                
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
        
        @self.app.route('/api/scene/save', methods=['POST'])
        def save_scene_route():
            """Save current scene state"""
            data = request.json
            name = data.get('name')
            
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
                
                # Load first character as active if available
                if self.active_characters:
                    first_char_id = list(self.active_characters.keys())[0]
                    char_asset = self.active_characters[first_char_id]
                    self.active_character = self._asset_to_character(char_asset)
                
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
        
        @self.app.route('/api/autonomous/enable', methods=['POST'])
        def enable_autonomous():
            """Enable autonomous messaging"""
            if not self.autonomous_messenger:
                return jsonify({'error': 'Autonomous messenger not initialized'}), 500
            
            try:
                self.autonomous_messenger.enable()
                return jsonify({'success': True, 'enabled': True})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/autonomous/disable', methods=['POST'])
        def disable_autonomous():
            """Disable autonomous messaging"""
            if not self.autonomous_messenger:
                return jsonify({'error': 'Autonomous messenger not initialized'}), 500
            
            try:
                self.autonomous_messenger.disable()
                return jsonify({'success': True, 'enabled': False})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/autonomous/register', methods=['POST'])
        def register_autonomous():
            """Register character for autonomous messaging"""
            if not self.autonomous_messenger:
                return jsonify({'error': 'Autonomous messenger not initialized'}), 500
            
            data = request.json
            char_id = data.get('character_id')
            frequency = data.get('frequency', 'moderate')
            time_range = data.get('time_range', [8, 23])
            enable_photos = data.get('enable_photos', True)
            
            if not char_id:
                return jsonify({'error': 'No character_id provided'}), 400
            
            try:
                self.autonomous_messenger.register_character(
                    character_id=char_id,
                    frequency=frequency,
                    time_range=tuple(time_range),
                    enable_photos=enable_photos
                )
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/autonomous/unregister', methods=['POST'])
        def unregister_autonomous():
            """Unregister character from autonomous messaging"""
            if not self.autonomous_messenger:
                return jsonify({'error': 'Autonomous messenger not initialized'}), 500
            
            data = request.json
            char_id = data.get('character_id')
            
            if not char_id:
                return jsonify({'error': 'No character_id provided'}), 400
            
            try:
                self.autonomous_messenger.unregister_character(char_id)
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/autonomous/status', methods=['GET'])
        def get_autonomous_status():
            """Get autonomous messenger status"""
            if not self.autonomous_messenger:
                return jsonify({'error': 'Autonomous messenger not initialized'}), 500
            
            try:
                return jsonify({
                    'enabled': self.autonomous_messenger.enabled,
                    'active_characters': list(self.autonomous_messenger.active_characters.keys()),
                    'character_configs': {
                        char_id: {
                            'frequency': config['frequency'],
                            'time_range': config['time_range'],
                            'enable_photos': config['enable_photos']
                        }
                        for char_id, config in self.autonomous_messenger.active_characters.items()
                    }
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/media/upload', methods=['POST'])
        def upload_media():
            """Upload photo from user"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            if 'photo' not in request.files:
                return jsonify({'error': 'No photo provided'}), 400
            
            file = request.files['photo']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            
            # Validate MIME type
            ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
            
            if file.content_type not in ALLOWED_TYPES:
                return jsonify({'error': f'Invalid file type: {file.content_type}. Allowed: JPEG, PNG, GIF, WEBP'}), 400
            
            # Save to temporary location first
            temp_path = self.media_dir / f"temp_{uuid.uuid4().hex[:8]}"
            file.save(str(temp_path))
            
            # Simple size check instead of imghdr (removed in Python 3.13)
            try:
                if temp_path.stat().st_size < 16:
                    temp_path.unlink()
                    return jsonify({'error': 'File too small to be a valid image'}), 400
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink()
                return jsonify({'error': f'File validation failed: {str(e)}'}), 400
            
            # Move to final location with secure filename
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_filename = f"{timestamp}_{filename}"
            filepath = self.media_dir / unique_filename
            
            temp_path.rename(filepath)
            
            # Add to gallery
            try:
                media_id = self.gallery.add_media(
                    character_id=self.active_character.id,
                    filepath=str(filepath),
                    media_type='image',
                    metadata={'source': 'user_upload', 'timestamp': timestamp}
                )
                
                return jsonify({
                    'success': True,
                    'media_id': media_id,
                    'filepath': str(filepath)
                })
            except Exception as e:
                # Clean up on error
                if filepath.exists():
                    filepath.unlink()
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/media/download/<media_id>', methods=['GET'])
        def download_media(media_id):
            """Serve photo file"""
            try:
                media = self.gallery.get_media(media_id)
                if not media:
                    return jsonify({'error': 'Media not found'}), 404
                
                # Validate path is within media directory (prevent path traversal)
                filepath = Path(media['filepath']).resolve()
                media_dir = self.media_dir.resolve()
                
                if not str(filepath).startswith(str(media_dir)):
                    return jsonify({'error': 'Invalid file path'}), 403
                
                if not filepath.exists():
                    return jsonify({'error': 'File not found'}), 404
                
                return send_file(str(filepath), mimetype='image/jpeg')
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/media/gallery', methods=['GET'])
        def get_gallery():
            """Get all photos for active character"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            try:
                media_list = self.gallery.get_character_media(
                    character_id=self.active_character.id,
                    media_type='image',
                    limit=100
                )
                
                # Format for frontend
                photos = [{
                    'id': m['id'],
                    'url': f"/api/media/download/{m['id']}",
                    'timestamp': m['created_at']
                } for m in media_list]
                
                return jsonify({'photos': photos})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/media/generate', methods=['POST'])
        def generate_media():
            """Generate selfie for character — content scales with relationship + arousal."""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            data = request.json or {}
            mood    = data.get('mood', self.active_character.mood)
            setting = data.get('setting', 'casual')
            rel     = float(self.active_character.relationship_level or 0.0)
            arousal = float(getattr(self.active_character, 'arousal', 0.0) or 0.0)
            nsfw_ok = getattr(self.active_character, 'nsfw_enabled', False)

            # Escalate prompt if relationship/arousal warrant it
            extra = data.get('extra_prompt', '')
            nsfw  = False
            if rel > 0.85 and arousal > 0.5 and nsfw_ok:
                nsfw = True
                if not extra:
                    extra = 'seductive pose, revealing outfit, bedroom eyes'
            elif rel > 0.6 and not extra:
                extra = 'flirty expression, attractive pose'
            
            try:
                filepath = self.media_generator.generate_selfie(
                    character_name=self.active_character.name,
                    character_description=self.active_character.appearance or "attractive person",
                    mood=mood,
                    setting=setting,
                    style='realistic',
                    nsfw=nsfw,
                    extra_prompt=extra,
                    chain_id=self.current_chain_id,
                    scene_id='phone',
                    character_id=self.active_character.id,
                )
                
                if not filepath:
                    return jsonify({'error': 'Failed to generate photo'}), 500
                
                # Add to gallery
                media_id = self.gallery.add_media(
                    character_id=self.active_character.id,
                    filepath=filepath,
                    media_type='image',
                    metadata={
                        'source': 'generated',
                        'mood': mood,
                        'setting': setting
                    }
                )
                
                return jsonify({
                    'success': True,
                    'media_id': media_id,
                    'url': f"/api/media/download/{media_id}"
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Voice Call Routes
        @self.app.route('/api/call/start', methods=['POST'])
        def start_call():
            """Start a voice call"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            data = request.json or {}
            call_type = data.get('type', 'outgoing')
            
            try:
                call_id = self.voice_call_handler.start_call(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    call_type=call_type
                )
                
                return jsonify({
                    'success': True,
                    'call_id': call_id,
                    'character': self.active_character.name
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/call/answer', methods=['POST'])
        def answer_call():
            """Answer an incoming call"""
            data = request.json or {}
            call_id = data.get('call_id')
            
            if not call_id:
                return jsonify({'error': 'No call_id provided'}), 400
            
            try:
                success = self.voice_call_handler.answer_call(call_id)
                
                if success:
                    return jsonify({'success': True, 'call_id': call_id})
                else:
                    return jsonify({'error': 'Failed to answer call'}), 500
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/call/end', methods=['POST'])
        def end_call():
            """End the active call"""
            data = request.json or {}
            call_id = data.get('call_id')
            
            try:
                call_info = self.voice_call_handler.end_call(call_id)
                
                if call_info:
                    return jsonify({
                        'success': True,
                        'call_id': call_info['id'],
                        'duration': call_info['duration']
                    })
                else:
                    return jsonify({'error': 'No active call'}), 400
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/call/status', methods=['GET'])
        def get_call_status():
            """Get current call status"""
            try:
                status = self.voice_call_handler.get_call_status()
                return jsonify(status)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/call/history', methods=['GET'])
        def get_call_history():
            """Get call history"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            try:
                limit = request.args.get('limit', 10, type=int)
                history = self.voice_call_handler.get_call_history(
                    character_id=self.active_character.id,
                    limit=limit
                )
                
                return jsonify({'history': history})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Voice Message Routes
        @self.app.route('/api/voice/generate', methods=['POST'])
        def generate_voice_message():
            """Generate a voice message"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            data = request.json or {}
            text = data.get('text')
            emotion = data.get('emotion', 'neutral')
            
            if not text:
                return jsonify({'error': 'No text provided'}), 400
            
            try:
                voice_msg = self.voice_message_generator.generate_voice_message(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    text=text,
                    emotion=emotion
                )
                
                if voice_msg:
                    return jsonify({
                        'success': True,
                        'filepath': voice_msg['filepath'],
                        'filename': voice_msg['filename'],
                        'duration': voice_msg['duration'],
                        'text': voice_msg['text'],
                        'url': f"/api/voice/download/{voice_msg['filename']}"
                    })
                else:
                    return jsonify({'error': 'Failed to generate voice message'}), 500
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/voice/send', methods=['POST'])
        def send_voice_message():
            """Send a voice message in chat"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            data = request.json or {}
            text = data.get('text')
            emotion = data.get('emotion', 'neutral')
            
            if not text:
                return jsonify({'error': 'No text provided'}), 400
            
            try:
                # Generate voice message
                voice_msg = self.voice_message_generator.generate_voice_message(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    text=text,
                    emotion=emotion
                )
                
                if voice_msg:
                    # Emit voice message via SocketIO
                    self.socketio.emit('voice_message_received', {
                        'role': 'assistant',
                        'filename': voice_msg['filename'],
                        'url': f"/api/voice/download/{voice_msg['filename']}",
                        'duration': voice_msg['duration'],
                        'text': voice_msg['text'],
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    return jsonify({'success': True})
                else:
                    return jsonify({'error': 'Failed to generate voice message'}), 500
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/voice/download/<filename>', methods=['GET'])
        def download_voice_message(filename):
            """Download/stream a voice message file"""
            try:
                # Secure the filename
                filename = secure_filename(filename)
                voice_dir = Path(__file__).parent.parent / "media" / "voice"
                filepath = voice_dir / filename
                
                if not filepath.exists():
                    return jsonify({'error': 'File not found'}), 404
                
                return send_file(str(filepath), mimetype='audio/wav')
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/voice/history', methods=['GET'])
        def get_voice_history():
            """Get voice message history"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            try:
                # Query voice messages from database
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT filepath, metadata, timestamp
                        FROM media
                        WHERE character_id = ? AND type = 'voice'
                        ORDER BY timestamp DESC
                        LIMIT 20
                    """, (self.active_character.id,))
                    
                    messages = []
                    for row in cursor.fetchall():
                        filepath = Path(row[0])
                        messages.append({
                            'filename': filepath.name,
                            'url': f"/api/voice/download/{filepath.name}",
                            'metadata': row[1],
                            'timestamp': row[2]
                        })
                    
                    return jsonify({'messages': messages})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Video Call Routes
        @self.app.route('/api/video-call/start', methods=['POST'])
        def start_video_call():
            """Start a video call"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            data = request.json or {}
            call_type = data.get('type', 'outgoing')
            
            try:
                call_id = self.video_call_handler.start_video_call(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    character_description=self.active_character.appearance or "attractive person",
                    call_type=call_type
                )
                
                return jsonify({
                    'success': True,
                    'call_id': call_id,
                    'character': self.active_character.name
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-call/answer', methods=['POST'])
        def answer_video_call():
            """Answer an incoming video call"""
            data = request.json or {}
            call_id = data.get('call_id')
            
            if not call_id:
                return jsonify({'error': 'No call_id provided'}), 400
            
            try:
                success = self.video_call_handler.answer_video_call(call_id)
                
                if success:
                    return jsonify({'success': True, 'call_id': call_id})
                else:
                    return jsonify({'error': 'Failed to answer video call'}), 500
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-call/end', methods=['POST'])
        def end_video_call():
            """End the active video call"""
            data = request.json or {}
            call_id = data.get('call_id')
            
            try:
                call_info = self.video_call_handler.end_video_call(call_id)
                
                if call_info:
                    return jsonify({
                        'success': True,
                        'call_id': call_info['call_id'],
                        'duration': call_info.get('duration', 0)
                    })
                else:
                    return jsonify({'error': 'No active video call'}), 400
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-call/toggle-video', methods=['POST'])
        def toggle_video():
            """Toggle video on/off during call"""
            data = request.json or {}
            enabled = data.get('enabled', True)
            
            try:
                self.video_call_handler.toggle_video(enabled)
                return jsonify({'success': True, 'video_enabled': enabled})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-call/status', methods=['GET'])
        def get_video_call_status():
            """Get current video call status"""
            try:
                status = self.video_call_handler.get_video_call_status()
                return jsonify(status)
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-call/history', methods=['GET'])
        def get_video_call_history():
            """Get video call history"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            try:
                limit = request.args.get('limit', 10, type=int)
                history = self.video_call_handler.get_video_call_history(
                    character_id=self.active_character.id,
                    limit=limit
                )
                
                return jsonify({'history': history})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Video Message Routes
        @self.app.route('/api/video-message/generate', methods=['POST'])
        def generate_video_message():
            """Generate a video message"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            data = request.json or {}
            text = data.get('text')
            mood = data.get('mood', 'happy')
            
            if not text:
                return jsonify({'error': 'No text provided'}), 400
            
            try:
                video_msg = self.video_message_generator.generate_video_message(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    character_description=self.active_character.appearance or "attractive person",
                    text=text,
                    mood=mood
                )
                
                if video_msg:
                    return jsonify({
                        'success': True,
                        'filepath': video_msg['filepath'],
                        'filename': video_msg['filename'],
                        'duration': video_msg['duration'],
                        'text': video_msg['text'],
                        'url': f"/api/video-message/download/{video_msg['filename']}"
                    })
                else:
                    return jsonify({'error': 'Failed to generate video message'}), 500
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-message/send', methods=['POST'])
        def send_video_message():
            """Send a video message in chat"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            data = request.json or {}
            text = data.get('text')
            mood = data.get('mood', 'happy')
            
            if not text:
                return jsonify({'error': 'No text provided'}), 400
            
            try:
                # Generate video message
                video_msg = self.video_message_generator.generate_video_message(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    character_description=self.active_character.appearance or "attractive person",
                    text=text,
                    mood=mood
                )
                
                if video_msg:
                    # Emit video message via SocketIO
                    self.socketio.emit('video_message_received', {
                        'role': 'assistant',
                        'filename': video_msg['filename'],
                        'url': f"/api/video-message/download/{video_msg['filename']}",
                        'duration': video_msg['duration'],
                        'text': video_msg['text'],
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    return jsonify({'success': True})
                else:
                    return jsonify({'error': 'Failed to generate video message'}), 500
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-message/download/<filename>', methods=['GET'])
        def download_video_message(filename):
            """Download/stream a video message file"""
            try:
                # Secure the filename
                filename = secure_filename(filename)
                video_dir = Path(__file__).parent.parent / "media" / "video"
                filepath = video_dir / filename
                
                if not filepath.exists():
                    return jsonify({'error': 'File not found'}), 404
                
                return send_file(str(filepath), mimetype='video/mp4')
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/video-message/history', methods=['GET'])
        def get_video_message_history():
            """Get video message history"""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            
            try:
                # Query video messages from database
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT filepath, metadata, timestamp
                        FROM media
                        WHERE character_id = ? AND type = 'video_message'
                        ORDER BY timestamp DESC
                        LIMIT 20
                    """, (self.active_character.id,))
                    
                    messages = []
                    for row in cursor.fetchall():
                        filepath = Path(row[0])
                        messages.append({
                            'filename': filepath.name,
                            'url': f"/api/video-message/download/{filepath.name}",
                            'metadata': row[1],
                            'timestamp': row[2]
                        })
                    
                    return jsonify({'messages': messages})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        # ── Gallery App List Routes ──────────────────────────────────────────

        @self.app.route('/api/video-messages/list', methods=['GET'])
        def list_video_messages():
            """
            Return structured video message cards for the Video Messages gallery screen.
            Uses VideoMessagesApp which enriches each record with title, duration, etc.
            Query param: limit (int, default 50)
            """
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            limit = request.args.get('limit', 50, type=int)
            cards = self.video_messages_app.get_list(self.active_character.id, limit=limit)
            return jsonify({'messages': cards, 'count': len(cards)})

        @self.app.route('/api/voice-messages/list', methods=['GET'])
        def list_voice_messages():
            """
            Return structured voice message cards for the Voice Messages gallery screen.
            Uses VoiceMessagesApp which enriches each record with title, duration, etc.
            Query param: limit (int, default 50)
            """
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            limit = request.args.get('limit', 50, type=int)
            cards = self.voice_messages_app.get_list(self.active_character.id, limit=limit)
            return jsonify({'messages': cards, 'count': len(cards)})

        # ── Skills API ───────────────────────────────────────────────────────

        @self.app.route('/api/skills/list', methods=['GET'])
        def list_skills():
            """
            List all registered skills (optionally filtered by pack or tag).

            Query params:
                pack  – filter by pack name (e.g. ``comfyui``)
                tag   – filter by tag (e.g. ``image``)
            Returns JSON list of skill dicts with name, pack, description, tags.
            """
            try:
                from engine.skills import SKILL_REGISTRY
                pack = request.args.get('pack')
                tag  = request.args.get('tag')
                tags = [tag] if tag else None
                skills = [
                    {
                        'name':        m.name,
                        'pack':        m.pack,
                        'description': m.description,
                        'tags':        list(m.tags),
                    }
                    for m in SKILL_REGISTRY.all_tools(tags=tags)
                    if (pack is None or m.pack == pack)
                ]
                return jsonify({'skills': skills, 'count': len(skills)})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/skills/run', methods=['POST'])
        def run_skill():
            """
            Execute a registered skill by name with the provided kwargs.

            Request JSON::

                {"skill": "generate_image", "kwargs": {"prompt": "...", "width": 512}}

            Returns ``{"result": <skill return value>}`` or ``{"error": "..."}`` on
            failure.  Skill output is always stringified for transport.
            """
            try:
                from engine.skills import SKILL_REGISTRY
                data    = request.get_json() or {}
                name    = data.get('skill', '')
                kwargs  = data.get('kwargs', {})
                if not name:
                    return jsonify({'error': 'skill name required'}), 400
                meta = SKILL_REGISTRY.get_skill(name)
                if meta is None:
                    return jsonify({'error': f'Unknown skill: {name}'}), 404
                result = meta.func(**kwargs)
                return jsonify({'result': result})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        # ── Anonymous Character Routes ───────────────────────────────────────

        @self.app.route('/api/anon/info', methods=['GET'])
        def anon_info():
            """Return display info for the anonymous character."""
            if not self.anon_char:
                return jsonify({'error': 'Anonymous character not initialized'}), 503
            return jsonify(self.anon_char.get_display_info())

        @self.app.route('/api/anon/message', methods=['POST'])
        def anon_message():
            """Send a message to / receive reply from the anonymous character."""
            if not self.anon_char:
                return jsonify({'error': 'Anonymous character not initialized'}), 503
            data = request.get_json() or {}
            user_msg = data.get('message', '')
            reply = self.anon_char.receive_reply(user_msg) if user_msg else self.anon_char.send_message()
            return jsonify({'reply': reply, 'info': self.anon_char.get_display_info()})

        @self.app.route('/api/anon/history', methods=['GET'])
        def anon_history():
            """Get anonymous character conversation history."""
            if not self.anon_char:
                return jsonify({'error': 'Anonymous character not initialized'}), 503
            return jsonify({'history': self.anon_char.get_conversation_history()})

        # ── Control-Panel API ────────────────────────────────────────────────

        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            """Composite status for the control-panel status tab."""
            llm = get_llm_service()
            llm_ok = False
            llm_model = "unknown"
            try:
                r = http_requests.get(f"{llm.base_url}/models", timeout=3)
                if r.ok:
                    data = r.json()
                    models = [m['id'] for m in data.get('data', [])]
                    llm_ok = True
                    llm_model = llm.model or (models[0] if models else "unknown")
            except Exception:
                pass

            comfy_ok = False
            comfy_progress = 0
            try:
                from content.simulation.services.comfyui_client import ComfyUIClient
                client = ComfyUIClient()
                r2 = http_requests.get(f"{client.base_url}/queue", timeout=3)
                if r2.ok:
                    comfy_ok = True
                    q = r2.json()
                    running = q.get('queue_running', [])
                    comfy_progress = 50 if running else 0
            except Exception:
                pass

            return jsonify({
                'llm': {'ok': llm_ok, 'model': llm_model},
                'comfyui': {'ok': comfy_ok, 'progress': comfy_progress},
                'active_request': self._active_request_in_progress,
            })

        @self.app.route('/api/llm/models', methods=['GET'])
        def list_llm_models():
            """List models available on LM Studio."""
            llm = get_llm_service()
            try:
                r = http_requests.get(f"{llm.base_url}/models", timeout=5)
                if r.ok:
                    models = [m['id'] for m in r.json().get('data', [])]
                    return jsonify({'models': models, 'current': llm.model})
                return jsonify({'models': [], 'current': llm.model})
            except Exception as e:
                return jsonify({'error': str(e), 'models': [], 'current': llm.model}), 500

        @self.app.route('/api/llm/set_model', methods=['POST'])
        def set_llm_model():
            """Switch active LLM model."""
            data = request.get_json() or {}
            model = data.get('model', '')
            if not model:
                return jsonify({'error': 'No model specified'}), 400
            llm = get_llm_service()
            llm.model = model
            return jsonify({'success': True, 'model': model})

        @self.app.route('/api/comfyui/models', methods=['GET'])
        def list_comfyui_models():
            """List models available on ComfyUI."""
            try:
                from content.simulation.services.comfyui_client import ComfyUIClient
                client = ComfyUIClient()
                models = client.get_models()
                return jsonify({'models': models, 'current': client._get_model_name()})
            except Exception as e:
                return jsonify({'error': str(e), 'models': []}), 500

        @self.app.route('/api/comfyui/set_model', methods=['POST'])
        def set_comfyui_model():
            """Override the ComfyUI model to use."""
            data = request.get_json() or {}
            model = data.get('model', '')
            if not model:
                return jsonify({'error': 'No model specified'}), 400
            try:
                from content.simulation.services.comfyui_client import ComfyUIClient
                ComfyUIClient._force_model = model   # class-level override
                return jsonify({'success': True, 'model': model})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/request/cancel', methods=['POST'])
        def cancel_request():
            """Signal the active LLM request (if any) to abort."""
            if self._active_request_in_progress:
                self._cancel_event.set()
                return jsonify({'success': True, 'cancelled': True})
            return jsonify({'success': True, 'cancelled': False, 'note': 'No active request'})

        @self.app.route('/api/settings', methods=['GET', 'POST'])
        def handle_settings():
            """Get or update control-panel settings."""
            if request.method == 'GET':
                return jsonify(self.settings)
            data = request.get_json() or {}
            allowed = {'message_timeout', 'audio_timeout', 'video_timeout',
                       'custom_llm_context', 'autonomous_frequency'}
            for k, v in data.items():
                if k in allowed:
                    self.settings[k] = v
            return jsonify({'success': True, 'settings': self.settings})

        @self.app.route('/api/character/update', methods=['PATCH'])
        def update_character():
            """Update attributes of the active character and persist to DB."""
            if not self.active_character:
                return jsonify({'error': 'No active character'}), 400
            data = request.get_json() or {}
            # Whitelist accepted keys to prevent injection vectors
            ALLOWED = {
                'name', 'age', 'sex', 'hair_color', 'eye_color', 'height', 'body_type',
                'mood', 'energy', 'relationship_level', 'arousal',
                'backstory', 'appearance', 'tags', 'avatar_url',
                'occupation', 'physical_description', 'speech_style',
                'interests', 'quirks', 'fears', 'secrets', 'personality',
            }
            filtered = {k: v for k, v in data.items() if k in ALLOWED}
            if not filtered:
                return jsonify({'success': True, 'message': 'No valid fields provided'})
            try:
                self.active_character.save(**filtered)
            except Exception as e:
                return jsonify({'error': f'Save failed: {e}'}), 500
            return jsonify({'success': True, 'character': self.active_character.to_dict()})

        @self.app.route('/api/logs', methods=['GET'])
        def stream_logs():
            """Return recent log entries for the terminal tab."""
            level    = request.args.get('level', 'ALL')
            limit    = request.args.get('limit', 200, type=int)
            since_id = request.args.get('since_id', 0, type=int)
            return jsonify({'logs': get_logs(level=level, limit=limit, since_id=since_id)})

    def _setup_socketio(self):
        """Setup SocketIO event handlers"""
        
        @self.socketio.on('connect')
        def handle_connect():
            """Handle client connection"""
            emit('connected', {'status': 'Connected to phone scene'})
            print("Client connected to phone scene")
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handle client disconnection"""
            print("Client disconnected from phone scene")
        
        @self.socketio.on('send_message')
        def handle_send_message(data):
            """Handle incoming message from user"""
            if not self.active_character:
                emit('error', {'message': 'No active character'})
                return
            
            message = data.get('message', '')
            
            # Validate input
            if not message:
                emit('error', {'message': 'Empty message'})
                return
            
            if not isinstance(message, str):
                emit('error', {'message': 'Invalid message type'})
                return
            
            # Enforce maximum length (10KB)
            MAX_MESSAGE_LENGTH = 10000
            if len(message) > MAX_MESSAGE_LENGTH:
                emit('error', {'message': f'Message too long (max {MAX_MESSAGE_LENGTH} characters)'})
                return
            
            # Strip leading/trailing whitespace
            message = message.strip()
            if not message:
                emit('error', {'message': 'Empty message after trimming'})
                return
            
            # Start conversation if needed
            if not self.current_chain_id:
                self.current_chain_id = str(uuid.uuid4())
                self.active_character.start_conversation(chain_id=self.current_chain_id)
            
            # Add user message
            self.active_character.add_message('user', message)
            
            # Emit user message
            emit('message_received', {
                'role': 'user',
                'content': message,
                'timestamp': datetime.now().isoformat()
            })
            
            # Show typing indicator
            self.socketio.emit('typing', {'is_typing': True})
            
            # Signal active LLM request to the control panel
            self._cancel_event.clear()
            self._active_request_in_progress = True
            self.socketio.emit('active_request_start', {'type': 'message'})
            
            try:
                # Generate response
                response = self._generate_response(message)
            finally:
                self._active_request_in_progress = False
                self.socketio.emit('active_request_end', {})
            
            # Update mood & relationship based on this exchange
            self._update_mood_and_relationship(message, response)
            
            # Add assistant message
            self.active_character.add_message('assistant', response)
            
            # Hide typing indicator and emit response with updated mood/rel
            self.socketio.emit('typing', {'is_typing': False})
            emit('message_received', {
                'role': 'assistant',
                'content': response,
                'timestamp': datetime.now().isoformat(),
                'mood': getattr(self.active_character, 'mood', 'neutral'),
                'relationship_level': getattr(self.active_character, 'relationship_level', 0.5),
                'arousal': getattr(self.active_character, 'arousal', 0.0),
            })
        
        @self.socketio.on('start_call')
        def handle_start_call(data):
            """Handle voice call initiation"""
            if not self.active_character:
                emit('error', {'message': 'No active character'})
                return
            
            call_type = data.get('type', 'outgoing')
            
            try:
                call_id = self.voice_call_handler.start_call(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    call_type=call_type
                )
                
                # Start call immediately if outgoing
                if call_type == 'outgoing':
                    self.voice_call_handler.answer_call(call_id)
                
                emit('call_started', {
                    'call_id': call_id,
                    'type': call_type,
                    'character': self.active_character.name
                })
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('answer_call')
        def handle_answer_call(data):
            """Handle answering incoming call"""
            call_id = data.get('call_id')
            
            if not call_id:
                emit('error', {'message': 'No call_id provided'})
                return
            
            try:
                success = self.voice_call_handler.answer_call(call_id)
                
                if success:
                    self.socketio.emit('call_answered', {'call_id': call_id})
                else:
                    emit('error', {'message': 'Failed to answer call'})
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('end_call')
        def handle_end_call(data=None):
            """Handle call ending"""
            call_id = data.get('call_id') if data else None
            
            try:
                call_info = self.voice_call_handler.end_call(call_id)
                
                if call_info:
                    emit('call_ended', {
                        'call_id': call_info['id'],
                        'duration': call_info['duration']
                    })
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('call_audio')
        def handle_call_audio(data):
            """Handle audio data from client during call"""
            audio_data = data.get('audio')
            
            if audio_data and self.voice_call_handler.call_active:
                # Pass audio to voice call handler for STT processing
                self.voice_call_handler.receive_audio(audio_data)
        
        @self.socketio.on('send_voice_message')
        def handle_send_voice_message(data):
            """Handle sending voice message in chat"""
            if not self.active_character:
                emit('error', {'message': 'No active character'})
                return
            
            text = data.get('text')
            
            if not text:
                emit('error', {'message': 'No text provided'})
                return
            
            try:
                # Generate voice message
                voice_msg = self.voice_message_generator.generate_voice_message(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    text=text
                )
                
                if voice_msg:
                    emit('voice_message_received', {
                        'role': 'assistant',
                        'filename': voice_msg['filename'],
                        'url': f"/api/voice/download/{voice_msg['filename']}",
                        'duration': voice_msg['duration'],
                        'text': voice_msg['text'],
                        'timestamp': datetime.now().isoformat()
                    })
                else:
                    emit('error', {'message': 'Failed to generate voice message'})
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('send_photo')
        def handle_send_photo(data):
            """Handle photo sharing in chat"""
            if not self.active_character:
                emit('error', {'message': 'No active character'})
                return
            
            media_id = data.get('media_id')
            if not media_id:
                return
            
            # Get media info
            media = self.gallery.get_media(media_id)
            if not media:
                emit('error', {'message': 'Media not found'})
                return
            
            # Emit photo message
            emit('photo_received', {
                'media_id': media_id,
                'url': f"/api/media/download/{media_id}",
                'role': 'user',
                'timestamp': datetime.now().isoformat()
            })
            
            # Log to conversation
            if self.current_chain_id:
                self.active_character.add_message('user', f"[Photo sent: {media_id}]")
        
        @self.socketio.on('request_photo')
        def handle_request_photo():
            """Handle photo request from user"""
            if not self.active_character:
                emit('error', {'message': 'No active character'})
                return
            
            # Get character photos
            media_list = self.gallery.get_character_media(
                character_id=self.active_character.id,
                media_type='image',
                limit=10
            )
            
            if media_list:
                # Send random photo
                media = random.choice(media_list)
                emit('photo_received', {
                    'media_id': media['id'],
                    'url': f"/api/media/download/{media['id']}",
                    'role': 'assistant',
                    'timestamp': datetime.now().isoformat()
                })
                
                # Log to conversation
                if self.current_chain_id:
                    self.active_character.add_message('assistant', f"[Photo sent: {media['id']}]")
            else:
                emit('message_received', {
                    'role': 'assistant',
                    'content': "I don't have any photos to send right now 😅",
                    'timestamp': datetime.now().isoformat()
                })
        
        # Video Call SocketIO Events
        @self.socketio.on('start_video_call')
        def handle_start_video_call(data):
            """Handle video call initiation"""
            if not self.active_character:
                emit('error', {'message': 'No active character'})
                return
            
            call_type = data.get('type', 'outgoing')
            
            try:
                call_id = self.video_call_handler.start_video_call(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    character_description=self.active_character.appearance or "attractive person",
                    call_type=call_type
                )
                
                # Start call immediately if outgoing
                if call_type == 'outgoing':
                    self.video_call_handler.answer_video_call(call_id)
                
                emit('video_call_started', {
                    'call_id': call_id,
                    'type': call_type,
                    'character': self.active_character.name
                })
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('answer_video_call')
        def handle_answer_video_call(data):
            """Handle answering incoming video call"""
            call_id = data.get('call_id')
            
            if not call_id:
                emit('error', {'message': 'No call_id provided'})
                return
            
            try:
                success = self.video_call_handler.answer_video_call(call_id)
                
                if success:
                    self.socketio.emit('video_call_answered', {'call_id': call_id})
                else:
                    emit('error', {'message': 'Failed to answer video call'})
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('end_video_call')
        def handle_end_video_call(data=None):
            """Handle video call ending"""
            call_id = data.get('call_id') if data else None
            
            try:
                call_info = self.video_call_handler.end_video_call(call_id)
                
                if call_info:
                    emit('video_call_ended', {
                        'call_id': call_info['call_id'],
                        'duration': call_info.get('duration', 0)
                    })
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('toggle_video')
        def handle_toggle_video(data):
            """Handle toggling video during call"""
            enabled = data.get('enabled', True)
            
            try:
                self.video_call_handler.toggle_video(enabled)
                self.socketio.emit('video_toggled', {'enabled': enabled})
            except Exception as e:
                emit('error', {'message': str(e)})
        
        @self.socketio.on('send_video_message')
        def handle_send_video_message(data):
            """Handle sending video message in chat"""
            if not self.active_character:
                emit('error', {'message': 'No active character'})
                return
            
            text = data.get('text')
            mood = data.get('mood', 'happy')
            
            if not text:
                emit('error', {'message': 'No text provided'})
                return
            
            try:
                # Generate video message
                video_msg = self.video_message_generator.generate_video_message(
                    character_id=self.active_character.id,
                    character_name=self.active_character.name,
                    character_description=self.active_character.appearance or "attractive person",
                    text=text,
                    mood=mood
                )
                
                if video_msg:
                    emit('video_message_received', {
                        'role': 'assistant',
                        'filename': video_msg['filename'],
                        'url': f"/api/video-message/download/{video_msg['filename']}",
                        'duration': video_msg['duration'],
                        'text': video_msg['text'],
                        'timestamp': datetime.now().isoformat()
                    })
                else:
                    emit('error', {'message': 'Failed to generate video message'})
            except Exception as e:
                emit('error', {'message': str(e)})
    
    def _generate_response(self, user_message: str) -> str:
        """
        Generate character response via LM Studio LLM.
        Parses intent and may trigger spontaneous media sends.
        """
        if not self.active_character:
            return "Error: No active character"

        llm = get_llm_service()

        # Build conversation history from recent messages
        history = []
        try:
            conv_history = self.active_character.get_conversation_history(limit=10)
            for conv in conv_history:
                if isinstance(conv, dict):
                    for turn in conv.get("messages", []):
                        if isinstance(turn, dict):
                            role = turn.get("role", "user")
                            content = turn.get("content", "")
                            if role and content:
                                history.append({"role": role, "content": content})
        except Exception:
            history = []

        # Generate LLM response
        # Apply timeout and custom context from control-panel settings
        original_timeout = llm.timeout
        llm.timeout = self.settings.get('message_timeout', 180)
        
        # Build system prompt directly so we can inject custom context
        try:
            system_prompt = self.active_character.get_system_prompt()
        except Exception:
            system_prompt = f"You are {self.active_character.name}, a virtual companion. Be warm and stay in character."
        
        try:
            memory_context = self.active_character.build_context(user_message)
            if memory_context:
                system_prompt += f"\n\n## Relevant Memories\n{memory_context}"
        except Exception:
            pass
        
        custom_ctx = self.settings.get('custom_llm_context', '').strip()
        if custom_ctx:
            system_prompt += f"\n\n## Operator Context\n{custom_ctx}"
        
        # Check for cancel before the (potentially slow) API call
        if self._cancel_event.is_set():
            llm.timeout = original_timeout
            return "(Request cancelled)"
        
        try:
            response = llm.chat(
                messages=history + [{"role": "user", "content": user_message}],
                system_prompt=system_prompt,
            ) or llm._character_fallback(self.active_character, user_message)
        finally:
            llm.timeout = original_timeout
        
        if self._cancel_event.is_set():
            return "(Request cancelled)"

        # Parse intent to decide if media should be triggered
        try:
            intent = llm.parse_intent(user_message)
        except Exception:
            intent = {}

        rel = float(self.active_character.relationship_level)
        arousal = float(getattr(self.active_character, 'arousal', 0.0) or 0.0)

        # User explicitly asked for a selfie
        if intent.get("wants_selfie") and rel > 0.2:
            self._maybe_send_photo()

        # User asked for a voice message
        if intent.get("wants_voice") and rel > 0.3:
            self._maybe_send_voice_message(response)

        # User asked for a video message
        if intent.get("wants_video") and rel > 0.4:
            self._maybe_send_video_message(response)

        # Spontaneous media — probability scales with relationship + arousal
        if not any(intent.values()):
            # Base chance: 5% at rel 0.5 → 25% at rel 1.0 + arousal boost
            base_chance = max(0, (rel - 0.3) * 0.35) + arousal * 0.10
            r = random.random()
            if r < base_chance * 0.5:      # photo most common
                self._maybe_send_photo()
            elif r < base_chance * 0.7:    # voice message
                self._maybe_send_voice_message(response)
            elif r < base_chance * 0.85:   # video message
                self._maybe_send_video_message(response)

        return response

    # ── Dynamic Mood, Relationship & Arousal Engine ───────────
    # Called after every assistant reply to nudge mood, relationship,
    # and arousal based on keyword sentiment heuristics.

    _POSITIVE_WORDS = frozenset([
        'love', 'happy', 'great', 'amazing', 'wonderful', 'thank', 'thanks',
        'awesome', 'beautiful', 'sweet', 'kind', 'funny', 'cute', 'miss',
        'haha', 'lol', 'yes', 'cool', 'nice', 'good', 'perfect', 'best',
        'appreciate', 'care', 'adore', 'excited', 'joy', 'hug', 'kiss',
    ])
    _NEGATIVE_WORDS = frozenset([
        'hate', 'angry', 'annoyed', 'stupid', 'ugly', 'boring', 'leave',
        'shut', 'stop', 'no', 'bad', 'worst', 'wrong', 'rude', 'mean',
        'ignore', 'upset', 'cry', 'sad', 'tired', 'whatever', 'ugh',
    ])
    _FLIRTY_WORDS = frozenset([
        'sexy', 'hot', 'gorgeous', 'stunning', 'flirt', 'tease', 'naughty',
        'kiss', 'lips', 'touch', 'skin', 'bed', 'cuddle', 'close',
        'desire', 'want', 'need', 'body', 'curves', 'eyes', 'smile',
        'seduce', 'tempt', 'attract', 'blush', 'whisper', 'breathe',
        'tight', 'soft', 'warm', 'wet', 'moan', 'bite', 'neck', 'thigh',
        'strip', 'undress', 'lingerie', 'naked', 'nude', 'bare',
        'pleasure', 'fantasy', 'dream', 'imagine', 'tonight', 'alone',
        'bedroom', 'shower', 'bath', 'daddy', 'baby', 'babe', 'darling',
        'handsome', 'pretty', 'adorable', 'irresistible', 'delicious',
    ])

    def _update_mood_and_relationship(self, user_message: str, response: str):
        """Nudge mood, relationship level, and arousal based on conversation."""
        if not self.active_character:
            return
        try:
            combined = (user_message + ' ' + response).lower()
            words = set(combined.split())
            pos   = len(words & self._POSITIVE_WORDS)
            neg   = len(words & self._NEGATIVE_WORDS)
            flirt = len(words & self._FLIRTY_WORDS)

            rel = float(self.active_character.relationship_level or 0.5)
            arousal = float(getattr(self.active_character, 'arousal', 0.0) or 0.0)
            flirtiness = float(getattr(self.active_character, 'flirtiness', 0.5) or 0.5)

            # ── Arousal ──────────────────────────────────────
            arousal_delta = 0.0
            if flirt > 0:
                arousal_delta = min(0.04 * flirt, 0.15)  # flirty words heat things up
            if pos > neg and flirt == 0:
                arousal_delta = 0.01                       # warm convo — slight
            if neg > pos + 1:
                arousal_delta = -0.05                      # negativity cools down
            # Natural decay towards 0
            if arousal_delta == 0:
                arousal_delta = -0.02
            arousal = max(0.0, min(1.0, arousal + arousal_delta))

            # ── Mood ─────────────────────────────────────────
            if flirt >= 3 and arousal > 0.6:
                new_mood = random.choice(['aroused', 'seductive', 'passionate'])
            elif flirt >= 2 or arousal > 0.4:
                new_mood = random.choice(['flirty', 'teasing', 'playful'])
            elif pos > neg + 2:
                new_mood = random.choice(['happy', 'excited', 'playful', 'loving'])
            elif neg > pos + 2:
                new_mood = random.choice(['sad', 'angry', 'anxious'])
            elif pos > neg:
                new_mood = random.choice(['happy', 'loving', 'playful'])
            elif neg > pos:
                new_mood = random.choice(['sad', 'bored'])
            else:
                new_mood = 'neutral'

            self.active_character.mood = new_mood

            # ── Relationship ─────────────────────────────────
            delta = 0.0
            if pos > neg:
                delta = min(0.02 * (pos - neg), 0.06)
            elif neg > pos:
                delta = max(-0.02 * (neg - pos), -0.04)
            if flirt > 0:
                delta += 0.01 * flirt       # flirting always builds closeness
            if delta == 0:
                delta = -0.005 if rel > 0.5 else 0.005 if rel < 0.5 else 0
            rel = max(0.0, min(1.0, rel + delta))
            self.active_character.relationship_level = rel

            # ── Flirtiness (character trait drift) ───────────
            if flirt > 1:
                flirtiness = min(1.0, flirtiness + 0.02)
            elif neg > pos:
                flirtiness = max(0.0, flirtiness - 0.01)

            # ── Persist to DB ────────────────────────────────
            self.db.update_character_state(
                self.active_character.id,
                mood=new_mood,
                relationship_level=rel,
                arousal=arousal,
                flirtiness=flirtiness,
            )
        except Exception as e:
            print(f"[mood/rel/arousal] update error: {e}")
    
    def _maybe_send_voice_message(self, text: str):
        """Character may spontaneously send a voice message"""
        try:
            voice_msg = self.voice_message_generator.generate_voice_message(
                character_id=self.active_character.id,
                character_name=self.active_character.name,
                text=text
            )
            
            if voice_msg:
                self.socketio.emit('voice_message_received', {
                    'role': 'assistant',
                    'filename': voice_msg['filename'],
                    'url': f"/api/voice/download/{voice_msg['filename']}",
                    'duration': voice_msg['duration'],
                    'text': voice_msg['text'],
                    'timestamp': datetime.now().isoformat()
                })
                
                # Log to conversation
                if self.current_chain_id:
                    self.active_character.add_message('assistant', f"[Voice message: {text}]")
        except Exception as e:
            print(f"Error sending voice message: {e}")
    
    def _maybe_send_photo(self):
        """
        Character spontaneously sends a photo.
        Content escalates with relationship level and arousal:
          rel < 0.4  → cute / casual selfie
          rel 0.4–0.7 → flirty selfie (bedroom, gym, mirror)
          rel > 0.7  → intimate selfie (lingerie, suggestive poses)
          rel > 0.85 AND arousal > 0.5 → NSFW selfie
        Falls back to existing gallery photos when ComfyUI is offline.
        """
        try:
            rel     = float(self.active_character.relationship_level or 0.0)
            arousal = float(getattr(self.active_character, 'arousal', 0.0) or 0.0)
            mood    = self.active_character.mood or 'happy'
            name    = self.active_character.name
            desc    = self.active_character.get_visual_description()
            nsfw_ok = getattr(self.active_character, 'nsfw_enabled', False)

            # ── Decide selfie tier ──────────────────────────
            if rel > 0.85 and arousal > 0.5 and nsfw_ok:
                # Intimate / NSFW tier
                tier_mood    = random.choice(['seductive', 'aroused', 'passionate', 'teasing'])
                tier_setting = random.choice(['bedroom', 'lingerie', 'bath', 'mirror selfie'])
                tier_extra   = random.choice([
                    'revealing lingerie, dim lighting, inviting pose',
                    'sheer fabric, soft focus, bedroom eyes',
                    'topless, covering with hands, biting lip',
                    'in bed under sheets, bare shoulders, messy hair',
                ])
                tier_nsfw    = True
                caption      = random.choice([
                    f"Thinking of you... 🔥",
                    f"Wish you were here right now 💋",
                    f"Just for your eyes 😈",
                    f"Can't sleep... want some company? 🥵",
                    f"Do you like what you see? 💦",
                ])
            elif rel > 0.7 or arousal > 0.4:
                # Flirty / suggestive tier
                tier_mood    = random.choice(['flirty', 'teasing', 'confident', 'playful'])
                tier_setting = random.choice(['bedroom', 'mirror selfie', 'gym', 'cozy night'])
                tier_extra   = random.choice([
                    'tight outfit, showing curves, playful wink',
                    'low-cut top, candlelight, smiling seductively',
                    'crop top, mirror selfie, confident pose',
                    'oversized shirt, no pants, lounging on bed',
                ])
                tier_nsfw    = False
                caption      = random.choice([
                    f"Like my outfit? 😘",
                    f"Felt cute, might delete later 💕",
                    f"This is what you're missing tonight 😏",
                    f"Just got out of the shower... 🫣",
                    f"Rate me? 💋",
                ])
            elif rel > 0.4:
                # Warm / cute tier
                tier_mood    = random.choice(['happy', 'playful', 'shy', 'loving'])
                tier_setting = random.choice(['casual', 'outdoors', 'cafe', 'sunset'])
                tier_extra   = 'cute selfie, natural lighting, warm smile'
                tier_nsfw    = False
                caption      = random.choice([
                    f"Hey you 😊",
                    f"Having a good day! Thought of you 💭",
                    f"Miss your face 🥰",
                    f"Selfie time! 📸",
                ])
            else:
                # Casual tier — barely know each other
                tier_mood    = random.choice(['happy', 'neutral', 'curious'])
                tier_setting = random.choice(['casual', 'outdoors', 'cafe'])
                tier_extra   = 'casual selfie, friendly smile'
                tier_nsfw    = False
                caption      = random.choice([
                    f"Hey! 👋",
                    f"Hope you're having a good day 😊",
                ])

            # ── Try generating a fresh selfie ────────────────
            filepath = None
            try:
                filepath = self.media_generator.generate_selfie(
                    character_name=name,
                    character_description=desc,
                    mood=tier_mood,
                    setting=tier_setting,
                    nsfw=tier_nsfw,
                    extra_prompt=tier_extra,
                    chain_id=self.current_chain_id,
                    scene_id='phone',
                    character_id=self.active_character.id,
                )
            except Exception:
                pass

            if filepath:
                media_id = self.gallery.add_media(
                    character_id=self.active_character.id,
                    filepath=filepath,
                    media_type='image',
                    metadata={'source': 'generated', 'mood': tier_mood,
                              'setting': tier_setting, 'nsfw': tier_nsfw},
                )
                url = f"/api/media/download/{media_id}"
            else:
                # Fallback: pick a random existing photo
                media_list = self.gallery.get_character_media(
                    character_id=self.active_character.id,
                    media_type='image', limit=20,
                )
                if not media_list:
                    return
                media = random.choice(media_list)
                url = f"/api/media/download/{media['id']}"

            # ── Send photo with caption ──────────────────────
            self.socketio.emit('photo_received', {
                'url': url,
                'role': 'assistant',
                'timestamp': datetime.now().isoformat(),
                'caption': caption,
            })
            if self.current_chain_id:
                self.active_character.add_message('assistant', f"[Photo sent] {caption}")
        except Exception as e:
            print(f"Error sending photo: {e}")
    
    def _maybe_send_video_message(self, text: str):
        """Character may spontaneously send a video message"""
        try:
            video_msg = self.video_message_generator.generate_video_message(
                character_id=self.active_character.id,
                character_name=self.active_character.name,
                character_description=self.active_character.appearance or "attractive person",
                text=text,
                mood=self.active_character.mood or "happy"
            )
            
            if video_msg:
                self.socketio.emit('video_message_received', {
                    'role': 'assistant',
                    'filename': video_msg['filename'],
                    'url': f"/api/video-message/download/{video_msg['filename']}",
                    'duration': video_msg['duration'],
                    'text': video_msg['text'],
                    'timestamp': datetime.now().isoformat()
                })
                
                # Log to conversation
                if self.current_chain_id:
                    self.active_character.add_message('assistant', f"[Video message: {text}]")
        except Exception as e:
            print(f"Error sending video message: {e}")
    
    def set_character(self, character_id: str):
        """Set active character (legacy database method)"""
        self.active_character = Character.load(character_id, db=self.db)
    
    # _asset_to_character() inherited from BaseScene

    def get_plugin_info(self) -> dict:
        """
        Return metadata describing this scene to the admin panel and launcher.

        Implements the :meth:`BaseScene.get_plugin_info` abstract contract.
        """
        return {
            "name":        "Phone Scene",
            "description": "Android-style phone interface — messages, calls, media gallery, apps",
            "version":     "2.0.0",
            "author":      "CosySim",
            "port":        self.port,
            "tags":        ["phone", "character", "chat", "media", "voice", "video"],
            "skill_packs": ["memory", "voice", "comfyui", "character"],
            "routes": [
                {"path": "/",                         "methods": ["GET"],  "description": "Phone UI"},
                {"path": "/api/chat",                 "methods": ["POST"], "description": "Chat with character"},
                {"path": "/api/gallery/list",         "methods": ["GET"],  "description": "Image gallery"},
                {"path": "/api/video-messages/list",  "methods": ["GET"],  "description": "Video message gallery"},
                {"path": "/api/voice-messages/list",  "methods": ["GET"],  "description": "Voice message gallery"},
                {"path": "/api/skills/list",          "methods": ["GET"],  "description": "List registered skills"},
                {"path": "/api/skills/run",           "methods": ["POST"], "description": "Execute a skill by name"},
                {"path": "/api/status",               "methods": ["GET"],  "description": "Scene health / status"},
            ],
        }

    def start(self) -> None:
        """Start the phone scene (Flask + SocketIO server)"""
        self.run(debug=False)
    
    def stop(self) -> None:
        """Stop the phone scene and cleanup"""
        if self.autonomous_messenger:
            self.autonomous_messenger.disable()
        print("🛑 Phone Scene stopped")
    
    def run(self, debug: bool = False):
        """Run the phone scene server"""
        print(f"🎮 Starting Phone Scene on {self.host}:{self.port}")
        if self.active_character:
            print(f"📱 Active Character: {self.active_character.name}")
        else:
            print("⚠️  No active character set")
        
        # Initialize and enable autonomous messenger after socketio is ready
        self.autonomous_messenger = AutonomousMessenger(self.db, self.socketio)
        self.autonomous_messenger.enable()
        print("🤖 Autonomous messaging enabled")
        
        # If there's an active character, register them
        if self.active_character:
            self.autonomous_messenger.register_character(
                character_id=self.active_character.id,
                frequency='moderate',
                time_range=(8, 23),
                enable_photos=True
            )
        
        self.socketio.run(self.app, host=self.host, port=self.port, debug=debug)


def create_phone_scene(character_id: Optional[str] = None, **kwargs) -> PhoneScene:
    """Factory function to create phone scene"""
    scene = PhoneScene(**kwargs)
    
    if character_id:
        scene.set_character(character_id)
    
    return scene


if __name__ == "__main__":
    # Test mode
    print("Phone Scene - Test Mode")
    
    # Create test character if needed
    db = Database()
    characters = db.get_all_characters()
    
    if not characters:
        print("No characters found. Create one first using dashboard.")
        exit(1)
    
    # Use first character
    char_id = characters[0]['id']
    print(f"Using character: {characters[0]['name']}")
    
    # Create and run phone scene
    scene = create_phone_scene(character_id=char_id, port=5555)
    scene.run(debug=True)
