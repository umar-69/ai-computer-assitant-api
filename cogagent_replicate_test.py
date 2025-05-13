import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
import mss
import mss.tools
import replicate
import os
import sys
import threading
import re
import math
from dotenv import load_dotenv
import httpx
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
import uuid
import pyautogui  # <-- Add PyAutoGUI import

# Configure PyAutoGUI safety settings
pyautogui.FAILSAFE = True  # Move mouse to upper-left corner to abort
pyautogui.PAUSE = 0.5  # Add pause between PyAutoGUI commands

load_dotenv() # Load environment variables from .env file

# --- Constants ---
# CogAgent model (original)
COGAGENT_MODEL_ID = "cjwbw/cogagent-chat"
COGAGENT_VERSION_HASH = "c3429fc8f69bc71d0ee109e99c62b1e223b7cdfc0839b8e44a4326e12752656e"

# LLaVA model (new)
LLAVA_MODEL_ID = "yorickvp/llava-13b"
LLAVA_VERSION_HASH = "80537f9eead1a5bfa72d5ac6ea6414379be41d4d4f6679fd776e9535d1eb58bb"

# Current active model - change this to switch models
MODEL_IDENTIFIER = COGAGENT_MODEL_ID
VERSION_HASH = COGAGENT_VERSION_HASH

# Operation modes
GRID_MODE = "grid"
DIRECT_MODE = "direct"
CURRENT_MODE = DIRECT_MODE  # Default to direct mode

TEMP_SCREENSHOT_PATH = "temp_screenshot.png"
GRID_ROWS = 4
GRID_COLS = 4
# Define the prompt (adjust Task and Platform as needed)
PLATFORM = "Mac" # Or "WIN", "Linux", etc.

# Define model-specific prompt templates
COGAGENT_GRID_PROMPT = """Task: Look at the screenshot with grid cells labeled (A1, A2, B1, B2, etc.). {task}
I need you to identify WHICH SPECIFIC GRID CELL contains what I'm looking for.

History steps:
(Platform: {platform})

Format your answer as: 
"Action: [Brief description of what to do]"
"Grid Cell: [Letter+Number of the cell, e.g. A1, B3, etc.]"

Be very specific about which grid cell to click."""

COGAGENT_DIRECT_PROMPT = """Task: {task}

History steps:
(Platform: {platform})

Format your answer as:
"Action: [Brief description of what to do]"
"Grounded Operation: [CLICK at the box [[x1, y1, x2, y2]]]"

Provide exact pixel coordinates (x1,y1,x2,y2) for where to click."""

LLAVA_PROMPT_TEMPLATE = """{task}

Please describe what you see in the image, and if there are any labeled grid cells (A1, B2, etc.), please identify which cell contains what the user is looking for."""

# --- S3 Configuration (WARNING: Hardcoding keys is insecure!) ---
AWS_ACCESS_KEY_ID = "AKIAY76D73VBKDBIHYWH"
AWS_SECRET_ACCESS_KEY = "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"
S3_BUCKET_NAME = "amplify-amplify96450abbe8794-staging-205703-deployment"
S3_REGION = "eu-west-2"
S3_FOLDER_PATH = "AI-computer-assitant" # Optional: subfolder within bucket
# --- End S3 Config ---

# --- Helper Functions ---
def get_grid_cell_id(row, col):
    """Converts row/col index to A1, B2 style ID."""
    if row < 0 or col < 0:
        return "N/A"
    return f"{chr(ord('A') + row)}{col + 1}"

def parse_coordinates(output_text):
    """Extracts coordinates [[x1, y1, x2, y2]] from model output."""
    # Try the standard format with CLICK at the box
    match = re.search(r"box=\[\[([\d\s,]+)\]\]", output_text)
    if match:
        try:
            coords_str = match.group(1).split(',')
            return [int(c.strip()) for c in coords_str]
        except (IndexError, ValueError):
            pass
    
    # Try alternative format with CLICK at the box [[x,y,x,y]]
    match = re.search(r"CLICK at the box\s*\[\[([\d\s,]+)\]\]", output_text)
    if match:
        try:
            coords_str = match.group(1).split(',')
            return [int(c.strip()) for c in coords_str]
        except (IndexError, ValueError):
            pass
    
    # Try to find any sequence of 4 numbers that could be coordinates
    match = re.search(r"\[\[(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\]\]", output_text)
    if match:
        try:
            return [int(match.group(i)) for i in range(1, 5)]
        except (IndexError, ValueError):
            pass
            
    return None

def parse_action(output_text):
    """Extracts the Action: text from CogAgent output."""
    match = re.search(r"Action:\s*(.*)", output_text, re.IGNORECASE)
    if match:
        # Take the first line of the action if it's multi-line
        return match.group(1).split('\n')[0].strip()
    return "No action found."

