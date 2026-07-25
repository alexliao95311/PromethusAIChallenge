#!/usr/bin/env python3
"""
Google Cloud Text-to-Speech Service for DebateSim
Uses existing credentials from credentials/debatesim-6f403-55fd99aa753a-google-cloud.json
"""

import os
import json
import base64
from typing import Dict, List, Optional
try:
    from google.cloud import texttospeech
except ImportError:
    texttospeech = None  # google-cloud-texttospeech not installed -- GoogleTTSService
    # methods using it will raise clearly when called, but importing this module still succeeds.
from google.oauth2 import service_account

class GoogleTTSService:
    def __init__(self):
        """Initialize Google TTS service with existing credentials"""
        # Path to credentials from speech_utils folder (go up one level to root)
        self.credentials_path = os.path.join(os.path.dirname(__file__), "..", "credentials", "debatesim-6f403-55fd99aa753a-google-cloud.json")
        self.client = None
        self.voices = [
            # Chirp3 voices - latest high-quality models
            {
                "name": "en-US-Chirp3-HD-Achernar",
                "language": "en-US",
                "gender": "FEMALE",
                "description": "High-quality Chirp3 voice - Achernar ⭐"
            },
            # Neural2 voices - previous generation
            {
                "name": "en-US-Neural2-A",
                "language": "en-US",
                "gender": "MALE",
                "description": "Natural male voice (Neural2) - 👨"
            },
            {
                "name": "en-US-Neural2-C",
                "language": "en-US",
                "gender": "FEMALE",
                "description": "Natural female voice (Neural2) - 👩"
            },
            {
                "name": "en-US-Neural2-D",
                "language": "en-US",
                "gender": "MALE",
                "description": "Natural male voice (Neural2) - 👨"
            },
            {
                "name": "en-US-Neural2-E",
                "language": "en-US",
                "gender": "FEMALE",
                "description": "Natural female voice (Neural2) - 👩"
            },
            {
                "name": "en-US-Neural2-F",
                "language": "en-US",
                "gender": "FEMALE",
                "description": "Natural female voice (Neural2) - 👩"
            },
            {
                "name": "en-US-Neural2-G",
                "language": "en-US",
                "gender": "FEMALE",
                "description": "Natural female voice (Neural2) - 👩"
            },
            {
                "name": "en-US-Neural2-H",
                "language": "en-US",
                "gender": "FEMALE",
                "description": "Natural female voice (Neural2) - 👩"
            },
            {
                "name": "en-US-Neural2-I",
                "language": "en-US",
                "gender": "MALE",
                "description": "Natural male voice (Neural2) - 👨"
            },
            {
                "name": "en-US-Neural2-J",
                "language": "en-US",
                "gender": "MALE",
                "description": "Natural male voice (Neural2) - 👨"
            }
        ]
        
        self.default_voice = "en-US-Chirp3-HD-Achernar"
        self._initialize_client()

    def _initialize_client(self):
        """Initialize Google Cloud TTS client with credentials"""
        try:
            # Convert to absolute path
            abs_credentials_path = os.path.abspath(self.credentials_path)
            
            if os.path.exists(abs_credentials_path):
                # Set environment variable for Google Cloud credentials
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_credentials_path
                
                # Create client
                self.client = texttospeech.TextToSpeechClient()
                print(f"✅ Google TTS client initialized successfully with credentials: {abs_credentials_path}")
            else:
                print(f"❌ Credentials file not found: {abs_credentials_path}")
                print(f"   Expected location: {abs_credentials_path}")
                print(f"   Current working directory: {os.getcwd()}")
                self.client = None
        except Exception as e:
            print(f"❌ Failed to initialize Google TTS client: {e}")
            self.client = None

    def get_available_voices(self) -> List[Dict]:
        """Get list of available voices"""
        return self.voices

    def get_default_voice(self) -> str:
        """Get default voice name"""
        return self.default_voice

    def synthesize_speech(self, text: str, voice_name: str = None, 
                         rate: float = 1.0, pitch: float = 0.0, 
                         volume: float = 1.0) -> Optional[str]:
        """
        Synthesize speech using Google Cloud TTS
        
        Args:
            text: Text to synthesize
            voice_name: Voice to use (defaults to default_voice)
            rate: Speaking rate (0.25 to 4.0)
            pitch: Pitch adjustment (-20.0 to 20.0)
            volume: Volume gain in dB (-96.0 to 16.0)
            
        Returns:
            Base64 encoded audio content or None if failed
        """
        if not self.client:
            print("❌ Google TTS client not initialized")
            return None

        if not voice_name:
            voice_name = self.default_voice

        try:
            # Set the text input to be synthesized
            synthesis_input = texttospeech.SynthesisInput(text=text)

            # Find the voice info to get the correct gender
            voice_info = next((v for v in self.voices if v["name"] == voice_name), None)
            if not voice_info:
                print(f"❌ Voice not found: {voice_name}")
                return None

            # Build the voice request with proper gender
            voice = texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name=voice_name,
                ssml_gender=texttospeech.SsmlVoiceGender.FEMALE if voice_info["gender"] == "FEMALE" else texttospeech.SsmlVoiceGender.MALE
            )

            # Select the type of audio file to return
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=rate,
                pitch=pitch,
                volume_gain_db=volume if volume > 0 else -96,
                effects_profile_id=["headphone-class-device"]
            )

            # Perform the text-to-speech request
            response = self.client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )

            # Return base64 encoded audio
            audio_b64 = base64.b64encode(response.audio_content).decode('utf-8')
            print(f"✅ Successfully synthesized speech for text: '{text[:50]}...' using voice: {voice_name}")
            return audio_b64

        except Exception as e:
            print(f"❌ Failed to synthesize speech: {e}")
            return None

    def test_connection(self) -> bool:
        """Test if Google TTS service is working"""
        if not self.client:
            return False
        
        try:
            test_text = "Hello, this is a test of Google Text-to-Speech."
            result = self.synthesize_speech(test_text)
            return result is not None
        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False

def main():
    """Test the Google TTS service"""
    print("🎤 Testing Google Cloud Text-to-Speech Service")
    print("=" * 50)
    
    # Initialize service
    tts_service = GoogleTTSService()
    
    if not tts_service.client:
        print("❌ Service initialization failed")
        return
    
    # Test connection
    print("\n🔍 Testing connection...")
    if tts_service.test_connection():
        print("✅ Connection test successful!")
    else:
        print("❌ Connection test failed!")
        return
    
    # Show available voices
    print("\n🎭 Available voices:")
    voices = tts_service.get_available_voices()
    for voice in voices:
        gender_emoji = "👩" if voice["gender"] == "FEMALE" else "👨"
        print(f"  {gender_emoji} {voice['name']} - {voice['description']}")
    
    # Test synthesis
    print("\n🎵 Testing speech synthesis...")
    test_texts = [
        "Welcome to DebateSim! This is a test of the enhanced text-to-speech system.",
        "The quality of these voices is significantly better than standard browser TTS.",
        "You can now choose from multiple natural-sounding voices for your debates."
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n  Test {i}: {text}")
        result = tts_service.synthesize_speech(text, voice_name="en-US-Neural2-A")
        if result:
            print(f"    ✅ Success! Audio length: {len(result)} characters")
        else:
            print(f"    ❌ Failed!")
    
    print("\n🎉 Google TTS service test completed!")

if __name__ == "__main__":
    main()
