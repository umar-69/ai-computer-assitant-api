from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget
from PyQt5.QtCore import Qt, QRect, QTimer, pyqtSlot, QPoint
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
import sys
import platform

class OverlayWindow(QMainWindow):
    """
    Transparent window overlay for displaying visual cues on screen
    This overlay stays on top of all other windows and can highlight areas with rectangles
    """
    def __init__(self):
        super().__init__()
        
        # Configure window to be frameless and stay on top
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.WindowTransparentForInput  # Allow clicks to pass through
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Store platform information
        self.is_mac = platform.system() == "Darwin"
        
        # Get screen dimensions
        self.setup_screen_geometry()
        
        # Initialize highlight data
        self.highlights = {}  # Dictionary of all active highlights
        self.active_timers = {}  # Track active flashing timers by id
        
        # Set default visual properties
        self.highlight_color = QColor(255, 0, 0, 200)  # Semi-transparent red
        self.highlight_thickness = 3
        self.text_color = QColor(255, 0, 0, 255)  # Solid red
        
    def setup_screen_geometry(self):
        """Setup the overlay to cover the primary screen"""
        # Get primary screen
        screen = QApplication.primaryScreen()
        if not screen:
            # Fallback to first screen if no primary
            screens = QApplication.screens()
            if screens:
                screen = screens[0]
            else:
                # No screens available, use default size
                self.setGeometry(0, 0, 1920, 1080)
                return
                
        # Get screen geometry
        geometry = screen.geometry()
        self.screen_width = geometry.width()
        self.screen_height = geometry.height()
        
        # Set window to cover entire screen
        self.setGeometry(geometry)
        
        # Store device pixel ratio for macOS retina displays
        self.device_pixel_ratio = screen.devicePixelRatio()
        
        print(f"Overlay set to: {geometry.width()}x{geometry.height()}, DPR: {self.device_pixel_ratio}")
        
    def paintEvent(self, event):
        """Draw all highlights on the overlay"""
        painter = QPainter(self)
        # Clear background with transparent color
        painter.fillRect(self.rect(), Qt.transparent)
        
        # Draw all active highlights
        for highlight_id, highlight_data in self.highlights.items():
            # Extract highlight data
            rect = highlight_data['rect']
            message = highlight_data.get('message')
            
            # Set pen for outline
            pen = QPen(self.highlight_color)
            pen.setWidth(self.highlight_thickness)
            painter.setPen(pen)
            
            # Draw rectangle
            painter.drawRect(rect)
            
            # Draw optional message above rectangle
            if message:
                painter.setFont(QFont("Arial", 12, QFont.Bold))
                painter.setPen(self.text_color)
                text_x = rect.x() + (rect.width() // 2) - (len(message) * 4)  # Rough center
                text_y = rect.y() - 10
                painter.drawText(text_x, text_y, message)
                
            # Draw "CLICK HERE" indicator in the middle of the rect if specified
            if highlight_data.get('show_click_indicator', False):
                click_message = "CLICK HERE"
                painter.setFont(QFont("Arial", 14, QFont.Bold))
                painter.setPen(self.text_color)
                text_x = rect.x() + (rect.width() // 2) - (len(click_message) * 4)  # Rough center
                text_y = rect.y() + (rect.height() // 2)
                painter.drawText(text_x, text_y, click_message)
    
    def add_highlight(self, x, y, width, height, message=None, flash=True, 
                     fade_out=True, show_click=False, duration=3000):
        """
        Add a rectangular highlight to the overlay
        
        Args:
            x, y: Top-left coordinates
            width, height: Dimensions of highlight
            message: Optional text to display with highlight
            flash: Whether to flash the highlight
            fade_out: Whether to automatically remove after duration
            show_click: Whether to show "CLICK HERE" text
            duration: How long to display highlight in ms (if fade_out is True)
            
        Returns:
            str: ID of the highlight for later reference
        """
        # Create unique ID
        import uuid
        highlight_id = str(uuid.uuid4())
        
        # Account for device pixel ratio on macOS Retina displays
        if hasattr(self, 'device_pixel_ratio') and self.device_pixel_ratio > 1.0:
            # Log original coordinates for debugging
            print(f"Original coordinates: x={x}, y={y}, w={width}, h={height}")
            
            # Apply scaling factor
            # On macOS with Retina, logical coordinates are different from pixel coordinates
            if self.is_mac:
                # On macOS, don't scale coordinates or we'll get double-scaling
                pass
            else:
                # On other platforms, we might need to scale
                x = int(x * self.device_pixel_ratio)
                y = int(y * self.device_pixel_ratio)
                width = int(width * self.device_pixel_ratio)
                height = int(height * self.device_pixel_ratio)
            
            print(f"Adjusted coordinates: x={x}, y={y}, w={width}, h={height}, DPR={self.device_pixel_ratio}")
        
        # Store highlight data
        self.highlights[highlight_id] = {
            'rect': QRect(x, y, width, height),
            'message': message,
            'show_click_indicator': show_click
        }
        
        # Update display
        self.update()
        
        # Setup flashing if requested
        if flash:
            self._setup_flashing(highlight_id)
            
        # Setup auto-removal if requested
        if fade_out:
            QTimer.singleShot(duration, lambda: self.remove_highlight(highlight_id))
            
        return highlight_id
    
    def _setup_flashing(self, highlight_id, cycles=5, interval=400):
        """Setup flashing animation for a highlight"""
        if highlight_id not in self.highlights:
            return
            
        # Create timer for flashing
        timer = QTimer(self)
        self.active_timers[highlight_id] = {
            'timer': timer,
            'visible': True,
            'cycles': cycles,
            'count': 0
        }
        
        # Connect timer to flash function
        timer.timeout.connect(lambda: self._flash_step(highlight_id))
        timer.start(interval)
    
    def _flash_step(self, highlight_id):
        """One step in the flashing animation"""
        if highlight_id not in self.active_timers or highlight_id not in self.highlights:
            return
            
        # Toggle visibility
        timer_data = self.active_timers[highlight_id]
        timer_data['visible'] = not timer_data['visible']
        
        # Handle visibility change
        if timer_data['visible']:
            # Just update display to show highlight
            pass
        else:
            # Temporarily remove from display dict (not from self.highlights)
            # This achieves hiding without removing
            pass
            
        # Update display
        self.update()
        
        # Increment counter
        timer_data['count'] += 1
        
        # Check if we're done flashing
        if timer_data['count'] >= timer_data['cycles'] * 2:  # *2 because each cycle is two timer events
            timer_data['timer'].stop()
            del self.active_timers[highlight_id]
    
    def remove_highlight(self, highlight_id):
        """Remove a specific highlight"""
        if highlight_id in self.highlights:
            del self.highlights[highlight_id]
            
            # Also stop any associated timer
            if highlight_id in self.active_timers:
                self.active_timers[highlight_id]['timer'].stop()
                del self.active_timers[highlight_id]
                
            # Update display
            self.update()
    
    def clear_all_highlights(self):
        """Remove all highlights"""
        # Stop all timers
        for timer_data in self.active_timers.values():
            timer_data['timer'].stop()
            
        # Clear dictionaries
        self.highlights.clear()
        self.active_timers.clear()
        
        # Update display
        self.update()
        
    def highlight_grid_cell(self, grid_rows, grid_cols, row, col, message=None):
        """
        Highlight a specific grid cell
        
        Args:
            grid_rows, grid_cols: Total grid dimensions
            row, col: 0-based indices of cell to highlight
            message: Optional message to display
        """
        # Calculate cell dimensions
        cell_width = self.screen_width / grid_cols
        cell_height = self.screen_height / grid_rows
        
        # Calculate position
        x = col * cell_width
        y = row * cell_height
        
        # Add highlight
        return self.add_highlight(x, y, cell_width, cell_height, message, flash=True)

# Function to create and show the overlay window
def create_overlay(parent_tk_root=None):
    """Create and return an OverlayWindow instance"""
    # Ensure application exists
    app = None
    if not QApplication.instance():
        app = QApplication(sys.argv)
    
    # Create overlay window
    overlay = OverlayWindow()
    overlay.show()
    
    return overlay, app

if __name__ == "__main__":
    # Test the overlay
    overlay, app = create_overlay()
    
    # Add a test highlight after 1 second
    QTimer.singleShot(1000, lambda: overlay.add_highlight(100, 100, 200, 150, "Test Highlight", show_click=True))
    
    # Start event loop if we created the application
    if app:
        sys.exit(app.exec_()) 