def upload_to_s3(local_file_path):
    """Uploads a file to S3 and returns the public URL."""
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        print("S3 Upload Skipped: AWS credentials not configured.")
        return None
        
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION
    )
    
    unique_filename = f"{uuid.uuid4()}.png"
    s3_key = f"{S3_FOLDER_PATH.strip('/')}/{unique_filename}" if S3_FOLDER_PATH else unique_filename
    # Ensure object ACL is public-read for Replicate access
    extra_args = {'ACL': 'public-read', 'ContentType': 'image/png'}
    
    try:
        print(f"Uploading {local_file_path} to s3://{S3_BUCKET_NAME}/{s3_key}...")
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, s3_key, ExtraArgs=extra_args)
        # Construct the public URL (adjust format based on region/bucket settings if needed)
        # Standard format: https://<bucket-name>.s3.<region>.amazonaws.com/<key>
        object_url = f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{s3_key}"
        print(f"Upload Successful. URL: {object_url}")
        return object_url
    except (NoCredentialsError, PartialCredentialsError):
        messagebox.showerror("S3 Error", "AWS credentials not found or incomplete.")
        return None
    except ClientError as e:
        messagebox.showerror("S3 Error", f"Failed to upload to S3: {e.code} - {e.response['Error']['Message']}")
        return None
    except FileNotFoundError:
        messagebox.showerror("S3 Error", f"Local file not found: {local_file_path}")
        return None
    except Exception as e:
        messagebox.showerror("S3 Error", f"An unexpected error occurred during S3 upload: {e}")
        return None

def create_gridded_image(screenshot_path, rows=GRID_ROWS, cols=GRID_COLS):
    """
    Create a new image with grid overlay and cell labels and save it.
    Returns the path to the new gridded image.
    """
    try:
        # Open the original screenshot
        original_img = Image.open(screenshot_path)
        width, height = original_img.size
        
        # Create a copy to draw on (don't modify original)
        gridded_img = original_img.copy()
        draw = ImageDraw.Draw(gridded_img)
        
        # Calculate cell dimensions
        cell_width = width / cols
        cell_height = height / rows
        
        # Try to load font for labels, fallback to default
        try:
            # For macOS, use a system font
            font = ImageFont.truetype("Arial", 36)  # Larger font for visibility
        except IOError:
            # Fallback to default font
            font = ImageFont.load_default()
        
        # Draw grid lines
        for i in range(1, cols):
            x = int(i * cell_width)
            draw.line([(x, 0), (x, height)], fill="red", width=3)
            
        for i in range(1, rows):
            y = int(i * cell_height)
            draw.line([(0, y), (width, y)], fill="red", width=3)
        
        # Draw cell labels (A1, B2, etc.)
        for r in range(rows):
            for c in range(cols):
                cell_id = get_grid_cell_id(r, c)
                x = int(c * cell_width + 20)  # Offset from left edge
                y = int(r * cell_height + 20)  # Offset from top edge
                
                # First draw black outline for better visibility
                for dx, dy in [(-2,-2), (-2,2), (2,-2), (2,2), (-2,0), (0,-2), (2,0), (0,2)]:
                    draw.text((x+dx, y+dy), cell_id, fill="black", font=font)
                
                # Then draw the actual text in yellow
                draw.text((x, y), cell_id, fill="yellow", font=font)
        
        # Save the gridded image with a new filename
        gridded_path = "gridded_screenshot.png"
        gridded_img.save(gridded_path)
        print(f"Created gridded image: {gridded_path}")
        return gridded_path
        
    except Exception as e:
        print(f"Error creating gridded image: {e}")
        # If there's an error, return the original path
        return screenshot_path

def parse_grid_cell(output_text, is_llava=False):
    """Extracts the grid cell identifier (e.g., A1, B2) from model output."""
    # For CogAgent, try exact match for "Grid Cell: X#" format
    grid_match = re.search(r"Grid Cell:\s*([A-Z][0-9])", output_text, re.IGNORECASE)
    if grid_match:
        return grid_match.group(1).upper()  # Return in uppercase for consistency
    
    # For LLaVA or fallback, look for patterns like "cell A1" or "grid cell B2" or "in A1"
    general_match = re.search(r"(?:(?:cell|grid|in|the)\s+)?([A-Z][0-9])\b", output_text, re.IGNORECASE)
    if general_match:
        return general_match.group(1).upper()
        
    # If still not found, try a more comprehensive search for any grid-like pattern (Letter+Number)
    cell_match = re.search(r"\b([A-Z][0-9])\b", output_text)
    if cell_match:
        return cell_match.group(1).upper()
    
    return None  # No grid cell found

