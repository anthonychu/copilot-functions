from pathlib import Path
from copilot_functions import create_function_app

app = create_function_app(app_root=Path(__file__).parent)
