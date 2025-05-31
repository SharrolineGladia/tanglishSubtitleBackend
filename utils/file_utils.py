import os
import shutil

def allowed_file(filename, allowed_extensions):
    """
    Check if a file has an allowed extension
    
    Args:
        filename (str): The filename to check
        allowed_extensions (set): Set of allowed file extensions
    
    Returns:
        bool: True if file has an allowed extension, False otherwise
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def cleanup_temp_files(file_list):
    """
    Clean up temporary files
    
    Args:
        file_list (list): List of file paths to clean up
    """
    for file_path in file_list:
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Error removing {file_path}: {e}")