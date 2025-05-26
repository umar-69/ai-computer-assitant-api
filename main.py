#!/usr/bin/env python3
import tkinter as tk
from tkinter import scrolledtext, font as tkFont, Toplevel
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
from PIL import ImageTk, Image

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
        # Optimize text for speech to reduce size and processing time
        # Simplify text by removing markdown, coordinates, etc.
        simplified_text = re.sub(r'\[[\d\., ]+\]', '', text)  # Remove coordinate patterns
        simplified_text = re.sub(r'(http|https)://[^\s]*', '', simplified_text)  # Remove URLs
        simplified_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', simplified_text)  # Remove markdown bold
        simplified_text = re.sub(r'\n\n', ' ', simplified_text)  # Replace double newlines with space
        simplified_text = simplified_text.replace('📚 Learn More:', 'Learn More:')
        
        # Further limit text length to reduce processing time
        # Stricter limit than in _speak_response to speed up initial API call
        if len(simplified_text) > 2000:
            simplified_text = simplified_text[:2000] + "... and more information is in the text chat."
        
        # Create a temporary file for the audio
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        
        # Use the recommended streaming approach
        with openai.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice=voice,
            input=simplified_text,
            speed=1.1  # Faster speech rate for more natural sound
        ) as response:
            # Write the streaming response to the file
            with open(temp_file.name, 'wb') as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
        
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
        
        # Current detected language (default to English)
        self.detected_language = "en"
        
        # Map of question types and intents
        self.intent_keywords = {
            "how_to": ["how do i", "how to", "how can i", "steps to", "guide for"],
            "what_is": ["what is", "what are", "explain", "meaning of", "definition of"],
            "where_is": ["where is", "find", "locate", "show me", "position of"],
            "when_to": ["when should i", "when to", "best time to"],
            "why_use": ["why should i", "why use", "purpose of", "benefit of"],
            "chat": [
                "hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening",
                "how are you", "how's it going", "what's up",
                "thank you", "thanks", "great", "cool", "awesome", "ok", "okay",
                "tell me a joke", "tell me something interesting", "can you chat", "let's talk",
                "what's the weather", "what time is it", "who are you", "what is your name",
                "bye", "goodbye", "see you later"
            ]
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
        # Visuals are needed for task-oriented intents, not for "chat" or some "what_is"
        if detected_intent == "chat":
            needs_visual = False
        elif detected_intent == "what_is":
            # For "what_is", check if it's about a UI element. If not, likely general knowledge.
            mentioned_elements = [element for element in self.ui_elements.keys() if element in user_query]
            if not mentioned_elements:
                needs_visual = False # Likely a general knowledge "what is" question
            else:
                needs_visual = True # "What is" about a specific UI element, might need visual
        else:
            needs_visual = True  # Default to True for other intents (how_to, where_is etc.)
        
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
        self.root.title("Maya")
        self.root.geometry("380x720")
        self.root.configure(bg="#FDFBF7")
        
        # Re-initialize settings variables (will be linked to settings UI)
        self.model_var = tk.StringVar(value="Gemini Flash")
        self.voice_var = tk.StringVar(value="nova") # Default voice
        self.speech_output_var = tk.BooleanVar(value=True) # Default to speech output ON
        self.educational_var = tk.BooleanVar(value=False) # Default to educational mode OFF
        self.text_size_var = tk.StringVar(value="Medium") # Default text size
        self.current_font_size = 14 # Default base font size, corresponds to "Medium"

        self.settings_window = None # To keep track of the settings window
        
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
        self.educational_mode = False # Educational mode disabled by default

        # State for audio recording
        self.is_recording = False
        self.stop_recording_event = threading.Event()
        self.mic_button_widget = None
        self.cancel_button_widget = None
        
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
        main_frame = tk.Frame(self.root, padx=10, pady=10, bg="#FDFBF7") # Reduced horizontal padding slightly
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header frame for Logo and Settings Cog
        header_frame = tk.Frame(main_frame, bg="#FDFBF7")
        header_frame.pack(fill=tk.X, pady=(10,0)) # pady top only, bottom padding handled by logo_frame

        # --- Logo --- 
        # (Making logo_frame a child of header_frame for better centering if needed later)
        self.logo_frame = tk.Frame(header_frame, bg="#FDFBF7") # Store as instance variable for potential dynamic updates
        self.logo_frame.pack(side=tk.TOP, pady=(0,10)) # Centered by default if it's the only thing expanding

        try:
            logo_path = "/Users/umartahir-butt/ai-computer-assitant-api/images/Group 1171277158.png"
            if os.path.exists(logo_path):
                pil_image = Image.open(logo_path)
                base_width = 70 # Slightly smaller logo to make space for cog
                w_percent = (base_width / float(pil_image.size[0]))
                h_size = int((float(pil_image.size[1]) * float(w_percent)))
                pil_image = pil_image.resize((base_width, h_size), Image.LANCZOS)
                self.logo_image_tk = ImageTk.PhotoImage(pil_image) # Changed variable name to avoid conflict
                
                logo_label = tk.Label(self.logo_frame, image=self.logo_image_tk, bg="#FDFBF7")
                logo_label.pack()
            else:
                print(f"Error: Logo image not found at {logo_path}")
                logo_ph_label = tk.Label(self.logo_frame, text="[Logo]", bg="#FDFBF7", fg="gray", font=("Outfit", 10, "normal"))
                logo_ph_label.pack()
        except Exception as e:
            print(f"Error loading logo: {e}")
            logo_ph_label = tk.Label(self.logo_frame, text="[Logo]", bg="#FDFBF7", fg="gray", font=("Outfit", 10, "normal"))
            logo_ph_label.pack()

        # --- Settings Cog Button ---
        settings_button = tk.Button(header_frame, text="⚙️", font=("Outfit", 20), 
                                    command=self._open_settings_window, relief=tk.FLAT, bg="#FDFBF7", fg="black")
        settings_button.place(relx=1.0, rely=0.0, anchor='ne') # Place in top-right corner of header_frame
        
        # --- Chat Bubble Area ---
        chat_bubble_frame = tk.Frame(main_frame, bg="#7BE1E8", padx=15, pady=15)
        chat_bubble_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 20)) # Added a bit of top padding to bubble

        self.chat_history_text = scrolledtext.ScrolledText(
            chat_bubble_frame, 
            wrap=tk.WORD, 
            state=tk.DISABLED, 
            bg="#7BE1E8", 
            fg="black",
            font=("Outfit", self.current_font_size, "normal"), 
            relief=tk.FLAT, 
            padx=10, 
            pady=10
        )
        self.chat_history_text.pack(fill=tk.BOTH, expand=True)
        
        self._configure_chat_tags() # Call helper to set up tags based on current_font_size

        # Frame for "Next Step" button, below the chat bubble
        self.next_step_button_frame = tk.Frame(main_frame, bg="#FDFBF7")
        self.next_step_button_frame.pack(fill=tk.X, pady=(5, 5)) # Add some padding

        self.next_step_button = tk.Button(
            self.next_step_button_frame,
            text="Next Step 👉",
            font=("Outfit", 13, "bold"),
            bg="#E0E0E0", # A neutral, clickable color
            fg="black",
            relief=tk.FLAT,
            padx=10,
            pady=5,
            command=self._on_next_step_clicked
        )
        # Initially, the button might be hidden or disabled until a step is given.
        # For now, let's pack it and we can manage its state later if needed.
        self.next_step_button.pack(pady=(5,0))

        # --- Suggestion Buttons ---
        suggestion_frame = tk.Frame(main_frame, bg="#FDFBF7")
        suggestion_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 10))
        
        # Create a scrollable canvas for suggestions
        suggestion_canvas = tk.Canvas(suggestion_frame, bg="#FDFBF7", highlightthickness=0, height=100)
        scrollbar = tk.Scrollbar(suggestion_frame, orient="horizontal", command=suggestion_canvas.xview)
        suggestion_canvas.configure(xscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        suggestion_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Create a frame inside the canvas to hold the buttons
        buttons_frame = tk.Frame(suggestion_canvas, bg="#FDFBF7")
        suggestion_canvas.create_window((0, 0), window=buttons_frame, anchor="nw")
        
        # List of suggestion questions
        suggestions = [
            "How do I save a file?",
            "What is the Finder?",
            "How do I open my email?",
            "How do I search the web?",
            "Where are settings on my Mac?",
            "How do I close a window?",
            "How do I copy and paste?",
            "How do I take a screenshot?",
            "How do I install an app?",
            "How do I print a document?",
            "How do I open a file?",
            "How do I create a folder?",
            "How do I bold text?",
            "How do I make screen items bigger?",
            "How do I connect to WiFi?"
        ]
        
        # Create a button for each suggestion
        for i, suggestion in enumerate(suggestions):
            btn = tk.Button(
                buttons_frame,
                text=suggestion,
                font=("Outfit", 10),
                bg="#E9F7F7",
                fg="black",
                relief=tk.FLAT,
                padx=8,
                pady=3,
                command=lambda s=suggestion: self._use_suggestion(s)
            )
            btn.grid(row=i//5, column=i%5, padx=5, pady=5, sticky="ew")
        
        # Update the canvas scroll region after the buttons are added
        buttons_frame.update_idletasks()
        suggestion_canvas.config(scrollregion=suggestion_canvas.bbox("all"))

        # Buttons frame
        button_frame = tk.Frame(main_frame, bg="#FDFBF7")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=0)
        button_frame.columnconfigure(2, minsize=20)
        button_frame.columnconfigure(3, weight=0)
        button_frame.columnconfigure(4, weight=1)

        button_font_size = 30

        self.mic_button_widget = tk.Button(
            button_frame, 
            text="🎤", 
            font=("Outfit", button_font_size),
            fg="white", 
            bg="#1DB954",
            relief=tk.FLAT, 
            command=self.toggle_recording_and_transcribe,
            width=3,
            height=1
        )
        self.mic_button_widget.grid(row=0, column=1, sticky="ew")

        self.cancel_button_widget = tk.Button(
            button_frame, 
            text="✕", 
            font=("Outfit", button_font_size), 
            fg="white", 
            bg="#FF4136",
            relief=tk.FLAT, 
            command=self._exit_application,
            width=3, 
            height=1
        )
        self.cancel_button_widget.grid(row=0, column=3, sticky="ew")
        
        # Add welcome message
        self.root.after(100, self._show_welcome_message)
        
        # Initially hide the Next Step button
        self.next_step_button_frame.pack_forget()
        
    def _configure_chat_tags(self):
        """Helper method to configure fonts for chat history tags."""
        # Sizes relative to self.current_font_size
        user_fs = self.current_font_size
        assistant_fs = self.current_font_size
        error_fs = max(10, self.current_font_size - 2) # Ensure min size
        status_fs = max(9, self.current_font_size - 3)  # Ensure min size

        user_font = tkFont.Font(family="Outfit", size=user_fs, weight="bold")
        assistant_font = tkFont.Font(family="Outfit", size=assistant_fs, weight="normal")
        error_font = tkFont.Font(family="Outfit", size=error_fs, weight="bold")
        status_font = tkFont.Font(family="Outfit", size=status_fs, slant="italic")

        self.chat_history_text.tag_configure("user", foreground="#000000", font=user_font) 
        self.chat_history_text.tag_configure("assistant", foreground="#000000", font=assistant_font) 
        self.chat_history_text.tag_configure("error", foreground="red", font=error_font)
        self.chat_history_text.tag_configure("status", foreground="#555555", font=status_font)
        self.chat_history_text.tag_configure("educational", foreground="#000000", font=assistant_font)

    def _open_settings_window(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        self.settings_window = Toplevel(self.root)
        self.settings_window.title("Settings")
        self.settings_window.geometry("400x450") # Adjusted size
        self.settings_window.configure(bg="#FDFBF7")
        self.settings_window.transient(self.root) # Keep on top of main window
        self.settings_window.grab_set() # Modal behavior

        settings_main_frame = tk.Frame(self.settings_window, padx=15, pady=15, bg="#FDFBF7")
        settings_main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Model Selection ---
        model_frame = tk.LabelFrame(settings_main_frame, text="Model", padx=10, pady=10, bg="#FDFBF7", font=('Outfit', 12))
        model_frame.pack(fill=tk.X, pady=5)
        model_options = ["Gemini 2.5 Flash", "Gemini Pro", "Gemini Flash", "CogAgent", "LLaVA"]
        model_dropdown = tk.OptionMenu(model_frame, self.model_var, *model_options, command=self._on_model_change)
        model_dropdown.config(bg="#FDFBF7", relief=tk.FLAT, width=15, font=('Outfit', 11))
        model_dropdown["menu"].config(bg="#FDFBF7", font=('Outfit', 11))
        model_dropdown.pack(side=tk.LEFT)

        # --- Voice Selection ---
        voice_s_frame = tk.LabelFrame(settings_main_frame, text="Assistant Voice", padx=10, pady=10, bg="#FDFBF7", font=('Outfit', 12))
        voice_s_frame.pack(fill=tk.X, pady=5)
        voice_options = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        voice_dropdown = tk.OptionMenu(voice_s_frame, self.voice_var, *voice_options, command=self._on_voice_change)
        voice_dropdown.config(bg="#FDFBF7", relief=tk.FLAT, width=15, font=('Outfit', 11))
        voice_dropdown["menu"].config(bg="#FDFBF7", font=('Outfit', 11))
        voice_dropdown.pack(side=tk.LEFT)

        # --- Speech Output Toggle ---
        speech_o_frame = tk.LabelFrame(settings_main_frame, text="Speech Output", padx=10, pady=10, bg="#FDFBF7", font=('Outfit', 12))
        speech_o_frame.pack(fill=tk.X, pady=5)
        speech_output_check = tk.Checkbutton(speech_o_frame, text="Enabled", variable=self.speech_output_var, 
                                             bg="#FDFBF7", command=self._toggle_speech_output, font=('Outfit', 11), selectcolor="#E0E0E0")
        speech_output_check.pack(side=tk.LEFT)

        # --- Text Size Selection ---
        text_s_frame = tk.LabelFrame(settings_main_frame, text="Chat Text Size", padx=10, pady=10, bg="#FDFBF7", font=('Outfit', 12))
        text_s_frame.pack(fill=tk.X, pady=5)
        size_options = ["Small", "Medium", "Large"]
        # Set initial value of radio buttons from self.text_size_var
        for size in size_options:
            rb = tk.Radiobutton(text_s_frame, text=size, variable=self.text_size_var, value=size, 
                               command=self._on_text_size_change, bg="#FDFBF7", font=('Outfit', 11), selectcolor="#E0E0E0")
            rb.pack(side=tk.LEFT, padx=5)

        # --- Educational Mode Toggle ---
        edu_frame = tk.LabelFrame(settings_main_frame, text="Educational Mode", padx=10, pady=10, bg="#FDFBF7", font=('Outfit', 12))
        edu_frame.pack(fill=tk.X, pady=5)
        educational_check = tk.Checkbutton(edu_frame, text="Enabled", variable=self.educational_var, 
                                            bg="#FDFBF7", command=self._toggle_educational_mode, font=('Outfit', 11), selectcolor="#E0E0E0")
        educational_check.pack(side=tk.LEFT)

        # --- Close Button for Settings ---
        close_button = tk.Button(settings_main_frame, text="Done", command=self.settings_window.destroy, 
                                 bg="#E0E0E0", relief=tk.FLAT, font=('Outfit', 12, 'bold'), padx=10)
        close_button.pack(pady=20)

    def _on_voice_change(self, selection):
        self.update_status(f"Assistant voice changed to: {selection}")
        # self.voice_var is automatically updated by Tkinter

    def _toggle_speech_output(self):
        status = "enabled" if self.speech_output_var.get() else "disabled"
        self.update_status(f"Speech output {status}")

    def _on_text_size_change(self):
        size_map = {"Small": 12, "Medium": 14, "Large": 16}
        new_base_size = size_map.get(self.text_size_var.get(), 14) # Default to Medium (14)
        self.current_font_size = new_base_size
        
        # Update the main chat history text font directly
        self.chat_history_text.config(font=("Outfit", self.current_font_size, "normal"))
        # Reconfigure all tags
        self._configure_chat_tags()
        self.update_status(f"Chat text size changed to: {self.text_size_var.get()} ({self.current_font_size}pt)")
        
    def _show_welcome_message(self):
        """Show a welcome message in the chat"""
        welcome_msg = """Welcome to the AI Computer Assistant! 👋

I'm here to help you learn about your computer and how to use it. You can ask me questions like:
• "How do I open my email?"
• "What is the Finder and how do I use it?"
• "Where is the settings menu on my Mac?"

Tap the microphone to ask your question!"""
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
        if self.is_recording:
            self.stop_recording_event.set()
            # The recording thread will handle UI updates for the mic button
            self.update_status("Recording stopped due to conversation clear.")
            # is_recording will be set to False by the recording thread

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
        
    def _exit_application(self):
        """Exit the application"""
        if self.is_recording:
            self.stop_recording_event.set()
            self.update_status("Recording stopped due to application exit.")
        
        # Clear any highlights
        if self.qt_overlay:
            self.qt_overlay.clear_all_highlights()
        
        # Stop any background keep-warm threads
        self.model_manager.stop_keep_warm()
        
        # Exit the application
        self.update_status("Exiting application...")
        self.root.after(500, self.root.quit)  # Give a brief delay to show the exit message
    
    def _on_model_change(self, selection):
        """Handle model selection change event"""
        model_map = {
            "Gemini Pro": "gemini",
            "Gemini Flash": "gemini-flash",
            "Gemini 2.5 Flash": "gemini-2.5-flash",
            "CogAgent": "cogagent",
            "LLaVA": "llava"
        }
        
        model_type = model_map.get(selection, "gemini-2.5-flash")
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
        
    def _record_audio_continuous(self, stop_event):
        """
        Record audio continuously until stop_event is set.
        Returns the path to the saved audio file or None.
        """
        chunk = 1024
        sample_format = pyaudio.paInt16
        channels = 1
        fs = 44100  # Sample rate
        
        p = pyaudio.PyAudio()
        
        stream = p.open(format=sample_format,
                        channels=channels,
                        rate=fs,
                        frames_per_buffer=chunk,
                        input=True)
        frames = []
        
        self.root.after(0, lambda: self.update_status("Recording started..."))
        
        while not stop_event.is_set():
            try:
                data = stream.read(chunk, exception_on_overflow=False)
                frames.append(data)
            except IOError as e:
                # Handle buffer overflow if necessary, though exception_on_overflow=False helps
                if e.errno == pyaudio.paInputOverflowed:
                    self.root.after(0, lambda: self.update_status("Warning: Audio input overflowed."))
                else:
                    raise
        
        self.root.after(0, lambda: self.update_status("Recording stopped."))
        
        # Stop and close the stream
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        if not frames:
            return None

        # Save to a temporary WAV file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        wf = wave.open(temp_file.name, 'wb')
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(sample_format))
        wf.setframerate(fs)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        return temp_file.name

    def toggle_recording_and_transcribe(self):
        """Toggle audio recording: start if not recording, stop if recording."""
        if self.is_recording:
            self.stop_recording_event.set()
            # UI updates (disabling button during stop, re-enabling after) will be handled
            # partly here and partly by _execute_recording_session upon completion.
            if self.mic_button_widget:
                self.mic_button_widget.config(state=tk.DISABLED, text="...") # Indicate processing
        else:
            self.is_recording = True
            self.stop_recording_event.clear()
            
            if self.mic_button_widget:
                self.mic_button_widget.config(text="⏹️", bg="#FFA500", state=tk.NORMAL) # Stop symbol, orange bg
            if self.cancel_button_widget: # Keep cancel button enabled
                self.cancel_button_widget.config(state=tk.NORMAL)

            self.update_status("Starting recording session...")
            threading.Thread(target=self._execute_recording_session, daemon=True).start()

    def _execute_recording_session(self):
        """Handles the audio recording process in a separate thread."""
        audio_file_path = None
        try:
            audio_file_path = self._record_audio_continuous(self.stop_recording_event)
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"Recording error: {e}"))
        finally:
            self.is_recording = False # Ensure this is reset
            # Reset mic button in the main thread
            self.root.after(0, lambda: {
                self.mic_button_widget.config(text="🎤", bg="#4CAF50", state=tk.NORMAL) if self.mic_button_widget else None,
                self.cancel_button_widget.config(state=tk.NORMAL) if self.cancel_button_widget else None
            })

            if audio_file_path:
                self.root.after(0, self._transcribe_audio_and_process, audio_file_path)
            else:
                # This case handles if recording was stopped very quickly with no data
                self.root.after(0, lambda: self.update_status("Recording session ended. No audio data to process."))
    
    def _transcribe_audio_and_process(self, audio_file_path):
        """Transcribes the audio file and then processes the resulting text."""
        self.update_status("Transcribing audio...")

        def transcribe_thread_fn():
            transcription = speech_to_text(audio_file_path) # speech_to_text handles file cleanup
            
            if transcription:
                self.root.after(0, lambda t=transcription: self.process_transcribed_speech(t))
                self.root.after(0, lambda: self.update_status("Transcription processed."))
            else:
                self.root.after(0, lambda: self.update_status("Transcription failed or was empty."))
        
        threading.Thread(target=transcribe_thread_fn, daemon=True).start()

    def process_transcribed_speech(self, user_prompt):
        """Processes the transcribed speech as if it were user input."""
        if not user_prompt:
            self.update_status("Transcription was empty. Nothing to process.")
            return
        
        self.add_message_to_chat("user", user_prompt)
        
        # Detect language of user input
        detected_language = self.detect_language(user_prompt)
        self.conversation_manager.detected_language = detected_language
        if detected_language != "en":
            self.update_status(f"Detected language: {detected_language}")
        
        self.conversation_manager.add_message("user", user_prompt)
        intent_data = self.conversation_manager.detect_intent(user_prompt)
        self.update_status(f"Detected intent: {intent_data['primary_intent']}, Visual guidance needed: {intent_data['needs_visual']}")
        
        threading.Thread(target=self.process_user_request, args=(user_prompt, intent_data), daemon=True).start()
        
    def detect_language(self, text):
        """
        Detect the language of the input text.
        Returns language code (e.g., 'en', 'ur', 'de')
        """
        # Simple language detection based on script and common markers
        # Proper implementation would use a language detection library
        
        # Check for common Urdu/Arabic script characters
        if any('\u0600' <= c <= '\u06FF' for c in text):
            if any(marker in text for marker in ["کیسے", "ہے", "میں", "کیا"]):
                return "ur"  # Urdu
            return "ar"  # Default to Arabic for Arabic script
        
        # Check for German markers
        if any(marker in text.lower() for marker in ["wie ", "ist ", "und ", "ich ", "der ", "das ", "ein ", "eine "]):
            return "de"  # German
        
        # Default to English
        return "en"

    def _create_coordinate_prompt(self, task_prompt, intent_data=None):
        """
        Creates a prompt asking the AI to answer the question and provide coordinates if relevant.
        Optimized for Gemini's bounding box format.
        Uses intent data to guide the AI response.
        """
        platform_map = {"darwin": "macOS", "win32": "Windows", "linux": "Linux"}
        platform_name = platform_map.get(sys.platform.lower(), sys.platform)
        
        # Add macOS-specific guidance
        mac_specific_guidance = ""
        if platform_name == "macOS":
            mac_specific_guidance = """
MAC-SPECIFIC GUIDANCE:
- The Dock is at the bottom of the screen with app icons
- The Apple menu (⌘) is at the top-left corner of the screen
- Menu bar is always at the top of the screen
- Applications have their menus in the top menu bar, not in the app window
- Finder is the file manager (blue face icon)
- Mission Control shows all open windows
- Spotlight search is accessed with the magnifying glass icon in the menu bar
- To close apps, use Command+Q or the red button at the top-left of the window
- To minimize windows, use the yellow button at the top-left
- The green button at the top-left maximizes/enters full screen
"""

        recent_messages = self.conversation_manager.get_last_messages(3)
        context_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_messages[:-1]]) if len(recent_messages) > 1 else ""
        if context_str:
            # Corrected f-string for multi-line content
            context_str = f"""Recent conversation context (ignore your previous responses if they didn\'t follow the single-step rule):
{context_str}

""" # Ensure the f-string is properly terminated
        
        # Check against the new default Pro model and the existing Flash model ID
        if self.model_manager.active_model_id in ["gemini-2.5-pro-preview-05-06", "gemini-1.5-flash", "gemini-2.5-flash-preview-04-17"]:
            if intent_data is None:
                intent_data = self.conversation_manager.detect_intent(task_prompt)
            
            mail_related = any(term in task_prompt.lower() for term in ["mail", "email", "outlook", "thunderbird"])
            educational = self.educational_mode
            
            # Determine language for response
            language_instruction = ""
            detected_lang = getattr(self.conversation_manager, 'detected_language', 'en')
            if detected_lang != "en":
                language_map = {
                    "ur": "Urdu",
                    "ar": "Arabic",
                    "de": "German", 
                    # Add more as needed
                }
                lang_name = language_map.get(detected_lang, "the same language as the user")
                language_instruction = f"\nIMPORTANT: The user is speaking in {lang_name}. RESPOND IN {lang_name} ONLY. Do not use English."
            
            prompt = f"""You are an AI assistant helping an elderly person with limited computer knowledge learn to use their {platform_name} computer.
Your primary goal is to guide the user through tasks by providing ONE SINGLE, CLEAR, ACTIONABLE STEP at a time.{language_instruction}

{context_str}User's current request: "{task_prompt}"

{mac_specific_guidance}

USE EXTREMELY SIMPLE LANGUAGE: 
- Use the simplest words possible - like you're explaining to a child
- Use very short sentences
- Avoid all technical terms
- Use everyday comparisons
- Be patient and encouraging
- Never use jargon or abbreviations

COORDINATE SYSTEM:
- The screen's TOP-LEFT corner is (0,0).
- Moving RIGHT increases X value (from 0 to 1000).
- Moving DOWN increases Y value (from 0 to 1000).
- Give coordinates as [y_min, x_min, y_max, x_max] (normalized 0-1000).

YOUR RESPONSE MUST:
1. Give ONLY ONE action for the user to do right now - never more than one step
2. Show coordinates for just ONE element on screen for this action
3. NEVER list multiple steps - focus only on the immediate next action
4. For broad requests, focus on just the first logical action
5. Use words anyone can understand, no technical terms
6. Be encouraging and patient
7. Make your bounding box tight around just the element needed
8. Keep responses brief and to the point - no lengthy explanations

Analyze the screenshot and give the user just the next single step they should take.
"""
            if educational:
                prompt += "Briefly explain WHY each step matters in simple terms.\n"

            if mail_related:
                prompt += "\nIf the current action involves the Mail app icon (blue square with white envelope), make the bounding box very precise around just that icon.\n"
            
            return prompt
        else:
            # Simplified prompt for other models, emphasizing single step
            return f"""You are an AI assistant for {platform_name} helping an elderly person. Guide the user with ONE clear action per response. 
{context_str}User asks: "{task_prompt}" 
Use extremely simple, everyday words like you're explaining to a child. Provide a single instruction and, if relevant, coordinates [[x1, y1, x2, y2]] for ONE key element for that action. Be patient and encouraging."""

    def _create_chat_prompt(self, task_prompt):
        """
        Creates a simpler prompt for general chat interactions.
        """
        platform_map = {"darwin": "macOS", "win32": "Windows", "linux": "Linux"}
        platform_name = platform_map.get(sys.platform.lower(), sys.platform)
        
        recent_messages = self.conversation_manager.get_last_messages(3)
        context_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_messages[:-1]]) if len(recent_messages) > 1 else ""
        if context_str:
            context_str = f"""Recent conversation context:
{context_str}

"""
        
        # Determine language for response
        language_instruction = ""
        detected_lang = getattr(self.conversation_manager, 'detected_language', 'en')
        if detected_lang != "en":
            language_map = {
                "ur": "Urdu",
                "ar": "Arabic",
                "de": "German", 
                # Add more as needed
            }
            lang_name = language_map.get(detected_lang, "the same language as the user")
            language_instruction = f"\nIMPORTANT: The user is speaking in {lang_name}. RESPOND IN {lang_name} ONLY."
        
        prompt = f"""You are a friendly and patient AI assistant for an elderly person using a {platform_name} computer. They are looking to chat or ask a general question.{language_instruction}

{context_str}User says: "{task_prompt}"

Your goal is to be a good conversationalist. 
- Respond in a kind, simple, and understanding way.
- Keep your answers VERY concise and easy to understand - use short sentences.
- Limit responses to 2-3 sentences whenever possible.
- If they ask a question you can answer, do so simply.
- If they are just chatting, respond naturally but briefly.
- Do not ask them to perform any actions on the computer.
- Do not mention screen elements or coordinates.
- Avoid lengthy explanations or technical details.

Provide a helpful and friendly chat response.
"""
        return prompt

    def process_user_request(self, user_prompt, intent_data=None):
        """Full workflow: screenshot, analyze, display response."""
        # Use provided intent data or detect it
        if intent_data is None:
            intent_data = self.conversation_manager.detect_intent(user_prompt)
        
        # Determine if screenshot and visual analysis are needed
        needs_visual_processing = intent_data.get("needs_visual", True)
        self.update_status(f"Intent: {intent_data.get('primary_intent', 'general')}, Needs visual: {needs_visual_processing}")
        
        image_url = None
        if needs_visual_processing:
            if not self.take_screenshot():
                 self.root.after(0, lambda: self.add_message_to_chat("error","Failed to take screenshot."))
                 return # Stop if screenshot fails
            
            if not self.last_screenshot_path:
                self.root.after(0, lambda: self.add_message_to_chat("error", "Screenshot path not set after capture."))
                return
            
            # Use S3 URL if available, otherwise encode as base64
            image_url = self.last_screenshot_s3_url
            if not image_url:
                self.root.after(0, lambda: self.update_status("Encoding image as base64..."))
                try:
                    with open(self.last_screenshot_path, "rb") as img_file:
                        img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                        image_url = f"data:image/png;base64,{img_base64}"
                        self.root.after(0, lambda: self.update_status("Image encoded as base64"))
                except Exception as e:
                    self.root.after(0, lambda: self.add_message_to_chat("error", f"Failed to encode image: {e}"))
                    return
        else:
            self.update_status("Skipping screenshot for chat-based interaction.")
        
        # Analyze Screenshot or process chat
        self.root.after(0, lambda: self.update_status(f"Processing with {self.model_manager.active_model_id}..."))
        try:
            if needs_visual_processing:
                prompt = self._create_coordinate_prompt(user_prompt, intent_data)
                print(f"--- Sending COORDINATE Prompt to AI (intent: {intent_data['primary_intent']}): {prompt} ---")
            else:
                prompt = self._create_chat_prompt(user_prompt)
                print(f"--- Sending CHAT Prompt to AI (intent: {intent_data['primary_intent']}): {prompt} ---")
            
            # Call the AI model using the manager
            # image_url will be None if not needs_visual_processing, model manager should handle this
            if not needs_visual_processing:
                # For chat, send a null image parameter
                response = self.model_manager.call_model(None, prompt)
            else:
                # For visual tasks, send the image URL
                response = self.model_manager.call_model(image_url, prompt)
            
            # Educational enhancement is now conditional based on the initial mode and if it's not a pure chat interaction
            enhanced_response = response
            if self.educational_mode and needs_visual_processing: # Only apply if educational mode is on AND it was a visual task
                enhanced_response = self.conversation_manager.create_educational_response(intent_data, response)
            
            # Add to conversation history
            self.conversation_manager.add_message("assistant", enhanced_response)
            
            # Update UI in main thread after model call
            self.root.after(0, lambda: self._process_analysis_response(enhanced_response, intent_data, needs_visual_processing))
            
        except Exception as e:
            self.root.after(0, lambda: self.add_message_to_chat("error", f"Analysis error: {e}"))
            
    def take_screenshot(self):
        """Take screenshot and prepare for analysis. Returns True on success, False on failure."""
        self.root.after(0, lambda: self.update_status("Taking screenshot..."))
        
        # Clear any existing highlights from the overlay
        if self.qt_overlay:
            self.qt_overlay.clear_all_highlights()
        else:
            self.root.after(0, self.visual_manager.clear_highlights)
        
        capture_success = threading.Event()
        capture_error = None
        
        def _capture_task():
            nonlocal capture_error
            try:
                # Minimize our own window temporarily - needs to run on main thread
                self.root.iconify()
                # Wait a moment for window to minimize
                time.sleep(0.3)  # Reduced wait time for faster response
                
                # Capture screen without grid for faster processing
                img_bytes, width, height, grid_dims = self.visual_manager.capture_screen(draw_grid=False)
                self.last_grid_dimensions = grid_dims
                
                # Restore our window
                self.root.deiconify()
                
                # Save screenshot locally
                screenshot_dir = os.path.dirname(os.path.abspath(__file__))
                if not os.path.exists(screenshot_dir):
                    os.makedirs(screenshot_dir)
                screenshot_path = os.path.join(screenshot_dir, "screenshot.png")
                with open(screenshot_path, "wb") as f:
                    f.write(img_bytes)
                self.last_screenshot_path = screenshot_path
                
                # Upload to S3 if configured - now return the URL directly if successful
                self.last_screenshot_s3_url = None
                if self.s3_client and self.s3_bucket:
                    self.root.after(0, lambda: self.update_status("Uploading to S3..."))
                    try:
                        # Do S3 upload synchronously to ensure URL is available for the next step
                        s3_key = f"AI-computer-assitant/{os.path.basename(screenshot_path)}"
                        self.s3_client.upload_fileobj(
                            io.BytesIO(img_bytes),
                            self.s3_bucket,
                            s3_key,
                            ExtraArgs={'ContentType': 'image/png', 'ACL': 'public-read'}
                        )
                        
                        region = os.getenv('AWS_REGION', 'us-east-1')
                        s3_url = f"https://{self.s3_bucket}.s3.{region}.amazonaws.com/{s3_key}"
                        self.last_screenshot_s3_url = s3_url
                        print(f"--- Screenshot S3 URL: {s3_url} ---")
                        self.root.after(0, lambda: self.update_status("Screenshot uploaded to S3"))
                    except Exception as e:
                        self.root.after(0, lambda e=e: self.add_message_to_chat("error", f"S3 upload error: {e}"))
                        self.last_screenshot_s3_url = None
                
                self.root.after(0, lambda: self.update_status(f"Screenshot captured ({width}x{height})"))
                capture_success.set()
            except Exception as e_capture:
                capture_error = e_capture
                self.root.deiconify()
                capture_success.set()
        
        # Run capture in a separate thread
        capture_thread = threading.Thread(target=_capture_task)
        capture_thread.start()
        capture_thread.join()
        
        if capture_error:
            self.root.after(0, lambda ce=capture_error: self.add_message_to_chat("error", f"Screenshot error: {ce}"))
            return False
        return True
        
    def _process_analysis_response(self, response, intent_data=None, was_visual_processing=True):
        """Process the AI's response, update chat."""
        if not response:
             self.add_message_to_chat("error", "Received empty response from AI.")
             if was_visual_processing: # Only hide if it might have been shown
                 self._hide_next_step_button()
             return
        
        # Add assistant message to chat display
        self.add_message_to_chat("assistant", response)
        
        if was_visual_processing:
            # Logic to decide if "Next Step" button should be shown.
            instructional_phrases = ["first,", "next,", "then,", "click on", "now, try", "the next step is", "you should now"]
            response_lower = response.lower()
            has_instruction_cue = any(phrase in response_lower for phrase in instructional_phrases)
            has_coordinates = re.search(r"\[[\d\.,\s]+\]", response) # Check for coordinate pattern

            if has_instruction_cue or has_coordinates:
                completion_phrases = ["task is complete", "you've successfully", "all done", "that's it!", "you're all set"]
                if not any(phrase in response_lower for phrase in completion_phrases):
                    self._show_next_step_button()
                else:
                    self._hide_next_step_button() # Task seems complete
            else:
                self._hide_next_step_button() # Not clearly a step, so hide it

            # Always try to find coordinates in the response for highlighting
            self._highlight_from_response(response)
        else:
            # For non-visual (chat) responses, ensure Next Step is hidden
            self._hide_next_step_button()
        
        # Convert to speech if enabled
        if self.speech_output_var.get():
            threading.Thread(target=self._speak_response, args=(response,), daemon=True).start()
        
        self.update_status("Analysis complete.")
    
    def _speak_response(self, text):
        """Convert text to speech and play it"""
        try:
            # We already simplified the text in the text_to_speech function
            # No need to repeat the same text cleanup here
            
            # Skip speech for very long responses to speed up interaction
            if len(text) > 4000:
                self.update_status("Response too long for speech output. Reading a shortened version.")
            
            self.update_status("Converting text to speech...")
            
            # Use the selected voice from the dropdown
            voice = self.voice_var.get()
            
            # Generate speech in a separate thread to keep UI responsive
            def generate_and_play():
                try:
                    audio_path = text_to_speech(text, voice)
                    if audio_path:
                        self.root.after(0, lambda: self.update_status(f"Playing audio response..."))
                        play_audio(audio_path)
                    else:
                        self.root.after(0, lambda: self.update_status("Failed to generate speech."))
                except Exception as e:
                    self.root.after(0, lambda: self.update_status(f"Speech playback error: {e}"))
            
            # Start speech generation in background thread
            speech_thread = threading.Thread(target=generate_and_play, daemon=True)
            speech_thread.start()
            
        except Exception as e:
            self.update_status(f"Speech synthesis error: {e}")
        
    def _highlight_from_response(self, response):
        """Extract coordinates from response and use them for highlighting."""
        # Print the full response for debugging
        print(f"\n--- FULL AI RESPONSE ---\n{response}\n---END RESPONSE---\n")
        
        # First try to match Gemini 2.5/1.5 format [y_min, x_min, y_max, x_max]
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
                        dpr = getattr(self.qt_overlay, 'device_pixel_ratio', 1.0)
                    else:
                        screen_width = self.root.winfo_screenwidth()
                        screen_height = self.root.winfo_screenheight()
                    
                    # Calculate pixel coordinates from normalized coordinates (0-1000)
                    x1 = int(x_min * screen_width / 1000)
                    y1 = int(y_min * screen_height / 1000)
                    x2 = int(x_max * screen_width / 1000)
                    y2 = int(y_max * screen_height / 1000)
                    width = x2 - x1
                    height = y2 - y1
                    
                    self.update_status(f"Calculated pixel coordinates: x1={x1}, y1={y1}, width={width}, height={height}")
                    
                    # Determine what kind of element we're highlighting
                    is_mail_icon = any(term.lower() in response.lower() for term in ["mail app", "mail icon", "email app"])
                    is_dock_icon = any(term.lower() in response.lower() for term in ["dock", "taskbar", "launcher"]) or is_mail_icon
                    
                    # Handle element-specific adjustments
                    if is_mail_icon:
                        # Create more precise boundaries for mail icon (square with center preserved)
                        center_x = (x1 + x2) / 2
                        center_y = (y1 + y2) / 2
                        box_size = min(width, height) * 0.85  # Tighter box
                        half_size = box_size / 2
                        x1 = int(center_x - half_size)
                        y1 = int(center_y - half_size)
                        width = int(box_size)
                        height = int(box_size)
                        self.update_status("Refined coordinates for Mail icon")
                    elif is_dock_icon and not (width > height * 3 or height > width * 3):
                        # For other dock icons, make more square if not extremely elongated
                        center_x = (x1 + x2) / 2
                        center_y = (y1 + y2) / 2
                        refined_size = int(min(width, height) * 0.9)  # Use smaller dimension with slight reduction
                        half_size = refined_size / 2
                        x1 = int(center_x - half_size)
                        y1 = int(center_y - half_size)
                        width = refined_size
                        height = refined_size
                        self.update_status("Refined coordinates for dock icon")
                    
                    # Ensure minimum size for visibility
                    min_size = 20 if is_dock_icon else 30
                    width = max(width, min_size)
                    height = max(height, min_size)
                    
                    # Add highlight with the Qt overlay
                    if self.use_qt_overlay and self.qt_overlay:
                        # Extract context for a helpful message
                        # Find sentence containing coordinates, or a clear instruction nearby
                        message = "Click here"  # Default
                        
                        # Try to find a clear instruction in the text
                        instruction_patterns = [
                            r"(?:click|tap|press)(?:\s+on)?\s+(?:the\s+)?([^\.,]+)",  # "click on the X" or "click X"
                            r"(?:select|choose)(?:\s+the)?\s+([^\.,]+)",  # "select the X"
                            r"(?:open|launch)(?:\s+the)?\s+([^\.,]+)"  # "open the X"
                        ]
                        
                        for i_pattern in instruction_patterns:
                            i_match = re.search(i_pattern, response.lower())
                            if i_match:
                                action_target = i_match.group(1).strip()
                                if 5 <= len(action_target) <= 40:  # Reasonable length for a message
                                    message = f"Click {action_target}"
                                    break
                        
                        # If we still have the default, try to extract message from coordinate context
                        if message == "Click here":
                            sentence_with_coords = re.search(r'([^.!?]*' + re.escape(match.group(0)) + r'[^.!?]*[.!?])', response)
                            if sentence_with_coords:
                                clean_sentence = re.sub(re.escape(match.group(0)), "", sentence_with_coords.group(1)).strip()
                                if clean_sentence and 5 <= len(clean_sentence) <= 60:
                                    message = clean_sentence
                        
                        # Add highlight with improved visibility
                        self.qt_overlay.add_highlight(
                            x1, y1, width, height,
                            message,
                            show_click=True,
                            flash=True,
                            fade_out=False
                        )
                        self.update_status(f"Added highlight at x={x1}, y={y1}, w={width}, h={height}")
                    else:
                        self.update_status("Qt overlay not available for highlighting")
                    
                    return  # Successfully processed coordinates
                except Exception as e:
                    self.update_status(f"Error processing coordinates: {e}")
        
        # Fall back to other coordinate formats if Gemini format not found
        alternative_patterns = [
            r"\[\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]\]",  # [[x,y,x,y]]
            r"coordinates:?\s*\[\[([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+),?\s*([\d\.]+)\]\]"  # coordinates: [[x,y,x,y]]
        ]
        
        for pattern in alternative_patterns:
            match = re.search(pattern, response)
            if match:
                try:
                    # Alternative format - could be [x1,y1,x2,y2] or other arrangement
                    # Assume x1,y1,x2,y2 format to start
                    vals = [float(match.group(i)) for i in range(1, 5)]
                    
                    # Check if these look like normalized values (0-1)
                    is_normalized = any('.' in match.group(i) and float(match.group(i)) <= 1.0 for i in range(1, 5))
                    
                    # Get screen dimensions
                    if self.use_qt_overlay and self.qt_overlay:
                        screen_width = self.qt_overlay.screen_width
                        screen_height = self.qt_overlay.screen_height
                    else:
                        screen_width = self.root.winfo_screenwidth()
                        screen_height = self.root.winfo_screenheight()
                    
                    # Convert to pixel coordinates
                    if is_normalized:
                        x1, y1, x2, y2 = [int(vals[0] * screen_width), int(vals[1] * screen_height), 
                                          int(vals[2] * screen_width), int(vals[3] * screen_height)]
                    else:
                        x1, y1, x2, y2 = [int(v) for v in vals]
                    
                    # Ensure correct ordering
                    if x2 < x1: x1, x2 = x2, x1
                    if y2 < y1: y1, y2 = y2, y1
                    
                    width = x2 - x1
                    height = y2 - y1
                    
                    # Ensure minimum size
                    width = max(width, 30)
                    height = max(height, 30)
                    
                    # Add highlight
                    if self.use_qt_overlay and self.qt_overlay:
                        self.qt_overlay.add_highlight(
                            x1, y1, width, height,
                            "Click here",
                            show_click=True,
                            flash=True,
                            fade_out=False
                        )
                        self.update_status(f"Added highlight using alternative coordinates")
                    return
                except Exception as e:
                    self.update_status(f"Error processing alternative coordinates: {e}")
        
        self.update_status("No recognizable coordinates found in the response")
        
    def _show_next_step_button(self):
        """Makes the 'Next Step' button visible."""
        self.next_step_button_frame.pack(fill=tk.X, pady=(5, 5), before=self.chat_history_text.master.master.winfo_children()[-1]) # pack before main mic/cancel buttons
        self.next_step_button.pack(pady=(5,0)) # Ensure it's packed if frame was repacked

    def _hide_next_step_button(self):
        """Hides the 'Next Step' button."""
        self.next_step_button_frame.pack_forget()

    def _on_next_step_clicked(self):
        """Handles the 'Next Step' button click."""
        user_prompt = "Okay, I've done that. What's the next step?"
        
        self.add_message_to_chat("user", user_prompt) # Add this "action" to chat
        
        self.conversation_manager.add_message("user", user_prompt)
        
        # For "Next Step", we always assume it's a continuation of a task
        # and requires the same context (and potentially visuals) as the previous step.
        # We bypass general intent detection here to ensure it's treated as a task follow-up.
        intent_data = {
            "primary_intent": "next_step_follow_up", # Specific intent for clarity
            "needs_visual": True,                   # Crucially, set this to True
            "mentioned_elements": []                # Typically no new elements in this phrase
        }
        self.update_status(f"User clicked 'Next Step'. Processing as a task follow-up with visual context.")
        
        # Hide the button temporarily after click, AI response might re-show it if there are more steps
        self._hide_next_step_button()

        threading.Thread(target=self.process_user_request, args=(user_prompt, intent_data), daemon=True).start()
        
    def _use_suggestion(self, suggestion):
        """Handle click on a suggestion button - process it as if user spoke it"""
        self.add_message_to_chat("user", suggestion)
        self.conversation_manager.add_message("user", suggestion)
        intent_data = self.conversation_manager.detect_intent(suggestion)
        self.update_status(f"Processing suggestion: {suggestion}")
        
        threading.Thread(target=self.process_user_request, args=(suggestion, intent_data), daemon=True).start()
        
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