import os
import sys

__all__ = ["get_data_path", "get_resource_path"]

def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller.

    Resources are files bundled WITH the executable (templates, static, json data).

    Args:
        relative_path (str): Path relative to the project/bundle root.

    Returns:
        str: Absolute, normalized path to the resource.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS —
        # injected onto sys at runtime only inside a frozen build, not in the
        # stdlib stub.
        base_path = sys._MEIPASS  # ty: ignore[missing-attribute]
    except AttributeError:
        # In development, use the project root
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return os.path.normpath(os.path.join(base_path, relative_path))

def get_data_path(filename: str) -> str:
    """Get absolute path to data file, always relative to the executable or script location.

    Data files are persistent files that should survive updates and exits (site.db).

    Args:
        filename (str): Name of the data file.

    Returns:
        str: Absolute, normalized path to the file inside the instance folder.
    """
    if getattr(sys, 'frozen', False):
        # Folder where the .exe is located
        base_path = os.path.dirname(sys.executable)
    else:
        # In development, use the project root
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    instance_path = os.path.join(base_path, 'instance')
    os.makedirs(instance_path, exist_ok=True)
    return os.path.normpath(os.path.join(instance_path, filename))
