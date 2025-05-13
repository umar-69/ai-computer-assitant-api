# AI Desktop Assistant

A desktop automation system that uses AI visual models to understand and interact with your GUI.

## Features

- **Visual Understanding**: Uses Google Gemini, CogAgent, and LLaVA models to understand desktop screenshots
- **Bounding Box Detection**: Gemini provides precise bounding box coordinates for UI elements
- **Grid Mode**: Overlays a grid (e.g., A1, B2) on screenshots, making it easier to reference locations
- **Direct Mode**: Uses raw screenshots and gets exact pixel coordinates
- **Visual Feedback**: Provides animated highlighting with flashing borders and "CLICK HERE" indicators
- **Model Warm-up**: Optional "keep-warm" feature to prevent cold boot delays
- **Voice Interaction**: Speech-to-text and text-to-speech capabilities for hands-free operation
- **Natural Female Voice**: Uses OpenAI's high-quality voices for audio responses
- **Cloud Integration**: Optional S3 storage for screenshots
- **Platform Support**: Designed for macOS with special considerations for its UI

## Requirements

- Python 3.7+
- Google Gemini API key (recommended for best object detection)
- OpenAI API key (for speech-to-text and text-to-speech)
- Replicate API key (for CogAgent and LLaVA models as alternatives)
- AWS credentials (optional, for S3 storage)
- PyAudio (for audio recording)
- Pygame (for audio playback)

## Installation

1. Clone this repository:
   ```
   git clone [repository-url]
   cd ai-desktop-assistant
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create a `.env` file with your API keys:
   ```
   GEMINI_API_KEY=your_gemini_api_key  # Recommended
   OPENAI_API_KEY=your_openai_api_key  # Required for voice features
   REPLICATE_API_TOKEN=your_replicate_api_token  # Optional
   AWS_ACCESS_KEY_ID=your_aws_access_key  # Optional
   AWS_SECRET_ACCESS_KEY=your_aws_secret_key  # Optional
   S3_BUCKET_NAME=your_s3_bucket  # Optional
   AWS_REGION=your_aws_region  # Optional
   ```

## Usage

Run the application with:

```
python main.py
```

Options:
- `--no-qt`: Use Tkinter-only mode (not recommended for macOS)

### Application Interface

1. **Model Selection**: Choose between Gemini (precise bounding boxes), CogAgent (specialized for GUI), or LLaVA (broader visual understanding)
2. **Voice Features**: Toggle speech input (microphone) and output (speakers), and select voice type
3. **Grid Mode**: Toggle grid overlay for easier reference of screen elements
4. **Keep Model Warm**: Toggle periodic pings to keep the model ready for faster responses
5. **Take Screenshot**: Capture your desktop for AI analysis
6. **Microphone Button**: Click to record your voice for speech-to-text conversion
7. **Prompt**: Enter instructions for the AI about what you want to do
8. **Analyze Screenshot**: Send the screenshot and prompt to the chosen AI model
9. **Execute Action**: Perform the action recommended by the AI
10. **Clear History**: Reset the conversation with the AI

### Model Capabilities

- **Gemini 1.5 Pro**: Best for detecting UI elements with precise bounding box coordinates. Outputs coordinates in [y_min, x_min, y_max, x_max] format normalized to 0-1000.
- **CogAgent**: Specialized for GUI understanding and interaction.
- **LLaVA**: Good for general visual understanding and analysis.

### Example Prompts

- "Click on the Safari icon in the dock"
- "Find and open System Preferences"
- "What's the title of the open window?"
- "How many tabs are open in my browser?"
- "Help me create a new folder on the desktop"

## Architecture

The application is organized in modular components:

- **main.py**: Main application and UI
- **model_manager.py**: Handles model selection and API interactions
- **visual_utils.py**: Manages screenshots and Tkinter-based visual highlighting
- **qt_overlay.py**: Provides PyQt5-based transparent overlay for visual cues

## Safety Features

- **Emergency Stop**: PyAutoGUI's failsafe (move mouse to upper-left corner)
- **Confirmation Steps**: The app shows what will be clicked before acting
- **Transparent Highlight**: The overlay allows you to see what's underneath

## Troubleshooting

- **Model Errors**: Ensure your API keys are valid
- **Visual Issues**: Try both Qt and Tkinter modes to see which works better on your system
- **Permission Issues**: macOS may require screen recording permissions
- **Bounding Box Issues**: If elements aren't properly detected, try being more specific in your prompt

## License

[MIT License](LICENSE)

## Acknowledgements

- [Google Gemini](https://ai.google.dev/) for the powerful multimodal model with bounding box capabilities
- [Replicate](https://replicate.com/) for the model API
- [THUDM/CogAgent](https://github.com/THUDM/CogAgent) for the visual understanding model
- [LLaVA](https://llava-vl.github.io/) for the multimodal model 