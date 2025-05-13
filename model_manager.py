import threading
import time
import replicate
import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# --- Constants ---
# CogAgent model
COGAGENT_MODEL_ID = "cjwbw/cogagent-chat"
COGAGENT_VERSION_HASH = "c3429fc8f69bc71d0ee109e99c62b1e223b7cdfc0839b8e44a4326e12752656e"

# LLaVA model
LLAVA_MODEL_ID = "yorickvp/llava-13b"
LLAVA_VERSION_HASH = "80537f9eead1a5bfa72d5ac6ea6414379be41d4d4f6679fd776e9535d1eb58bb"

# Gemini models
GEMINI_MODEL_ID = "gemini-1.5-pro"
GEMINI_FLASH_ID = "gemini-1.5-flash"  # Faster, smaller model

class ModelManager:
    def __init__(self):
        # Initialize Replicate client
        self.api_token = os.getenv("REPLICATE_API_TOKEN")
        if not self.api_token:
            print("Warning: REPLICATE_API_TOKEN not found in environment variables")
        else:
            self.client = replicate.Client(api_token=self.api_token)
        
        # Initialize Gemini client
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "AIzaSyBtdcdBlL9dIZCI9nM7Km4POGCpOveePQs")
        if self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)
            self.gemini_model = genai.GenerativeModel(model_name=GEMINI_MODEL_ID)
            self.gemini_flash = genai.GenerativeModel(model_name=GEMINI_FLASH_ID)
        else:
            print("Warning: GEMINI_API_KEY not found in environment variables")
            self.gemini_model = None
            self.gemini_flash = None
            
        # Current active model
        self.active_model_id = GEMINI_MODEL_ID  # Default to Gemini
        self.active_version_hash = None  # Not used for Gemini
        
        # Warm-up settings
        self.keep_warm = False
        self.warm_up_interval = 300  # seconds (5 minutes)
        self.warm_up_thread = None
        self.stop_warm_up = threading.Event()
    
    def switch_model(self, model_type="gemini"):
        """Switch between supported models"""
        model_type = model_type.lower()
        if model_type == "llava":
            self.active_model_id = LLAVA_MODEL_ID
            self.active_version_hash = LLAVA_VERSION_HASH
            return "LLaVA"
        elif model_type == "cogagent":
            self.active_model_id = COGAGENT_MODEL_ID
            self.active_version_hash = COGAGENT_VERSION_HASH
            return "CogAgent"
        elif model_type == "gemini-flash":
            self.active_model_id = GEMINI_FLASH_ID
            self.active_version_hash = None
            return "Gemini Flash"
        else:  # Default to Gemini Pro
            self.active_model_id = GEMINI_MODEL_ID
            self.active_version_hash = None
            return "Gemini Pro"
    
    def call_model(self, image_url, prompt, temperature=0.9):
        """Call the current active model with image and prompt"""
        try:
            # Use Gemini models
            if self.active_model_id in [GEMINI_MODEL_ID, GEMINI_FLASH_ID]:
                if not self.gemini_model and not self.gemini_flash:
                    return "Error: Gemini models not initialized. Please set GEMINI_API_KEY."
                
                # For base64 images
                if image_url.startswith('data:image'):
                    # If it's a base64 image directly in the URL
                    from PIL import Image
                    import base64
                    import io
                    
                    # Extract the base64 part after the comma
                    if ',' in image_url:
                        base64_data = image_url.split(',')[1]
                    else:
                        base64_data = image_url
                    
                    # Decode base64 to bytes
                    image_bytes = base64.b64decode(base64_data)
                    
                    # Open image from bytes
                    image = Image.open(io.BytesIO(image_bytes))
                else:
                    # For URL images
                    import requests
                    from PIL import Image
                    from io import BytesIO
                    
                    response = requests.get(image_url)
                    image = Image.open(BytesIO(response.content))
                
                # Call the appropriate Gemini model based on active_model_id
                if self.active_model_id == GEMINI_FLASH_ID:
                    gemini_response = self.gemini_flash.generate_content(
                        [image, prompt],
                        generation_config={"temperature": min(temperature, 1.0)}
                    )
                else:  # Default to Pro
                    gemini_response = self.gemini_model.generate_content(
                        [image, prompt],
                        generation_config={"temperature": min(temperature, 1.0)}
                    )
                return gemini_response.text
            
            # Use Replicate models (LLaVA or CogAgent)
            output = self.client.run(
                f"{self.active_model_id}:{self.active_version_hash}",
                input={
                    "image": image_url,
                    "prompt": prompt,
                    "temperature": temperature
                }
            )
            
            # Handle streaming response if LLaVA (which returns a generator)
            if self.active_model_id == LLAVA_MODEL_ID and hasattr(output, '__iter__'):
                full_response = ""
                for chunk in output:
                    full_response += chunk
                return full_response
                
            return output
        except Exception as e:
            return f"Model API Error: {e}"
    
    def start_keep_warm(self):
        """Start thread to periodically ping model to keep it warm"""
        if self.warm_up_thread and self.warm_up_thread.is_alive():
            print("Keep-warm thread already running")
            return
            
        self.keep_warm = True
        self.stop_warm_up.clear()
        self.warm_up_thread = threading.Thread(target=self._warm_up_loop, daemon=True)
        self.warm_up_thread.start()
        print(f"Started keep-warm thread for {self.active_model_id}")
    
    def stop_keep_warm(self):
        """Stop the keep-warm thread"""
        if self.warm_up_thread and self.warm_up_thread.is_alive():
            self.stop_warm_up.set()
            self.warm_up_thread.join(timeout=1.0)
            print("Stopped keep-warm thread")
        self.keep_warm = False
    
    def _warm_up_loop(self):
        """Loop that periodically pings the model with a minimal request"""
        while not self.stop_warm_up.is_set():
            try:
                print(f"Sending warm-up ping to {self.active_model_id}...")
                # Use a minimal prompt for keep-warm
                if self.active_model_id in [GEMINI_MODEL_ID, GEMINI_FLASH_ID]:
                    if self.active_model_id == GEMINI_FLASH_ID and self.gemini_flash:
                        self.gemini_flash.generate_content("warm-up ping")
                    elif self.gemini_model:
                        self.gemini_model.generate_content("warm-up ping")
                else:
                    # Both CogAgent and LLaVA seem to require/accept an image input.
                    tiny_img = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
                    self.client.run(
                        f"{self.active_model_id}:{self.active_version_hash}",
                        input={
                            "image": tiny_img, # Always include the placeholder image
                            "prompt": "warm-up ping",
                            "temperature": 0.1,
                            "max_tokens": 5
                        }
                    )
                print("Warm-up ping successful")
            except Exception as e:
                print(f"Warm-up ping error: {e}")
            
            # Wait for the interval or until stopped
            self.stop_warm_up.wait(self.warm_up_interval)

# Singleton instance for easy import
model_manager = ModelManager()

def get_model_manager():
    return model_manager 