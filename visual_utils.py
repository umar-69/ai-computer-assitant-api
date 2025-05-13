import tkinter as tk
from PIL import Image, ImageDraw, ImageFont
import io
import uuid
import time
from threading import Thread
import platform
import pyautogui
import mss
import mss.tools

# Constants for visual feedback
GRID_COLOR = "#FF0000"  # Red
HIGHLIGHT_COLOR = "#FF3366"  # Pink-red
HIGHLIGHT_THICKNESS = 3
FLASH_ITERATIONS = 5
FLASH_DELAY = 0.1

class VisualManager:
    def __init__(self, root=None):
        """Initialize the visual manager"""
        self.root = root  # Tkinter root if provided
        self.grid_mode = True  # Default to grid mode
        self.grid_rows = 10  # Default grid size
        self.grid_cols = 10
        self.highlight_canvas = None
        self.current_highlights = []  # List to track active highlights
        
        # Platform-specific adjustments
        self.is_mac = platform.system() == "Darwin"
        self.is_windows = platform.system() == "Windows"
        self.is_linux = platform.system() == "Linux"
        
        # MSS screen capture instance
        self.sct = mss.mss()
        
    def toggle_grid_mode(self):
        """Toggle between grid mode and direct mode"""
        self.grid_mode = not self.grid_mode
        return self.grid_mode
    
    def capture_screen(self, draw_grid=True):
        """Capture screen and optionally overlay grid"""
        # Get primary monitor
        monitor = self.sct.monitors[1]  # Primary monitor in MSS
        
        # Capture screenshot
        sct_img = self.sct.grab(monitor)
        img_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)
        
        # Get actual dimensions
        actual_width = sct_img.width
        actual_height = sct_img.height
        
        # Calculate grid dimensions based on screen size
        # Aim for reasonable cell size (e.g. ~80px)
        target_cell_size = 80
        self.grid_rows = max(5, actual_height // target_cell_size)
        self.grid_cols = max(5, actual_width // target_cell_size)
        
        # If grid mode and draw_grid is True, draw the grid
        if self.grid_mode and draw_grid:
            img_bytes = self._add_grid_to_image(img_bytes, self.grid_rows, self.grid_cols)
            
        return img_bytes, actual_width, actual_height, (self.grid_rows, self.grid_cols)
    
    def _add_grid_to_image(self, image_bytes, rows, cols):
        """Add grid overlay to image"""
        try:
            # Open image from bytes
            img = Image.open(io.BytesIO(image_bytes))
            draw = ImageDraw.Draw(img)
            width, height = img.size
            
            # Calculate cell dimensions
            cell_width = width / cols
            cell_height = height / rows
            
            # Try to load font, use default if not available
            try:
                if self.is_mac:
                    font = ImageFont.truetype("Arial.ttf", 12)
                elif self.is_windows:
                    font = ImageFont.truetype("arial.ttf", 12)
                else:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except IOError:
                font = ImageFont.load_default()
                
            # Draw grid lines and labels
            for r in range(rows):
                for c in range(cols):
                    # Draw cell borders
                    x1, y1 = c * cell_width, r * cell_height
                    x2, y2 = (c + 1) * cell_width, (r + 1) * cell_height
                    
                    # Draw rectangle for cell
                    draw.rectangle([x1, y1, x2, y2], outline=GRID_COLOR, width=1)
                    
                    # Add label (e.g., A1, B2)
                    col_letter = chr(65 + c) if c < 26 else chr(65 + (c // 26) - 1) + chr(65 + (c % 26))
                    label = f"{col_letter}{r+1}"
                    
                    # Position label in top-left of cell
                    text_x, text_y = x1 + 3, y1 + 3
                    draw.text((text_x, text_y), label, fill="#FF0000", font=font)
            
            # Save image to bytes
            output = io.BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()
        except Exception as e:
            print(f"Error adding grid to image: {e}")
            return image_bytes  # Return original if error
    
    def highlight_area(self, x, y, width, height, message=None, flash=True):
        """
        Create a visual highlight on the screen at specified coordinates
        
        Args:
            x, y: Top-left coordinates of highlight
            width, height: Size of highlight
            message: Optional message to display
            flash: Whether to flash the highlight
        """
        if self.root is None:
            print("Cannot highlight without Tkinter root")
            return
            
        # Create a new toplevel window if needed
        if self.highlight_canvas is None:
            highlight_window = tk.Toplevel(self.root)
            highlight_window.attributes("-topmost", True)
            highlight_window.attributes("-alpha", 0.7)
            highlight_window.overrideredirect(True)  # No window decorations
            
            # Make window as large as screen
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            highlight_window.geometry(f"{screen_width}x{screen_height}+0+0")
            
            # On macOS, set window to allow clicks to pass through
            if self.is_mac:
                try:
                    highlight_window.attributes("-transparent", True)
                except:
                    pass
            
            # Create canvas for drawing
            self.highlight_canvas = tk.Canvas(
                highlight_window, 
                width=screen_width, 
                height=screen_height,
                highlightthickness=0,
                bg=""  # Transparent background
            )
            self.highlight_canvas.pack(fill=tk.BOTH, expand=True)
            
        # Generate a unique tag for this highlight
        highlight_id = f"highlight_{uuid.uuid4().hex}"
        
        # Draw rectangle
        rect_id = self.highlight_canvas.create_rectangle(
            x, y, x + width, y + height,
            outline=HIGHLIGHT_COLOR,
            width=HIGHLIGHT_THICKNESS,
            tags=(highlight_id,)
        )
        
        # Add optional message
        text_id = None
        if message:
            text_id = self.highlight_canvas.create_text(
                x + width//2, y - 10,
                text=message,
                fill=HIGHLIGHT_COLOR,
                font=("Arial", 12, "bold"),
                tags=(highlight_id,)
            )
        
        # Start flashing in a separate thread if requested
        if flash:
            self.current_highlights.append(highlight_id)
            Thread(target=self._flash_highlight, args=(highlight_id, rect_id, text_id)).start()
        
        return highlight_id
        
    def _flash_highlight(self, highlight_id, rect_id, text_id=None):
        """Flash a highlight by toggling visibility"""
        try:
            for _ in range(FLASH_ITERATIONS):
                # Toggle visibility
                self.highlight_canvas.itemconfig(rect_id, state=tk.HIDDEN)
                if text_id:
                    self.highlight_canvas.itemconfig(text_id, state=tk.HIDDEN)
                time.sleep(FLASH_DELAY)
                
                self.highlight_canvas.itemconfig(rect_id, state=tk.NORMAL)
                if text_id:
                    self.highlight_canvas.itemconfig(text_id, state=tk.NORMAL)
                time.sleep(FLASH_DELAY)
                
            # Remove from tracking after done flashing
            if highlight_id in self.current_highlights:
                self.current_highlights.remove(highlight_id)
                
            # If no more highlights, hide canvas after a delay
            if not self.current_highlights:
                self.root.after(500, self._hide_highlight_canvas)
        except Exception as e:
            print(f"Error during highlight flashing: {e}")
    
    def _hide_highlight_canvas(self):
        """Hide the highlight canvas if no active highlights"""
        if self.highlight_canvas and not self.current_highlights:
            self.highlight_canvas.delete("all")
    
    def clear_highlights(self):
        """Clear all highlights"""
        if self.highlight_canvas:
            self.highlight_canvas.delete("all")
            self.current_highlights = []
    
    def highlight_grid_cell(self, row, col, message=None):
        """Highlight a specific grid cell"""
        if not self.grid_mode:
            print("Cannot highlight grid cell when not in grid mode")
            return
            
        # Calculate screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Calculate cell dimensions
        cell_width = screen_width / self.grid_cols
        cell_height = screen_height / self.grid_rows
        
        # Calculate cell position
        x = col * cell_width
        y = row * cell_height
        
        # Highlight the cell
        return self.highlight_area(x, y, cell_width, cell_height, message, flash=True)
    
    def convert_grid_to_pixel(self, grid_ref):
        """
        Convert grid reference (e.g. 'A1', 'C5') to pixel coordinates
        Returns (x, y, width, height) of the cell
        """
        if not self.grid_mode:
            return None
            
        try:
            # Parse grid reference
            # Handle both A1 format and R1C1 format
            if grid_ref[0] == 'R' and 'C' in grid_ref:
                # R1C1 format
                parts = grid_ref.split('C')
                row = int(parts[0][1:]) - 1  # R1 -> row 0
                col = int(parts[1]) - 1      # C1 -> col 0
            else:
                # A1 format
                col_part = ""
                row_part = ""
                for char in grid_ref:
                    if char.isalpha():
                        col_part += char
                    else:
                        row_part += char
                
                # Convert column letters to number (A=0, B=1, etc.)
                col = 0
                for i, c in enumerate(reversed(col_part.upper())):
                    col += (ord(c) - 65 + 1) * (26 ** i)
                col -= 1  # Convert to 0-based
                
                row = int(row_part) - 1  # Convert to 0-based
            
            # Calculate screen dimensions
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            
            # Calculate cell dimensions
            cell_width = screen_width / self.grid_cols
            cell_height = screen_height / self.grid_rows
            
            # Calculate cell position
            x = col * cell_width
            y = row * cell_height
            
            return (x, y, cell_width, cell_height)
        except Exception as e:
            print(f"Error converting grid reference: {e}")
            return None
    
    def click_at_position(self, x, y, right_click=False, double_click=False):
        """Perform a click at specified coordinates"""
        try:
            # Move mouse to position
            pyautogui.moveTo(x, y, duration=0.5)
            
            # Perform click action
            if right_click:
                pyautogui.rightClick()
            elif double_click:
                pyautogui.doubleClick()
            else:
                pyautogui.click()
            
            return True
        except Exception as e:
            print(f"Error performing click: {e}")
            return False
    
    def click_grid_cell(self, grid_ref, right_click=False, double_click=False):
        """Click in the center of a grid cell"""
        cell_coords = self.convert_grid_to_pixel(grid_ref)
        if cell_coords:
            x, y, width, height = cell_coords
            # Click in the center of the cell
            center_x = x + width / 2
            center_y = y + height / 2
            return self.click_at_position(center_x, center_y, right_click, double_click)
        return False 