#!/usr/bin/env python3
import tkinter as tk
from tkinter import scrolledtext
import base64
import os
import json
import threading
import argparse
import sys
import io
import time
import re
import tempfile
import wave
import pyaudio
import openai
import pygame

from dotenv import load_dotenv
import pyautogui
import boto3
from botocore.exceptions import NoCredentialsError

# Import our modular components
from model_manager import get_model_manager
from visual_utils import VisualManager
from qt_overlay import create_overlay

# Initialize GUI safety (for PyAutoGUI)
pyautogui.FAILSAFE = True  # Move mouse to upper-left corner to abort

# Load environment variables
load_dotenv()

# Initialize OpenAI API
openai.api_key = os.getenv("OPENAI_API_KEY")

# Speech-to-text and text-to-speech functions
def record_audio(seconds=5):
    """
    Record audio for a specified number of seconds
    Returns the audio as a bytes object
    """
    chunk = 1024
    sample_format = pyaudio.paInt16
    channels = 1
    fs = 44100  # Sample rate
    
    p = pyaudio.PyAudio()
    
    print("Recording...")
    
    stream = p.open(format=sample_format,
                    channels=channels,
                    rate=fs,
                    frames_per_buffer=chunk,
                    input=True)
    
    frames = []
    
    # Record for the specified duration
    for i in range(0, int(fs / chunk * seconds)):
        data = stream.read(chunk)
        frames.append(data)
    
    # Stop and close the stream
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    print("Recording complete.")
    
    # Save to a temporary WAV file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    wf = wave.open(temp_file.name, 'wb')
    wf.setnchannels(channels)
    wf.setsampwidth(p.get_sample_size(sample_format))
    wf.setframerate(fs)
    wf.writeframes(b''.join(frames))
    wf.close()
    
    return temp_file.name

def speech_to_text(audio_file_path):
    """
    Convert speech to text using OpenAI's API
    Returns the transcribed text
    """
    try:
        with open(audio_file_path, "rb") as audio_file:
            transcription = openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        return transcription.text
    except Exception as e:
        print(f"Error in speech to text: {e}")
        return None
    finally:
        # Clean up the temporary file
        if os.path.exists(audio_file_path):
            os.unlink(audio_file_path)

def text_to_speech(text, voice="alloy"):
    """
    Convert text to speech using OpenAI's API
    Voice options: alloy, echo, fable, onyx, nova, shimmer
    Returns the path to the generated audio file
    """
    try:
        response = openai.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )
        
        # Save to a temporary MP3 file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        response.stream_to_file(temp_file.name)
        
        return temp_file.name
    except Exception as e:
        print(f"Error in text to speech: {e}")
        return None

def play_audio(file_path):
    """
    Play an audio file using pygame
    """
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        pygame.mixer.quit()
    except Exception as e:
        print(f"Error playing audio: {e}")
    finally:
        # Clean up the temporary file
        if os.path.exists(file_path):
            os.unlink(file_path)

class ConversationManager:
    """
    Manages conversation context, educational content, and intent recognition.
    Helps provide appropriate responses for users with limited computer knowledge.
    """
    def __init__(self):
        # Conversation history
        self.conversation_history = []
        
        # Map of question types and intents
        self.intent_keywords = {
            "how_to": ["how do i", "how to", "how can i", "steps to", "guide for"],
            "what_is": ["what is", "what are", "explain", "meaning of", "definition of"],
            "where_is": ["where is", "find", "locate", "show me", "position of"],
            "when_to": ["when should i", "when to", "best time to"],
            "why_use": ["why should i", "why use", "purpose of", "benefit of"]
        }
        
        # Map of common UI elements and descriptions for education
        self.ui_elements = {
            "dock": "The Dock is a bar of icons at the bottom of your Mac screen that gives you quick access to frequently used apps and documents.",
            "menu bar": "The Menu Bar at the top of your screen contains menus like File, Edit, and View, plus status icons on the right.",
            "finder": "Finder is a file management application that helps you navigate and organize files on your Mac.",
            "spotlight": "Spotlight is a quick search feature on Mac that helps you find apps, documents, and information.",
            "mail": "Mail is the default email application on your Mac that helps you send, receive and manage emails.",
            "safari": "Safari is the default web browser on your Mac that lets you access the internet and browse websites.",
            "system preferences": "System Preferences lets you customize settings on your Mac, like display, sound, and user accounts.",
            "desktop": "The Desktop is the main screen you see when your Mac is running, where you can store files and access applications.",
            "folder": "Folders help you organize and store files on your computer.",
            "window": "Windows are rectangular areas on your screen that display apps, documents, or other content.",
            "button": "Buttons are interactive elements you can click to perform actions.",
            "icon": "Icons are small images that represent applications, files, or functions on your computer."
        }
        
        # Always apply visual cues flag
        self.always_visual = True
        
    def add_message(self, role, content):
        """Add a message to the conversation history"""
        self.conversation_history.append({"role": role, "content": content})
        
    def get_last_messages(self, count=5):
        """Get the last n messages from conversation history"""
        return self.conversation_history[-count:] if len(self.conversation_history) >= count else self.conversation_history
        
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []
    
    def set_always_visual(self, value):
        """Set whether to always apply visual cues"""
        self.always_visual = value
        
    def detect_intent(self, user_query):
        """
        Detect the user's intent based on their query
        Returns intent type and whether visual guidance is likely needed
        """
        user_query = user_query.lower()
        
        # Detect primary intent
        detected_intent = "general"
        for intent, keywords in self.intent_keywords.items():
            if any(keyword in user_query for keyword in keywords):
                detected_intent = intent
                break
        
        # Determine if visual guidance is needed
        needs_visual = True  # Always set to True to apply visual cues for all queries
        
        # Check for specific UI elements mentioned
        mentioned_elements = []
        for element in self.ui_elements.keys():
            if element in user_query.lower():
                mentioned_elements.append(element)
        
        return {
            "primary_intent": detected_intent,
            "needs_visual": needs_visual,
            "mentioned_elements": mentioned_elements
        }
    
    def create_educational_response(self, intent_data, ai_response):
        """
        Enhance the AI response with educational content based on intent
        """
        enhanced_response = ai_response
        
        # Add educational content about UI elements mentioned
        if intent_data["mentioned_elements"]:
            educational_info = []
            for element in intent_data["mentioned_elements"]:
                if element in self.ui_elements:
                    educational_info.append(f"**{element.title()}**: {self.ui_elements[element]}")
            
            if educational_info:
                enhanced_response += "\n\n📚 Learn More:\n" + "\n".join(educational_info)
        
        # For "what_is" questions, add more background when relevant
        if intent_data["primary_intent"] == "what_is":
            # Add general computer literacy information if no specific elements mentioned
            if not intent_data["mentioned_elements"]:
                enhanced_response += "\n\nI hope that helps explain it clearly! Feel free to ask if you have any other questions."
        
        # Add visual guidance encouragement for all responses
        enhanced_response += "\n\nI've highlighted elements on your screen to help you visualize what I'm explaining. This should make it easier to follow along!"
            
        return enhanced_response

