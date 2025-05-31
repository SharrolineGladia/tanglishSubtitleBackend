import os

def cleanup_temp_files(file_list):
    """
    Clean up temporary files
    Args:
        file_list: List of file paths to remove
    """
    for file_path in file_list:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Error removing {file_path}: {e}")