def perform_click_action(row_index, col_index, screenshot_width, screenshot_height):
    """
    Convert grid cell coordinates to screen coordinates and perform a click.
    
    Args:
        row_index: Zero-based row index (A=0, B=1, etc.)
        col_index: Zero-based column index (1=0, 2=1, etc.)
        screenshot_width: Width of the full screenshot in pixels
        screenshot_height: Height of the full screenshot in pixels
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get the screen dimensions
        screen_width, screen_height = pyautogui.size()
        
        # Handle case where screenshot might be from different resolution
        # If there's a mismatch, we need to scale coordinates
        scale_x = screen_width / screenshot_width
        scale_y = screen_height / screenshot_height
        
        # Calculate cell dimensions
        cell_width = screenshot_width / GRID_COLS
        cell_height = screenshot_height / GRID_ROWS
        
        # Calculate center of the grid cell (in screenshot coordinates)
        center_x_screenshot = (col_index * cell_width) + (cell_width / 2)
        center_y_screenshot = (row_index * cell_height) + (cell_height / 2)
        
        # Scale to actual screen coordinates
        target_x = center_x_screenshot * scale_x
        target_y = center_y_screenshot * scale_y
        
        # Safety guardrail to ensure coordinates are within screen
        target_x = max(0, min(target_x, screen_width - 1))
        target_y = max(0, min(target_y, screen_height - 1))
        
        # Log the action
        print(f"Moving mouse to coordinates: ({target_x}, {target_y})")
        
        # Move the mouse to the position (with duration for visibility)
        pyautogui.moveTo(target_x, target_y, duration=0.5)
        
        # Perform the click
        pyautogui.click()
        
        return True
    except Exception as e:
        print(f"Error performing click action: {e}")
        return False

# --- GUI Application Class ---
class ScreenshotAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Screenshot Analyzer")
        self.root.geometry("800x700") # Adjust size as needed

        self.api_token = os.getenv("REPLICATE_API_TOKEN")
        if not self.api_token:
            messagebox.showerror("Error", "REPLICATE_API_TOKEN not found in .env file.")
            self.root.quit()
            return
        
        # Create replicate client
        try:
            self.replicate_client = replicate.Client(api_token=self.api_token)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to initialize Replicate client: {e}")
            self.root.quit()
            return

        self.original_img = None
        self.display_img_tk = None
        self.screenshot_width = 0
        self.screenshot_height = 0
        self.display_width = 0
        self.display_height = 0
        self.highlighted_rect = None
        # Keep track of currently identified grid cell
        self.current_cell = {"row": -1, "col": -1, "valid": False}

        # --- Layout ---
        self.controls_frame = ttk.Frame(root, padding="10")
        self.controls_frame.pack(side=tk.TOP, fill=tk.X)

        # Prompt Input
        self.prompt_label = ttk.Label(self.controls_frame, text="Task:")
        self.prompt_label.pack(side=tk.LEFT, padx=(0, 5))
        self.prompt_entry = ttk.Entry(self.controls_frame, width=40) # Adjust width as needed
        self.prompt_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.prompt_entry.insert(0, "Find the terminal application.") # Default prompt

        # Screenshot Button
        self.screenshot_button = ttk.Button(self.controls_frame, text="Take Screenshot & Analyze", command=self.run_analysis)
        self.screenshot_button.pack(side=tk.LEFT, padx=5)
        
        # Add Execute Action button (initially disabled)
        self.action_button = ttk.Button(
            self.controls_frame, 
            text="Execute Action (Click)", 
            command=self.execute_action,
            state="disabled"  # Start disabled until we have a valid cell
        )
        self.action_button.pack(side=tk.LEFT, padx=5)
        
        # Add Switch Model button
        self.current_model_var = tk.StringVar(value="CogAgent")
        self.switch_model_button = ttk.Button(
            self.controls_frame,
            text="Switch to LLaVA",
            command=self.switch_model
        )
        self.switch_model_button.pack(side=tk.LEFT, padx=5)
        
        # Add Mode Toggle button
        self.current_mode_var = tk.StringVar(value="Direct")
        self.mode_button = ttk.Button(
            self.controls_frame,
            text="Switch to Grid Mode",
            command=self.toggle_mode
        )
        self.mode_button.pack(side=tk.LEFT, padx=5)

        # Status Label (keep at the end or move as desired)
        self.status_label = ttk.Label(self.controls_frame, text="Status: Idle")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        self.canvas = tk.Canvas(root, bg="lightgrey")
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.output_frame = ttk.Frame(root, padding="10")
        self.output_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.action_label = ttk.Label(self.output_frame, text="Action: -")
        self.action_label.pack(side=tk.LEFT, anchor=tk.W)

        self.coords_label = ttk.Label(self.output_frame, text="Coords: - | Grid Cell: -")
        self.coords_label.pack(side=tk.RIGHT, anchor=tk.E)

        # Bind resize event
        self.root.bind("<Configure>", self.on_resize)
        self.last_width = root.winfo_width()
        self.last_height = root.winfo_height()

    def update_status(self, text):
        self.status_label.config(text=f"Status: {text}")
        self.root.update_idletasks() # Force GUI update

    def run_analysis(self):
        current_task = self.prompt_entry.get().strip()
        if not current_task:
            messagebox.showwarning("Input Needed", "Please enter a task description in the text box.")
            self.update_status("Idle. Waiting for task.")
            return
            
        self.update_status("Taking screenshot...")
        
        # Hide the main window before taking the screenshot
        self.root.withdraw()
        self.root.after(200, lambda: self.capture_and_process(current_task)) # Delay to ensure window is hidden
        
    def capture_and_process(self, current_task):
        screenshot_taken = self.take_screenshot()
        
        # Show the main window again
        self.root.deiconify()
        
        if screenshot_taken:
            # Process screenshot based on mode
            if CURRENT_MODE == GRID_MODE:
                self.update_status("Screenshot captured. Creating gridded image...")
                # Create gridded image
                gridded_image_path = create_gridded_image(TEMP_SCREENSHOT_PATH)
                self.gridded_image_path = gridded_image_path  # Store for S3 upload
            else:  # DIRECT_MODE
                self.update_status("Screenshot captured. Processing raw image...")
                # Use the raw screenshot directly
                self.gridded_image_path = TEMP_SCREENSHOT_PATH
            
            # Display the original (non-gridded) screenshot in the GUI
            self.update_status("Calling API...")
            
            # Run API call in a separate thread, passing the current task
            threading.Thread(target=self.call_cogagent_api, args=(current_task,), daemon=True).start()
        else:
            self.update_status("Screenshot failed. Check console for errors.")

    def take_screenshot(self):
        try:
            with mss.mss() as sct:
                # Capture the primary monitor
                monitor = sct.monitors[1] # Index 1 is usually the primary monitor
                sct_img = sct.grab(monitor)
                # Save to PNG file
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=TEMP_SCREENSHOT_PATH)

            self.original_img = Image.open(TEMP_SCREENSHOT_PATH)
            self.screenshot_width, self.screenshot_height = self.original_img.size
            self.display_screenshot() # Display and draw grid
            return True
        except Exception as e:
            messagebox.showerror("Screenshot Error", f"Failed to capture screenshot: {e}")
            print(f"Screenshot Error: {e}")
            self.original_img = None
            self.screenshot_width = 0
            self.screenshot_height = 0
            self.canvas.delete("all") # Clear canvas
            return False

    def display_screenshot(self, event=None):
        if not self.original_img:
            return

        # Calculate available canvas size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1: # Canvas not ready yet
             # Retry after a short delay if canvas size is not available
             if hasattr(self, '_display_retry_id'):
                 self.root.after_cancel(self._display_retry_id)
             self._display_retry_id = self.root.after(50, self.display_screenshot)
             return
        if hasattr(self, '_display_retry_id'): # Clear retry if successful
             delattr(self, '_display_retry_id')


        # Calculate aspect ratios
        img_aspect = self.screenshot_width / self.screenshot_height
        canvas_aspect = canvas_width / canvas_height

        # Determine resize dimensions to fit canvas while maintaining aspect ratio
        if img_aspect > canvas_aspect:
            # Image is wider than canvas, fit to width
            self.display_width = canvas_width
            self.display_height = int(canvas_width / img_aspect)
        else:
            # Image is taller than canvas (or same aspect), fit to height
            self.display_height = canvas_height
            self.display_width = int(canvas_height * img_aspect)

        # Resize image using Pillow with ANTIALIAS filter for better quality
        # Use LANCZOS (previously ANTIALIAS) for high-quality downsampling
        display_img_resized = self.original_img.resize((self.display_width, self.display_height), Image.Resampling.LANCZOS)

        # Convert to Tkinter PhotoImage
        self.display_img_tk = ImageTk.PhotoImage(display_img_resized)

        # Clear previous drawings and display the new image
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.display_img_tk)
        self.canvas.config(scrollregion=self.canvas.bbox(tk.ALL)) # Optional: if you want scrollbars

        # Draw the grid over the displayed image
        self.draw_grid()
        # Clear previous highlight (cell highlight, keep if using)
        # if self.highlighted_rect:
        #    self.canvas.delete(self.highlighted_rect)
        #    self.highlighted_rect = None
        
        # Refresh dynamic elements like the target box
        # self.refresh_dynamic_canvas_elements()


    def draw_grid(self):
        if not self.display_img_tk or self.display_width == 0 or self.display_height == 0:
            return

        cell_width = self.display_width / GRID_COLS
        cell_height = self.display_height / GRID_ROWS

        # Draw grid lines - make them thicker
        for i in range(1, GRID_COLS):
            x = i * cell_width
            self.canvas.create_line(x, 0, x, self.display_height, fill="red", width=2)
            
        for i in range(1, GRID_ROWS):
            y = i * cell_height
            self.canvas.create_line(0, y, self.display_width, y, fill="red", width=2)

        # Draw cell labels (e.g., A1, B2)
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                cell_id = get_grid_cell_id(r, c)
                label_x = c * cell_width + 10  # Offset from left edge
                label_y = r * cell_height + 10  # Offset from top edge
                
                # Use a clearer, more visible label
                self.canvas.create_text(
                    label_x, label_y, 
                    text=cell_id, 
                    anchor=tk.NW, 
                    fill="yellow", 
                    font=("Arial", 12, "bold"),
                    # Add a black outline/shadow for better visibility
                    tags="grid_label"
                )


    def call_cogagent_api(self, task):
        """Call Replicate API with the current active model."""
        # Check for gridded image
        if not hasattr(self, 'gridded_image_path') or not os.path.exists(self.gridded_image_path):
            self.root.after(0, lambda: messagebox.showerror("Error", "Gridded screenshot file missing."))
            self.root.after(0, lambda: self.update_status("Error: Gridded screenshot file missing"))
            return
            
        # --- S3 Upload ---    
        image_input = None
        s3_url = upload_to_s3(self.gridded_image_path)
        if s3_url:
            image_input = s3_url # Use URL if upload successful
            # Clean up temporary files after successful upload (optional)
            try:
                if os.path.exists(TEMP_SCREENSHOT_PATH):
                    os.remove(TEMP_SCREENSHOT_PATH)
                    print(f"Removed local file: {TEMP_SCREENSHOT_PATH}")
                
                if self.gridded_image_path != TEMP_SCREENSHOT_PATH and os.path.exists(self.gridded_image_path):
                    os.remove(self.gridded_image_path)
                    print(f"Removed gridded file: {self.gridded_image_path}")
            except OSError as e:
                print(f"Error removing temp files: {e}")
        else:
            # Fallback or Error: Use local file upload (requires file to exist)
            # For simplicity, we'll just error out if S3 upload fails here
            self.root.after(0, lambda: messagebox.showerror("Error", "S3 Upload failed. Cannot proceed."))
            self.root.after(0, lambda: self.update_status("Error: S3 Upload failed"))
            return 
        # --- End S3 Upload ---
        
        try:
            # Select the appropriate prompt template based on the current model and mode
            if MODEL_IDENTIFIER == COGAGENT_MODEL_ID:
                if CURRENT_MODE == GRID_MODE:
                    prompt = COGAGENT_GRID_PROMPT.format(task=task, platform=PLATFORM)
                else:  # DIRECT_MODE
                    prompt = COGAGENT_DIRECT_PROMPT.format(task=task, platform=PLATFORM)
            else:  # LLaVA model
                prompt = LLAVA_PROMPT_TEMPLATE.format(task=task)
                
            print(f"Calling {MODEL_IDENTIFIER} with image URL and prompt:\n{prompt}")
            
            # Use the client instance and add temperature
            output = self.replicate_client.run(
                f"{MODEL_IDENTIFIER}:{VERSION_HASH}",
                input={
                    "image": image_input,
                    "prompt": prompt,
                    "temperature": 0.8
                }
            )
            
            # Handle streaming response if LLaVA (which returns a generator)
            if MODEL_IDENTIFIER == LLAVA_MODEL_ID and hasattr(output, '__iter__'):
                full_response = ""
                for chunk in output:
                    full_response += chunk
                output = full_response
                
            # Schedule result processing on the main thread
            self.root.after(0, self.process_api_result, output)
        
        except Exception as e:
            error_message = f"Replicate API Error: {e}"
            print(error_message) # Log the full error
            # Use lambda to pass the error message correctly
            self.root.after(0, lambda em=error_message: messagebox.showerror("API Error", em))
            self.root.after(0, lambda: self.update_status("API call failed"))

    def process_api_result(self, output):
        self.update_status("Processing API result...")
        print("\n--- Raw Model Output ---")
        print(output)
        print("----------------------")

        # Reset current cell data
        self.current_cell = {"row": -1, "col": -1, "valid": False}
        self.action_button.config(state="disabled")  # Disable action button by default

        if not isinstance(output, str):
             output = "\n".join(output) # Handle if output is unexpectedly a list/tuple
        
        # Different parsing based on model type
        is_llava = (MODEL_IDENTIFIER == LLAVA_MODEL_ID)
        
        # Parse the action
        if is_llava:
            # For LLaVA, entire response is the "action" description
            action = output
            self.action_label.config(text="LLaVA Response: (See below)")
            
            # Create or update a text box for the full response
            if not hasattr(self, 'response_text'):
                self.response_frame = ttk.Frame(self.root, padding="10")
                self.response_frame.pack(side=tk.BOTTOM, fill=tk.X, before=self.output_frame)
                
                self.response_label = ttk.Label(self.response_frame, text="Model Response:")
                self.response_label.pack(side=tk.TOP, anchor=tk.W)
                
                self.response_text = tk.Text(self.response_frame, height=5, width=80, wrap=tk.WORD)
                self.response_text.pack(side=tk.TOP, fill=tk.X)
                
                self.scrollbar = ttk.Scrollbar(self.response_text, command=self.response_text.yview)
                self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                self.response_text.configure(yscrollcommand=self.scrollbar.set)
            
            # Clear and update the text box
            self.response_text.delete(1.0, tk.END)
            self.response_text.insert(tk.END, output)
        else:
            # For CogAgent, parse action using the existing method
            action = parse_action(output)
            self.action_label.config(text=f"Action: {action}")
            
            # If we have a response frame from LLaVA, hide it
            if hasattr(self, 'response_frame'):
                self.response_frame.pack_forget()
        
        # Process based on mode
        if CURRENT_MODE == DIRECT_MODE:
            # For direct mode, look for coordinates
            coordinates = parse_coordinates(output)
            if coordinates and len(coordinates) == 4:
                x1, y1, x2, y2 = coordinates
                print(f"Coordinates Found: [{x1}, {y1}, {x2}, {y2}]")
                
                # Store the center of the coordinates for the click action
                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2
                
                # Store for direct execution
                self.current_coords = {"x": center_x, "y": center_y, "valid": True}
                self.coords_label.config(text=f"Coordinates: [{x1}, {y1}, {x2}, {y2}]")
                
                # Enable the action button
                self.action_button.config(state="normal")
                
                # Highlight the area with a rectangle
                if self.original_img and self.display_width > 0:
                    # Scale coordinates
                    scale_x = self.display_width / self.screenshot_width
                    scale_y = self.display_height / self.screenshot_height
                    
                    # Calculate displayed rectangle coordinates
                    disp_x1 = x1 * scale_x
                    disp_y1 = y1 * scale_y
                    disp_x2 = x2 * scale_x
                    disp_y2 = y2 * scale_y
                    
                    # Highlight area
                    self.highlight_area(disp_x1, disp_y1, disp_x2, disp_y2)
            else:
                self.coords_label.config(text="Coordinates: Not found")
        else:
            # Grid mode processing (existing logic)
            grid_cell = parse_grid_cell(output, is_llava=is_llava)
            
            # Find and highlight the grid cell if one was identified
            if grid_cell:
                print(f"Grid Cell Identified: {grid_cell}")
                # Extract row (letter) and column (number) from grid cell reference
                row_letter = grid_cell[0]  # First character (A, B, C, etc.)
                col_number = int(grid_cell[1]) - 1  # Second character (1, 2, 3, etc.) minus 1 for 0-indexing
                row_index = ord(row_letter) - ord('A')  # Convert letter to 0-based index
                
                # Validate indices are within grid bounds
                if 0 <= row_index < GRID_ROWS and 0 <= col_number < GRID_COLS:
                    # Highlight the specified grid cell
                    self.highlight_grid_cell(row_index, col_number)
                    self.coords_label.config(text=f"Grid Cell: {grid_cell}")
                    # Update current_cell
                    self.current_cell["row"] = row_index
                    self.current_cell["col"] = col_number
                    self.current_cell["valid"] = True
                    # Enable the action button
                    self.action_button.config(state="normal")
                else:
                    # Cell reference is out of bounds
                    self.coords_label.config(text=f"Invalid grid cell: {grid_cell}")
                    print(f"Warning: Grid cell {grid_cell} is outside the valid range.")
            else:
                # No grid cell identified
                self.coords_label.config(text="Grid Cell: Not found")
                print("Warning: No grid cell identified in the response.")
                # Clear any highlighting
                if self.highlighted_rect:
                    self.canvas.delete(self.highlighted_rect)
                    self.highlighted_rect = None
                    
        self.update_status("Analysis complete.")

    def on_resize(self, event):
         # Redraw image and grid only if size actually changed to avoid excessive redraws
        if event.widget == self.root and \
           (self.root.winfo_width() != self.last_width or self.root.winfo_height() != self.last_height):
            # A small delay helps ensure the canvas size is updated before redrawing
            if hasattr(self, '_resize_id'):
                self.root.after_cancel(self._resize_id)
            self._resize_id = self.root.after(50, self.display_screenshot) # Call display_screenshot after delay
            self.last_width = self.root.winfo_width()
            self.last_height = self.root.winfo_height()

    def highlight_grid_cell(self, row, col):
        """Highlights a specific grid cell by row and column index."""
        # Clear previous highlight and associated elements
        if self.highlighted_rect:
            self.canvas.delete(self.highlighted_rect)
            self.highlighted_rect = None
            # Delete any previously created elements with tag "highlight_elements"
            self.canvas.delete("highlight_elements")

        if self.display_width == 0 or self.display_height == 0:
            return

        cell_width = self.display_width / GRID_COLS
        cell_height = self.display_height / GRID_ROWS

        x1 = col * cell_width
        y1 = row * cell_height
        x2 = x1 + cell_width
        y2 = y1 + cell_height
        
        # Create multiple visual cues for better visibility:
        
        # 1. Semi-transparent filled rectangle (bright green with 40% opacity)
        self.highlighted_rect = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill="#00FF00",     # Bright green fill
            stipple='gray25',   # Transparency pattern
            tags="highlight_elements"
        )
        
        # 2. Thick border with animation effect (flashing)
        border_width = 4
        border = self.canvas.create_rectangle(
            x1 + border_width/2, y1 + border_width/2, 
            x2 - border_width/2, y2 - border_width/2,
            outline="#FF0000",   # Red outline
            width=border_width,
            tags="highlight_elements"
        )
        
        # 3. Large, bold cell ID in the center
        cell_id = get_grid_cell_id(row, col)
        center_x = x1 + (cell_width / 2)
        center_y = y1 + (cell_height / 2)
        
        # Black shadow/outline for text (for visibility against any background)
        for dx, dy in [(-2,-2), (-2,2), (2,-2), (2,2), (-1,0), (1,0), (0,-1), (0,1)]:
            self.canvas.create_text(
                center_x + dx, center_y + dy,
                text=cell_id,
                fill="black",
                font=("Arial", 36, "bold"),
                tags="highlight_elements"
            )
            
        # Foreground text
        self.canvas.create_text(
            center_x, center_y,
            text=cell_id,
            fill="white",
            font=("Arial", 36, "bold"),
            tags="highlight_elements"
        )
        
        # 4. "Click Here" indicator with arrow
        indicator_text = "CLICK HERE"
        arrow_size = min(cell_width, cell_height) * 0.15
        
        # Position below the cell ID
        indicator_y = center_y + 40
        
        self.canvas.create_text(
            center_x, indicator_y,
            text=indicator_text,
            fill="#FFFF00",  # Yellow
            font=("Arial", 24, "bold"),
            tags="highlight_elements"
        )
        
        # Simple arrow pointing to center (triangle)
        self.canvas.create_polygon(
            center_x, center_y - arrow_size*2,  # Top
            center_x - arrow_size, center_y - arrow_size*3,  # Bottom left
            center_x + arrow_size, center_y - arrow_size*3,  # Bottom right
            fill="#FFFF00",  # Yellow
            outline="black",
            width=2,
            tags="highlight_elements"
        )
        
        # Make sure all elements are above the image but below any interface elements
        for element in self.canvas.find_withtag("highlight_elements"):
            self.canvas.tag_raise(element)
        
        # Force update
        self.canvas.update_idletasks()
        
        # Create a blinking effect with alternating colors for the border
        def blink_border(count=0):
            if count < 10:  # Blink 5 times (10 color changes)
                current_color = self.canvas.itemcget(border, "outline")
                new_color = "#00FFFF" if current_color == "#FF0000" else "#FF0000"  # Toggle between red and cyan
                self.canvas.itemconfig(border, outline=new_color)
                self.root.after(500, lambda: blink_border(count + 1))  # Schedule next blink in 500ms
        
        # Start the blinking effect
        blink_border()

    def refresh_dynamic_canvas_elements(self):
        """Clears old target box and draws a new one if coords are available."""
        # This method is no longer needed with the new gridded image approach
        pass

    def draw_target_box(self, x1, y1, x2, y2):
        """Draws a red rectangle at the specific target coordinates. Assumes old one is cleared."""
        # This method is no longer needed with the new gridded image approach
        pass

    def execute_action(self):
        """Execute the action based on the current mode."""
        if CURRENT_MODE == DIRECT_MODE:
            # Direct coordinate mode
            if not hasattr(self, 'current_coords') or not self.current_coords.get("valid", False):
                messagebox.showwarning("No Valid Coordinates", "No valid coordinates have been identified.")
                return
            
            # Get the coordinates
            x = self.current_coords["x"]
            y = self.current_coords["y"]
            self.update_status("Executing action (Direct Mode)...")
            
            # Ask for confirmation before performing the click
            confirm = messagebox.askyesno("Confirm Action", f"Are you sure you want to click at coordinates ({x}, {y})?")
            if not confirm:
                self.update_status("Action execution cancelled.")
                return
            
            # Perform the click action at exact coordinates
            try:
                # Get screen dimensions
                screen_width, screen_height = pyautogui.size()
                
                # Safety check
                if x < 0 or x >= screen_width or y < 0 or y >= screen_height:
                    self.update_status(f"Error: Coordinates ({x}, {y}) are outside screen bounds.")
                    return
                
                # Move the mouse directly to the specified position
                print(f"Moving mouse to direct coordinates: ({x}, {y})")
                pyautogui.moveTo(x, y, duration=0.5)
                pyautogui.click()
                self.update_status("Action executed successfully.")
            except Exception as e:
                self.update_status(f"Action execution failed: {e}")
                print(f"Error executing direct action: {e}")
        else:
            # Grid cell mode
            if not self.current_cell["valid"]:
                messagebox.showwarning("No Valid Cell", "No valid grid cell has been identified.")
                return
            
            row_index = self.current_cell["row"]
            col_index = self.current_cell["col"]
            self.update_status("Executing action (Grid Mode)...")
            
            # Ask for confirmation before performing the click
            confirm = messagebox.askyesno("Confirm Action", "Are you sure you want to perform this action?")
            if not confirm:
                self.update_status("Action execution cancelled.")
                return
            
            # Perform the click action
            if perform_click_action(row_index, col_index, self.screenshot_width, self.screenshot_height):
                self.update_status("Action executed successfully.")
            else:
                self.update_status("Action execution failed. Check console for errors.")

    def switch_model(self):
        """Toggles between CogAgent and LLaVA models."""
        global MODEL_IDENTIFIER, VERSION_HASH
        
        if self.current_model_var.get() == "CogAgent":
            # Switch to LLaVA
            MODEL_IDENTIFIER = LLAVA_MODEL_ID
            VERSION_HASH = LLAVA_VERSION_HASH
            self.current_model_var.set("LLaVA")
            self.switch_model_button.config(text="Switch to CogAgent")
            self.update_status("Model switched to LLaVA-13B")
            # Change prompt field placeholder
            self.prompt_entry.delete(0, tk.END)
            self.prompt_entry.insert(0, "What do you see in this image?")
        else:
            # Switch to CogAgent
            MODEL_IDENTIFIER = COGAGENT_MODEL_ID
            VERSION_HASH = COGAGENT_VERSION_HASH
            self.current_model_var.set("CogAgent")
            self.switch_model_button.config(text="Switch to LLaVA")
            self.update_status("Model switched to CogAgent")
            # Change prompt field placeholder
            self.prompt_entry.delete(0, tk.END)
            self.prompt_entry.insert(0, "Find the terminal application.")
            
        print(f"Switched to {self.current_model_var.get()} model: {MODEL_IDENTIFIER}:{VERSION_HASH}")

    def toggle_mode(self):
        """Toggles between grid mode and direct mode."""
        global CURRENT_MODE
        
        if CURRENT_MODE == GRID_MODE:
            CURRENT_MODE = DIRECT_MODE
            self.current_mode_var.set("Direct")
            self.mode_button.config(text="Switch to Grid Mode")
            self.update_status("Mode switched to Direct Mode")
        else:
            CURRENT_MODE = GRID_MODE
            self.current_mode_var.set("Grid")
            self.mode_button.config(text="Switch to Direct Mode")
            self.update_status("Mode switched to Grid Mode")
            
        print(f"Switched to {CURRENT_MODE} mode")

    def highlight_area(self, x1, y1, x2, y2):
        """Highlights a specific area using direct coordinates."""
        # Clear previous highlight and associated elements
        if self.highlighted_rect:
            self.canvas.delete(self.highlighted_rect)
            self.highlighted_rect = None
            # Delete any previously created elements with tag "highlight_elements"
            self.canvas.delete("highlight_elements")

        # Create multiple visual cues for better visibility
        
        # 1. Semi-transparent filled rectangle (bright red with 40% opacity)
        self.highlighted_rect = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill="#FF0000",     # Bright red fill
            stipple='gray25',   # Transparency pattern
            tags="highlight_elements"
        )
        
        # 2. Thick border with animation effect (flashing)
        border_width = 4
        border = self.canvas.create_rectangle(
            x1 + border_width/2, y1 + border_width/2, 
            x2 - border_width/2, y2 - border_width/2,
            outline="#00FF00",   # Green outline
            width=border_width,
            tags="highlight_elements"
        )
        
        # 3. "Click Here" indicator with arrow
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        indicator_text = "CLICK HERE"
        
        # Black shadow/outline for text
        for dx, dy in [(-2,-2), (-2,2), (2,-2), (2,2), (-1,0), (1,0), (0,-1), (0,1)]:
            self.canvas.create_text(
                center_x + dx, center_y + dy,
                text=indicator_text,
                fill="black",
                font=("Arial", 24, "bold"),
                tags="highlight_elements"
            )
            
        # Foreground text
        self.canvas.create_text(
            center_x, center_y,
            text=indicator_text,
            fill="#FFFF00",  # Yellow
            font=("Arial", 24, "bold"),
            tags="highlight_elements"
        )
        
        # Make sure all elements are above the image but below any interface elements
        for element in self.canvas.find_withtag("highlight_elements"):
            self.canvas.tag_raise(element)
        
        # Force update
        self.canvas.update_idletasks()
        
        # Create a blinking effect with alternating colors for the border
        def blink_border(count=0):
            if count < 10:  # Blink 5 times (10 color changes)
                current_color = self.canvas.itemcget(border, "outline")
                new_color = "#FF00FF" if current_color == "#00FF00" else "#00FF00"  # Toggle between green and magenta
                self.canvas.itemconfig(border, outline=new_color)
                self.root.after(500, lambda: blink_border(count + 1))  # Schedule next blink in 500ms
        
        # Start the blinking effect
        blink_border()


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = ScreenshotAnalyzerApp(root)
    # Check if app initialization failed (e.g., no API key)
    if app.api_token:
        root.mainloop()
    else:
        print("Exiting due to missing API token.") 