class ScreenshotAnalyzerApp:
    def __init__(self, root=None, use_qt_overlay=True):
        """
        Initialize the desktop automation app
        
        Args:
            root: Optional Tkinter root window
            use_qt_overlay: Whether to use the Qt-based overlay (recommended for macOS)
        """
        # Create Tkinter root if not provided
        self.root = root if root else tk.Tk()
        self.root.title("AI Desktop Assistant")
        # Start slightly smaller, let packing handle resizing
        self.root.geometry("500x700") # Increased height for larger fonts
        
        # Set up model manager (handles API connections and keep-warm)
        self.model_manager = get_model_manager()
        self.model_manager.start_keep_warm() # Keep the model warm
        
        # Set up visual manager (handles Tkinter-based highlights, still needed for capture)
        self.visual_manager = VisualManager(self.root)
        # Grid mode isn't directly controlled by user anymore, but keep it for potential future use
        self.visual_manager.grid_mode = True
        
        # Set up Qt overlay if requested (better for macOS)
        self.use_qt_overlay = use_qt_overlay
        self.qt_overlay = None
        self.qt_app = None
        
        if self.use_qt_overlay:
            # Ensure Qt app is created if needed
            # Pass self.root to potentially manage lifecycle better if needed
            self.qt_overlay, self.qt_app = create_overlay(parent_tk_root=self.root)
        
        # AWS S3 setup for image storage
        self.s3_client = None
        self.s3_bucket = os.getenv("S3_BUCKET_NAME")
        self.setup_s3_client()
        
        # Initialize conversation manager
        self.conversation_manager = ConversationManager()
        
        # UI elements
        self.setup_ui()
        
        # Other state variables
        self.last_screenshot_path = None
        self.last_screenshot_s3_url = None
        self.last_grid_dimensions = None # Store this after capture
        self.educational_mode = True # Educational mode enabled by default
        
    def setup_s3_client(self):
        """Setup AWS S3 client with credentials from environment"""
        aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_region = os.getenv("AWS_REGION") # Get region
        
        if aws_access_key and aws_secret_key and self.s3_bucket and aws_region:
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    region_name=aws_region # Use region
                )
                print("S3 client initialized successfully")
            except Exception as e:
                print(f"Error initializing S3 client: {e}")
                self.s3_client = None # Ensure it's None if init fails
        else:
            print("AWS credentials, bucket name, or region not found - S3 upload disabled")
            self.s3_client = None
            
    def setup_ui(self):
        """Set up the new chat-style application UI"""
        # Main frame
        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Title ---
        title_label = tk.Label(main_frame, text="AI computer assistant", font=("Arial", 16, "bold"))
        title_label.pack(pady=(0, 10))
        
        # --- Model Selection Frame ---
        model_frame = tk.Frame(main_frame)
        model_frame.pack(fill=tk.X, pady=(0, 10))
        
        model_label = tk.Label(model_frame, text="Model:", font=("Arial", 10))
        model_label.pack(side=tk.LEFT, padx=(0, 5))
        
        self.model_var = tk.StringVar(value="Gemini Pro")  # Default model
        model_options = ["Gemini Pro", "Gemini Flash", "CogAgent", "LLaVA"]
        model_dropdown = tk.OptionMenu(model_frame, self.model_var, *model_options, command=self._on_model_change)
        model_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # --- Voice Features Frame ---
        voice_frame = tk.Frame(main_frame)
        voice_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Speech input toggle
        self.speech_input_var = tk.BooleanVar(value=True)
        speech_input_check = tk.Checkbutton(
            voice_frame, 
            text="Speech Input", 
            variable=self.speech_input_var
        )
        speech_input_check.pack(side=tk.LEFT, padx=(0, 10))
        
        # Speech output toggle
        self.speech_output_var = tk.BooleanVar(value=True)
        speech_output_check = tk.Checkbutton(
            voice_frame, 
            text="Speech Output", 
            variable=self.speech_output_var
        )
        speech_output_check.pack(side=tk.LEFT, padx=(0, 10))
        
        # Voice selection
        voice_label = tk.Label(voice_frame, text="Voice:", font=("Arial", 10))
        voice_label.pack(side=tk.LEFT, padx=(10, 5))
        
        self.voice_var = tk.StringVar(value="nova")  # Default to female voice
        voice_options = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]  # OpenAI voice options
        voice_dropdown = tk.OptionMenu(voice_frame, self.voice_var, *voice_options)
        voice_dropdown.pack(side=tk.LEFT)
        
        # --- Educational Mode Toggle ---
        educational_frame = tk.Frame(main_frame)
        educational_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.educational_var = tk.BooleanVar(value=True)
        educational_check = tk.Checkbutton(
            educational_frame, 
            text="Educational Mode (Explanations & Learning Tips)", 
            variable=self.educational_var,
            command=self._toggle_educational_mode
        )
        educational_check.pack(side=tk.LEFT)
        
        # --- Chat History Area ---
        chat_frame = tk.Frame(main_frame)
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.chat_history_text = scrolledtext.ScrolledText(chat_frame, height=20, wrap=tk.WORD, state=tk.DISABLED)
        self.chat_history_text.pack(fill=tk.BOTH, expand=True)
        # Add tags for styling user and assistant messages
        self.chat_history_text.tag_configure("user", foreground="blue", font=("Arial", 12, "bold")) # Increased font size
        self.chat_history_text.tag_configure("assistant", foreground="green", font=("Arial", 12)) # Increased font size
        self.chat_history_text.tag_configure("error", foreground="red", font=("Arial", 10, "bold"))
        self.chat_history_text.tag_configure("status", foreground="gray", font=("Arial", 9, "italic"))
        self.chat_history_text.tag_configure("educational", foreground="#8B4513", font=("Arial", 11, "italic")) # Brown color for educational tips
        
        # --- Input Area ---
        input_frame = tk.Frame(main_frame)
        input_frame.pack(fill=tk.X)
        
        self.input_text = tk.Entry(input_frame, font=("Arial", 10))
        self.input_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        # Bind Enter key to send message
        self.input_text.bind("<Return>", self.send_message_event)
        
        # Add microphone button for speech input
        mic_btn = tk.Button(input_frame, text="🎤", font=("Arial", 12), command=self.record_and_transcribe)
        mic_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Add a clear button
        clear_btn = tk.Button(input_frame, text="Clear", command=self._clear_conversation)
        clear_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        send_btn = tk.Button(input_frame, text="Send", command=self.send_message)
        send_btn.pack(side=tk.LEFT)
        
        # Add welcome message
        self.root.after(100, self._show_welcome_message)
        
    def _show_welcome_message(self):
        """Show a welcome message in the chat"""
        welcome_msg = """Welcome to the AI Computer Assistant! 👋

I'm here to help you learn about your computer and how to use it. You can ask me questions like:
• "How do I open my email?"
• "What is the Finder and how do I use it?"
• "Where is the settings menu on my Mac?"

Type your question below and press Enter to get started!"""
        self.add_message_to_chat("assistant", welcome_msg)
    
    def _toggle_educational_mode(self):
        """Toggle educational mode on/off"""
        self.educational_mode = self.educational_var.get()
        if self.educational_mode:
            self.update_status("Educational mode enabled - I'll include helpful explanations!")
        else:
            self.update_status("Educational mode disabled - I'll keep responses concise.")
            
    def _clear_conversation(self):
        """Clear the conversation history"""
        # Clear text widget
        self.chat_history_text.config(state=tk.NORMAL)
        self.chat_history_text.delete(1.0, tk.END)
        self.chat_history_text.config(state=tk.DISABLED)
        
        # Clear conversation history
        self.conversation_manager.clear_history()
        
        # Clear any highlights
        if self.qt_overlay:
            self.qt_overlay.clear_all_highlights()
        
        # Show welcome message again
        self._show_welcome_message()
        
        self.update_status("Conversation cleared!")
    
    def _on_model_change(self, selection):
        """Handle model selection change event"""
        model_map = {
            "Gemini Pro": "gemini",
            "Gemini Flash": "gemini-flash",
            "CogAgent": "cogagent",
            "LLaVA": "llava"
        }
        
        model_type = model_map.get(selection, "gemini")
        model_name = self.model_manager.switch_model(model_type)
        
        self.update_status(f"Switched to {model_name} model")
        
        # Restart keep-warm with new model if enabled
        if self.model_manager.keep_warm:
            self.model_manager.stop_keep_warm()
            self.model_manager.start_keep_warm()
        
    def add_message_to_chat(self, role, message):
        """Adds a message to the chat history display with appropriate styling."""
        self.chat_history_text.config(state=tk.NORMAL) # Enable editing
        if role == "user":
            self.chat_history_text.insert(tk.END, f"You: {message}\n", ("user",))
        elif role == "assistant":
            self.chat_history_text.insert(tk.END, f"Assistant: {message}\n", ("assistant",))
        elif role == "error":
             self.chat_history_text.insert(tk.END, f"Error: {message}\n", ("error",))
        elif role == "status":
             self.chat_history_text.insert(tk.END, f"Status: {message}\n", ("status",))
        else: # Default case
            self.chat_history_text.insert(tk.END, f"{message}\n")
        
        self.chat_history_text.see(tk.END) # Scroll to the bottom
        self.chat_history_text.config(state=tk.DISABLED) # Disable editing
        self.root.update_idletasks()
        
    def update_status(self, message):
        """Update the status (prints and adds to chat)."""
        print(f"Status: {message}")
        self.add_message_to_chat("status", message)
        
    def record_and_transcribe(self):
        """Record audio and transcribe it to text using OpenAI's API"""
        if not self.speech_input_var.get():
            self.update_status("Speech input is disabled")
            return
            
        self.update_status("Recording... Speak now")
        
        # Disable UI during recording
        self.root.update_idletasks()
        
        # Record audio in a separate thread to avoid freezing UI
        audio_file = None
        
        def record_thread():
            nonlocal audio_file
            try:
                audio_file = record_audio(seconds=5)  # Record for 5 seconds
            except Exception as e:
                self.root.after(0, lambda: self.update_status(f"Recording error: {e}"))
        
        # Start recording thread
        record_thread = threading.Thread(target=record_thread)
        record_thread.start()
        record_thread.join()  # Wait for recording to complete
        
        if not audio_file:
            self.update_status("Failed to record audio")
            return
            
        self.update_status("Transcribing...")
        
        # Transcribe in separate thread
        def transcribe_thread():
            transcription = speech_to_text(audio_file)
            if transcription:
                self.root.after(0, lambda: self.input_text.insert(0, transcription))
                self.root.after(0, lambda: self.update_status("Transcription complete"))
            else:
                self.root.after(0, lambda: self.update_status("Transcription failed"))
        
        threading.Thread(target=transcribe_thread).start()
    
    def send_message_event(self, event):
        """Callback for Enter key press."""
        self.send_message()
        
    def send_message(self):
        """Handles sending the user's message and starting the workflow."""
        user_prompt = self.input_text.get().strip()
        if not user_prompt:
            self.update_status("Please enter a message.")
            return
        
        # Add user message to chat display
        self.add_message_to_chat("user", user_prompt)
        # Clear input field
        self.input_text.delete(0, tk.END)
        
        # Add to conversation manager history
        self.conversation_manager.add_message("user", user_prompt)
        
        # Detect user intent
        intent_data = self.conversation_manager.detect_intent(user_prompt)
        self.update_status(f"Detected intent: {intent_data['primary_intent']}, Visual guidance needed: {intent_data['needs_visual']}")
        
        # Start the analysis workflow in a separate thread
        threading.Thread(target=self.process_user_request, args=(user_prompt, intent_data), daemon=True).start()
        
    def _create_coordinate_prompt(self, task_prompt, intent_data=None):
        """
        Creates a prompt asking the AI to answer the question and provide coordinates if relevant.
        Optimized for Gemini's bounding box format.
        Uses intent data to guide the AI response.
        """
        # Get platform name
        platform_map = {"darwin": "macOS", "win32": "Windows", "linux": "Linux"}
        platform_name = platform_map.get(sys.platform.lower(), sys.platform)
        
        # Format recent conversation context
        recent_messages = self.conversation_manager.get_last_messages(3)
        context_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_messages[:-1]]) if len(recent_messages) > 1 else ""
        if context_str:
            context_str = f"Recent conversation:\n{context_str}\n\n"
        
        # For Gemini models, use a prompt that specifically requests the normalized coordinate format
        if self.model_manager.active_model_id in ["gemini-1.5-pro", "gemini-1.5-flash"]:
            # Get intent data if not provided
            if intent_data is None:
                intent_data = self.conversation_manager.detect_intent(task_prompt)
            
            # Check if task involves opening email or mail
            mail_related = any(term in task_prompt.lower() for term in ["mail", "email", "outlook", "thunderbird"])
            educational = self.educational_mode
            
            # Base prompt for all tasks
            prompt = f"""You are an AI assistant helping a user with their {platform_name} computer.
You're specifically designed to help users with limited computer knowledge learn how to use their computer.

{context_str}User's request: "{task_prompt}"

Please analyze the attached screenshot and answer the user's question in a clear, educational way.

IMPORTANT: For ANY question, always try to identify and provide coordinates for relevant UI elements on screen, even for explanation or general questions.

When answering, you MUST:
1. Clearly and simply describe what the relevant elements are and what they do (educational)
2. Explain where these elements are located on the screen (top, bottom, left, right, etc.)
3. Return a tight, precise bounding box around at least one visible element in the format [y_min, x_min, y_max, x_max] where:
   - y_min is the top edge
   - x_min is the left edge
   - y_max is the bottom edge
   - x_max is the right edge
4. The coordinates should be normalized values between 0-1000 where (0,0) is the top-left of the image

For abstract questions, identify relevant visual elements on screen to highlight. For example:
- For "What is a file?" - Highlight a file icon visible on screen
- For "How does copy-paste work?" - Highlight the Edit menu or visible clipboard elements
- For general questions - Highlight a relevant area of the interface

IMPORTANT:
- Make the bounding box as precise and tight as possible around just the element
- For dock or taskbar icons, focus on just the icon itself, not any labels or indicators around it
- For buttons, include only the visible button area, not any surrounding padding
"""
            # Additional educational context
            if educational:
                prompt += f"""
Please make your response educational for someone learning to use a computer:
1. Be encouraging and supportive in your tone
2. Briefly explain what the elements are used for when relevant
3. Use simple, non-technical language
4. When giving instructions, explain WHY each step is important
"""
            # Add specialized instructions for Mail app if the query is mail-related
            if mail_related:
                prompt += """

SPECIFIC INSTRUCTIONS FOR MAIL APP ICON:
- The Mail app icon typically looks like a white/light envelope on a blue background
- Draw your bounding box very precisely around just the blue square with the envelope
- Do not include any label text beneath the icon
- Do not include any badge/notification indicators
- Do not include any surrounding padding or empty space
- The icon might be in the dock, on the desktop, or in the Applications folder
- Example approximate Mail icon coordinates (but use your own precise values): [405, 580, 440, 615]"""
            
            return prompt
        else:
            # Default prompt for other models
            return f"""You are an AI assistant helping a user with their {platform_name} computer.
You are designed to provide educational support for users with limited computer knowledge.

{context_str}User's request: "{task_prompt}"

Please analyze the attached screenshot and answer the user's request.

IMPORTANT: For ANY question, always try to identify and provide coordinates for relevant UI elements on screen, even for explanation or general questions.

For your response, you MUST:
1. Describe the element clearly in simple terms.
2. Explain what it does and why it's useful.
3. Provide the bounding box coordinates for that element in the format [[x1, y1, x2, y2]] within your response.

Example response for finding an email app:
'To open your emails, click on the Mail app icon [[123, 456, 200, 550]]. The Mail app lets you read and send emails to communicate with people.'

For abstract questions, identify relevant visual elements on screen to highlight. For example:
- For "What is a file?" - Highlight a file icon visible on screen
- For "How does copy-paste work?" - Highlight the Edit menu or visible clipboard elements

Answer the user's request directly and include coordinates if applicable.
"""

    def process_user_request(self, user_prompt, intent_data=None):
        """Full workflow: screenshot, analyze, display response."""
        # Use provided intent data or detect it
        if intent_data is None:
            intent_data = self.conversation_manager.detect_intent(user_prompt)
        
        # Always apply visual cues by setting needs_visual to True
        intent_data["needs_visual"] = True
        
        # Take Screenshot for all queries
        if not self.take_screenshot():
             self.root.after(0, lambda: self.add_message_to_chat("error","Failed to take screenshot."))
             return # Stop if screenshot fails
        
        # Ensure we have a screenshot path
        if not self.last_screenshot_path:
            self.root.after(0, lambda: self.add_message_to_chat("error", "Screenshot path not set after capture."))
            return
        
        # Prepare Image for Model (S3 or Base64)
        image_url = self.last_screenshot_s3_url
        if not image_url:
            self.root.after(0, lambda: self.update_status("Encoding image as base64 (S3 upload failed or disabled)..."))
            try:
                with open(self.last_screenshot_path, "rb") as img_file:
                    img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                    image_url = f"data:image/png;base64,{img_base64}"
            except Exception as e:
                self.root.after(0, lambda: self.add_message_to_chat("error", f"Failed to encode image: {e}"))
                return # Stop if encoding fails
        
        # Analyze Screenshot
        self.root.after(0, lambda: self.update_status(f"Analyzing with {self.model_manager.active_model_id}..."))
        try:
            # Call the AI model using the manager
            coordinate_prompt = self._create_coordinate_prompt(user_prompt, intent_data)
            print(f"--- Sending Prompt to AI (intent: {intent_data['primary_intent']}): {coordinate_prompt} ---") # Log the prompt
            response = self.model_manager.call_model(image_url, coordinate_prompt)
            
            # Enhance response with educational content if educational mode is on
            if self.educational_mode:
                enhanced_response = self.conversation_manager.create_educational_response(intent_data, response)
            else:
                enhanced_response = response
            
            # Add to conversation history
            self.conversation_manager.add_message("assistant", enhanced_response)
            
            # Update UI in main thread after model call
            self.root.after(0, lambda: self._process_analysis_response(enhanced_response, intent_data))
            
        except Exception as e:
            self.root.after(0, lambda: self.add_message_to_chat("error", f"Analysis error: {e}"))
            
    def take_screenshot(self):
        """Take screenshot and prepare for analysis. Returns True on success, False on failure."""
        self.root.after(0, lambda: self.update_status("Taking screenshot..."))
        
        # Clear any existing highlights from the overlay
        if self.qt_overlay:
            # Run clear_all_highlights in the main thread if it modifies Qt elements
            self.qt_overlay.clear_all_highlights() # Assume this is thread-safe or handles its own threading
            # Or if needed: self.root.after(0, self.qt_overlay.clear_all_highlights)
        else:
            # Tkinter visual manager clearing needs to be on main thread
            self.root.after(0, self.visual_manager.clear_highlights)
        
        capture_success = threading.Event()
        capture_error = None
        
        def _capture_task():
            nonlocal capture_error
            try:
                # Minimize our own window temporarily - needs to run on main thread
                self.root.iconify()
                # Wait a moment for window to minimize
                time.sleep(0.5) # Use time.sleep in thread
                
                # Capture screen with grid if enabled (visual_manager handles grid logic)
                # Grid is drawn on the *captured image*, not necessarily displayed live unless using Tk overlay
                img_bytes, width, height, grid_dims = self.visual_manager.capture_screen(draw_grid=False) # Capture WITHOUT grid
                self.last_grid_dimensions = grid_dims # Store dimensions
                
                # Restore our window - needs to run on main thread
                self.root.deiconify()
                
                # Save screenshot locally
                screenshot_dir = os.path.dirname(os.path.abspath(__file__))
                if not os.path.exists(screenshot_dir):
                    os.makedirs(screenshot_dir) # Ensure directory exists
                screenshot_path = os.path.join(screenshot_dir, "screenshot.png")
                with open(screenshot_path, "wb") as f:
                    f.write(img_bytes)
                self.last_screenshot_path = screenshot_path # Store path
                
                # Upload to S3 if configured
                if self.s3_client and self.s3_bucket:
                    self.root.after(0, lambda: self.update_status("Uploading to S3..."))
                    try:
                        s3_key = f"AI-computer-assitant/{os.path.basename(screenshot_path)}" # Use the specified folder
                        # Use upload_fileobj with BytesIO
                        self.s3_client.upload_fileobj(
                            io.BytesIO(img_bytes),
                            self.s3_bucket,
                            s3_key,
                            ExtraArgs={'ContentType': 'image/png', 'ACL': 'public-read'} # Set content type AND public read ACL
                        )
                        
                        # Generate S3 URL (use region from env, default if missing)
                        region = os.getenv('AWS_REGION', 'us-east-1') # Default to us-east-1 if not set
                        s3_url = f"https://{self.s3_bucket}.s3.{region}.amazonaws.com/{s3_key}"
                        self.last_screenshot_s3_url = s3_url
                        print(f"--- Screenshot S3 URL: {s3_url} ---") # Log the S3 URL
                        self.root.after(0, lambda: self.update_status(f"Screenshot uploaded to S3"))
                    except NoCredentialsError:
                        self.root.after(0, lambda: self.add_message_to_chat("error","S3 upload failed: credentials not found"))
                        self.last_screenshot_s3_url = None
                    except Exception as e_s3:
                        self.root.after(0, lambda: self.add_message_to_chat("error", f"S3 upload error: {e_s3}"))
                        self.last_screenshot_s3_url = None
                else:
                    self.last_screenshot_s3_url = None # Ensure it's None if S3 not used
                
                self.root.after(0, lambda: self.update_status(f"Screenshot captured ({width}x{height})"))
                capture_success.set() # Signal success
            except Exception as e_capture:
                capture_error = e_capture
                # Restore window in case of error - needs to run on main thread
                self.root.deiconify()
                capture_success.set() # Signal completion even on error
        
        # Run capture in a separate thread to avoid blocking UI during sleep/capture
        capture_thread = threading.Thread(target=_capture_task)
        capture_thread.start()
        capture_thread.join() # Wait for capture thread to finish
        
        if capture_error:
            self.root.after(0, lambda ce=capture_error: self.add_message_to_chat("error", f"Screenshot error: {ce}"))
            return False
        return True
        
    def _process_analysis_response(self, response, intent_data=None):
        """Process the AI's response, update chat."""
        if not response:
             self.add_message_to_chat("error", "Received empty response from AI.")
             return
        
        # Add assistant message to chat display
        self.add_message_to_chat("assistant", response)
        
        # Always try to find coordinates in the response
        self._highlight_from_response(response)
        
        # Convert to speech if enabled
        if self.speech_output_var.get():
            # Start speech synthesis in a separate thread
            threading.Thread(target=self._speak_response, args=(response,), daemon=True).start()
        
        # Update status
        self.update_status("Analysis complete.")
    
    def _speak_response(self, text):
        """Convert text to speech and play it"""
        try:
            # Simplify text for speech by removing coordinate references and other formatting
            # This makes the speech more natural
            simplified_text = re.sub(r'\[[\d\., ]+\]', '', text)  # Remove coordinate patterns
            simplified_text = re.sub(r'(http|https)://[^\s]*', '', simplified_text)  # Remove URLs
            simplified_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', simplified_text)  # Remove markdown **bold**
            simplified_text = re.sub(r'\n\n', ' ', simplified_text)  # Replace double newlines with space
            
            # Further cleanup for better speech
            simplified_text = simplified_text.replace('📚 Learn More:', 'Learn More:')
            
            # Limit text length for OpenAI API (approximately 4000 characters)
            if len(simplified_text) > 4000:
                simplified_text = simplified_text[:4000] + "... and more information is in the text chat."
            
            self.update_status("Converting text to speech...")
            
            # Use the selected voice from the dropdown
            voice = self.voice_var.get()
            
            # Generate speech
            audio_path = text_to_speech(simplified_text, voice)
            
            if audio_path:
                self.update_status(f"Playing audio response using {voice} voice...")
                play_audio(audio_path)
            else:
                self.update_status("Failed to generate speech.")
                
        except Exception as e:
            self.update_status(f"Speech synthesis error: {e}")
        
    def _highlight_from_response(self, response):
        """Extract coordinates from response and use them for highlighting."""
        # Print the full response for debugging
        print(f"\n--- FULL AI RESPONSE ---\n{response}\n---END RESPONSE---\n")
        
        # Specific handling for Gemini format [y_min, x_min, y_max, x_max]
        if self.model_manager.active_model_id in ["gemini-1.5-pro", "gemini-1.5-flash"]:
            # Patterns optimized for Gemini's format
            gemini_patterns = [
                r"\[([\d\.]+),\s*([\d\.]+),\s*([\d\.]+),\s*([\d\.]+)\]",  # Standard [y_min, x_min, y_max, x_max]
                r"coordinates:?\s*\[([\d\.]+),\s*([\d\.]+),\s*([\d\.]+),\s*([\d\.]+)\]",  # With "coordinates:" prefix
                r"bounding box:?\s*\[([\d\.]+),\s*([\d\.]+),\s*([\d\.]+),\s*([\d\.]+)\]",  # With "bounding box:" prefix
            ]
            
            for pattern in gemini_patterns:
                match = re.search(pattern, response)
                if match:
                    try:
                        # Extract Gemini coordinates in order: y_min, x_min, y_max, x_max
                        y_min = float(match.group(1))
                        x_min = float(match.group(2))
                        y_max = float(match.group(3))
                        x_max = float(match.group(4))
                        
                        self.update_status(f"Found Gemini coordinates: [{y_min}, {x_min}, {y_max}, {x_max}]")
                        
                        # Get screen dimensions
                        if self.use_qt_overlay and self.qt_overlay:
                            screen_width = self.qt_overlay.screen_width
                            screen_height = self.qt_overlay.screen_height
                        else:
                            screen_width = self.root.winfo_screenwidth()
                            screen_height = self.root.winfo_screenheight()
                        
                        # Convert normalized Gemini coordinates (0-1000) to pixel coordinates
                        x1 = int(x_min * screen_width / 1000)
                        y1 = int(y_min * screen_height / 1000)
                        x2 = int(x_max * screen_width / 1000)
                        y2 = int(y_max * screen_height / 1000)
                        
                        # Calculate width and height
                        width = x2 - x1
                        height = y2 - y1
                        
                        # Determine what kind of element we're looking at
                        is_mail_icon = False
                        is_dock_icon = False
                        
                        # Check if this is a Mail app icon specifically
                        mail_terms = ["mail app", "mail icon", "mail application", "email app", "email icon"]
                        if any(term.lower() in response.lower() for term in mail_terms):
                            is_mail_icon = True
                            self.update_status("Detected Mail app icon - applying specialized refinements")
                            
                        # Analyze response text for dock-related terms
                        dock_terms = ["dock", "taskbar", "launcher"]
                        if any(term.lower() in response.lower() for term in dock_terms) or is_mail_icon:
                            is_dock_icon = True
                        
                        # Mail icon specific handling
                        if is_mail_icon:
                            # Mail icons are usually square - ensure square proportions
                            # Calculate the center point
                            center_x = (x1 + x2) / 2
                            center_y = (y1 + y2) / 2
                            
                            # Tightening factor - make mail icon highlight smaller for precision
                            tightening_factor = 0.85  # More aggressive tightening 
                            
                            # Use the smaller dimension for a square bounding box
                            box_size = min(width, height) * tightening_factor
                            
                            # Recalculate dimensions based on center point
                            half_size = box_size / 2
                            x1 = int(center_x - half_size)
                            y1 = int(center_y - half_size)
                            width = int(box_size)
                            height = int(box_size)
                            
                        # General dock icon handling (if not a mail icon)
                        elif is_dock_icon:
                            # For dock icons, ensure square-ish proportions if it seems to be an app icon
                            if not (width > height * 3 or height > width * 3):  # Not extremely elongated
                                # Make more square if needed
                                avg_size = (width + height) / 2
                                # Apply a slight reduction factor to make the highlight tighter
                                tightening_factor = 0.9
                                refined_size = int(avg_size * tightening_factor)
                                
                                # Recalculate dimensions keeping the center point the same
                                center_x = (x1 + x2) / 2
                                center_y = (y1 + y2) / 2
                                half_size = refined_size / 2
                                
                                x1 = int(center_x - half_size)
                                y1 = int(center_y - half_size)
                                width = refined_size
                                height = refined_size
                        
                        # General sanity checks
                        # Ensure minimum size - smaller for dock icons, larger for other elements
                        min_size = 20 if (is_dock_icon or is_mail_icon) else 30
                        if width < min_size:
                            width = min_size
                        if height < min_size:
                            height = min_size
                            
                        # If extremely thin in one dimension, make it more reasonable
                        if width < 10 and height > 30:
                            width = max(20, height // 3)
                        if height < 10 and width > 30:
                            height = max(20, width // 3)
                        
                        self.update_status(f"Refined pixel coordinates: [{x1}, {y1}, {x1+width}, {y1+height}]")
                        
                        # Use the overlay to highlight this area
                        if self.use_qt_overlay and self.qt_overlay:
                            # Extract context for a message
                            message_pattern = r"([^.!?]*" + re.escape(match.group(0)) + r"[^.!?]*[.!?])"
                            message_match = re.search(message_pattern, response)
                            
                            if is_mail_icon:
                                message = "Click on Mail icon" # Custom message for Mail app
                            else:
                                message = "Click here" # Default message
                            
                            if message_match:
                                # Extract the message and clean it
                                raw_message = message_match.group(1).strip()
                                # Remove the coordinates from the message
                                message = re.sub(re.escape(match.group(0)), "", raw_message).strip()
                                if not message:
                                    message = "Click here"
                            
                            # Add highlight with a more visible style
                            highlight_id = self.qt_overlay.add_highlight(
                                x1, y1, width, height,
                                message,
                                show_click=True,  # Show "CLICK HERE" indicator
                                flash=True,       # Flash the highlight
                                fade_out=False    # Don't fade out - stay visible until dismissed
                            )
                            self.update_status(f"Added highlight overlay (ID: {highlight_id})")
                        else:
                            self.update_status("Qt overlay not available. Cannot highlight.")
                        # Found valid coordinates, so return early
                        return
                    except Exception as e:
                        self.update_status(f"Error processing Gemini coordinates: {e}")
        
        # Fall back to original patterns for other models
        patterns = [
            r"\[\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]\]",  # Standard [[x,y,x,y]] (integers or floats)
            r"\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]",      # Single brackets [x,y,x,y] (integers or floats)
            r"coordinates:?\s*\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]",  # "coordinates: [x,y,x,y]"
            r"coordinates:?\s*\[\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]\]",  # "coordinates: [[x,y,x,y]]"
            r"position:?\s*\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]",  # "position: [x,y,x,y]"
            r"box:?\s*\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]",  # "box: [x,y,x,y]"
            r"([\d\.]+)\s*,\s*([\d\.]+)\s*,\s*([\d\.]+)\s*,\s*([\d\.]+)",        # Just numbers x,y,x,y
        ]
        
        # Try each pattern until we find a match
        for i, pattern in enumerate(patterns):
            match = re.search(pattern, response)
            if match:
                try:
                    # Extract coordinates - could be integers or floats
                    x1_val = match.group(1)
                    y1_val = match.group(2)
                    x2_val = match.group(3)
                    y2_val = match.group(4)
                    
                    # Check if these are normalized coordinates (0.0-1.0) or pixel coordinates
                    is_normalized = False
                    if (('.' in x1_val and float(x1_val) <= 1.0) or 
                        ('.' in y1_val and float(y1_val) <= 1.0) or
                        ('.' in x2_val and float(x2_val) <= 1.0) or
                        ('.' in y2_val and float(y2_val) <= 1.0)):
                        is_normalized = True
                    
                    # Convert to float first (works for both integers and floats)
                    x1 = float(x1_val)
                    y1 = float(y1_val)
                    x2 = float(x2_val)
                    y2 = float(y2_val)
                    
                    # If they're normalized coordinates (0.0-1.0), convert to pixels
                    if is_normalized:
                        self.update_status(f"Found normalized coordinates: [{x1}, {y1}, {x2}, {y2}]")
                        
                        # We need the screen dimensions to convert normalized to pixels
                        if self.use_qt_overlay and self.qt_overlay:
                            screen_width = self.qt_overlay.screen_width
                            screen_height = self.qt_overlay.screen_height
                            
                            # Convert normalized coordinates to pixel coordinates
                            x1 = int(x1 * screen_width)
                            y1 = int(y1 * screen_height)
                            x2 = int(x2 * screen_width)
                            y2 = int(y2 * screen_height)
                        else:
                            # Fallback to dimensions from visual_manager if qt_overlay not available
                            screen_width = self.root.winfo_screenwidth()
                            screen_height = self.root.winfo_screenheight()
                            
                            # Convert normalized coordinates to pixel coordinates
                            x1 = int(x1 * screen_width)
                            y1 = int(y1 * screen_height)
                            x2 = int(x2 * screen_width)
                            y2 = int(y2 * screen_height)
                    else:
                        # Convert float to integer for pixel coordinates
                        x1 = int(x1)
                        y1 = int(y1)
                        x2 = int(x2)
                        y2 = int(y2)
                    
                    # Sanity check: ensure width and height are positive
                    # If x2 < x1 or y2 < y1, swap them
                    if x2 < x1:
                        x1, x2 = x2, x1
                    if y2 < y1:
                        y1, y2 = y2, y1
                    
                    # Calculate width and height
                    width = x2 - x1
                    height = y2 - y1
                    
                    # Sanity check: ensure width and height are reasonable
                    if width < 5 or height < 5:
                        width = max(width, 30)  # Minimum width of 30px
                        height = max(height, 30)  # Minimum height of 30px
                    
                    self.update_status(f"Found coordinates (pattern {i+1}): [{x1}, {y1}, {x2}, {y2}]")
                    
                    # Use the overlay to highlight this area
                    if self.use_qt_overlay and self.qt_overlay:
                        # Get text surrounding the coordinates for a message
                        # Search for a sentence containing the coordinates
                        message_pattern = r"([^.!?]*" + re.escape(match.group(0)) + r"[^.!?]*[.!?])"
                        message_match = re.search(message_pattern, response)
                        message = "Click here" # Default message
                        
                        if message_match:
                            # Extract the message and clean it
                            raw_message = message_match.group(1).strip()
                            # Remove the coordinates from the message
                            message = re.sub(re.escape(match.group(0)), "", raw_message).strip()
                        
                        # Add highlight with a more visible style
                        highlight_id = self.qt_overlay.add_highlight(
                            x1, y1, width, height,
                            message,
                            show_click=True,  # Show "CLICK HERE" indicator
                            flash=True,       # Flash the highlight
                            fade_out=False    # Don't fade out - stay visible until dismissed
                        )
                        self.update_status(f"Added highlight overlay (ID: {highlight_id})")
                    else:
                        self.update_status("Qt overlay not available. Cannot highlight.")
                    # Found valid coordinates, so return early
                    return
                except Exception as e:
                    self.update_status(f"Error processing coordinates from pattern {i+1}: {e}")
                    continue  # Try the next pattern
        
        # If we get here, none of the patterns matched valid coordinates
        self.update_status("No coordinates found in the response. Please try asking again and mention 'coordinates' or 'box' specifically.")
        
    def run(self):
        """Run the application main loop"""
        self.root.mainloop()
        
        # Stop any background keep-warm threads
        print("Stopping keep-warm thread...")
        self.model_manager.stop_keep_warm()
        
        # Clean up Qt if it was created and we own the app instance
        if self.qt_app:
             print("Attempting to quit Qt application...")
             self.qt_app.quit()

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="AI Desktop Assistant")
    parser.add_argument("--no-qt", action="store_true", help="Disable Qt overlay (use Tkinter only)")
    args = parser.parse_args()
    
    # Decide whether to use Qt overlay based on flag and platform (optional)
    use_qt = not args.no_qt
    # Maybe force Tkinter on non-macOS if Qt proves unstable?
    # if platform.system() != "Darwin":
    #     use_qt = False
    
    # Create Tkinter root window *before* creating the app instance
    # as the app might need it during __init__
    root = tk.Tk()
    
    # Create and run app
    app = ScreenshotAnalyzerApp(root, use_qt_overlay=use_qt)
    
    # Start the Tkinter event loop using app.run() which calls root.mainloop()
    app.run()

if __name__ == "__main__":
    main() 