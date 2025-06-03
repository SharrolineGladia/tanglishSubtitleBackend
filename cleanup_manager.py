import os
import shutil
import time
import threading
import schedule
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CleanupManager:
    def __init__(self, temp_dir="static/temp"):
        self.temp_dir = temp_dir
        self.cleanup_thread = None
        self.stop_cleanup = False
        
    def get_folder_age_minutes(self, folder_path):
        """Get the age of a folder in minutes based on creation time"""
        try:
            creation_time = os.path.getctime(folder_path)
            current_time = time.time()
            age_seconds = current_time - creation_time
            return age_seconds / 60  # Convert to minutes
        except OSError:
            return 0
    
    def get_file_age_minutes(self, file_path):
        """Get the age of a file in minutes based on modification time"""
        try:
            modification_time = os.path.getmtime(file_path)
            current_time = time.time()
            age_seconds = current_time - modification_time
            return age_seconds / 60  # Convert to minutes
        except OSError:
            return 0
    
    def should_cleanup_folder(self, upload_id_folder):
        """
        Determine if a folder should be cleaned up based on:
        1. results.txt is older than 10 minutes
        2. upload_id folder is older than 2 hours (120 minutes)
        """
        folder_path = os.path.join(self.temp_dir, upload_id_folder)
        
        if not os.path.isdir(folder_path):
            return False
        
        # Check if folder is older than 2 hours (120 minutes)
        folder_age = self.get_folder_age_minutes(folder_path)
        if folder_age > 120:
            logger.info(f"Folder {upload_id_folder} is {folder_age:.1f} minutes old (>120 min)")
            return True
        
        # Check if results.txt exists and is older than 10 minutes
        results_file = os.path.join(folder_path, "results.txt")
        if os.path.exists(results_file):
            file_age = self.get_file_age_minutes(results_file)
            if file_age > 10:
                logger.info(f"results.txt in {upload_id_folder} is {file_age:.1f} minutes old (>10 min)")
                return True
        
        return False
    
    def cleanup_old_files(self):
        """Remove old upload folders based on cleanup criteria"""
        if not os.path.exists(self.temp_dir):
            logger.info(f"Temp directory {self.temp_dir} does not exist")
            return
        
        cleaned_count = 0
        total_size_freed = 0
        
        try:
            # Get all subdirectories in temp folder
            upload_folders = [f for f in os.listdir(self.temp_dir) 
                            if os.path.isdir(os.path.join(self.temp_dir, f))]
            
            logger.info(f"Found {len(upload_folders)} upload folders to check")
            
            for upload_id in upload_folders:
                folder_path = os.path.join(self.temp_dir, upload_id)
                
                if self.should_cleanup_folder(upload_id):
                    try:
                        # Calculate folder size before deletion
                        folder_size = self.get_folder_size(folder_path)
                        
                        # Remove the entire folder
                        shutil.rmtree(folder_path)
                        cleaned_count += 1
                        total_size_freed += folder_size
                        
                        logger.info(f"✓ Cleaned up folder: {upload_id} (Size: {self.format_size(folder_size)})")
                        
                    except Exception as e:
                        logger.error(f"Error cleaning up folder {upload_id}: {e}")
            
            if cleaned_count > 0:
                logger.info(f"Cleanup completed: {cleaned_count} folders removed, "
                          f"{self.format_size(total_size_freed)} freed")
            else:
                logger.info("No folders needed cleanup")
                
        except Exception as e:
            logger.error(f"Error during cleanup process: {e}")
    
    def get_folder_size(self, folder_path):
        """Calculate total size of a folder in bytes"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(file_path)
                    except OSError:
                        pass
        except OSError:
            pass
        return total_size
    
    def format_size(self, size_bytes):
        """Format size in bytes to human readable format"""
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024
            i += 1
        return f"{size_bytes:.1f}{size_names[i]}"
    
    def start_scheduled_cleanup(self, interval_minutes=30):
        """Start scheduled cleanup that runs every interval_minutes"""
        schedule.clear()  # Clear any existing schedules
        
        # Schedule cleanup to run every interval_minutes
        schedule.every(interval_minutes).minutes.do(self.cleanup_old_files)
        
        def run_scheduler():
            logger.info(f"Starting scheduled cleanup every {interval_minutes} minutes")
            while not self.stop_cleanup:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        
        self.cleanup_thread = threading.Thread(target=run_scheduler)
        self.cleanup_thread.daemon = True
        self.cleanup_thread.start()
        
        # Run initial cleanup
        self.cleanup_old_files()
    
    def stop_scheduled_cleanup(self):
        """Stop the scheduled cleanup"""
        self.stop_cleanup = True
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=5)
        logger.info("Scheduled cleanup stopped")
    
    def manual_cleanup(self):
        """Manually trigger cleanup (useful for testing or on-demand cleanup)"""
        logger.info("Manual cleanup triggered")
        self.cleanup_old_files()
    
    def get_cleanup_status(self):
        """Get current status of temp directory"""
        if not os.path.exists(self.temp_dir):
            return {
                'status': 'temp_dir_not_found',
                'total_folders': 0,
                'total_size': 0,
                'folders': []
            }
        
        folders = []
        total_size = 0
        
        try:
            upload_folders = [f for f in os.listdir(self.temp_dir) 
                            if os.path.isdir(os.path.join(self.temp_dir, f))]
            
            for upload_id in upload_folders:
                folder_path = os.path.join(self.temp_dir, upload_id)
                folder_size = self.get_folder_size(folder_path)
                folder_age = self.get_folder_age_minutes(folder_path)
                
                results_file = os.path.join(folder_path, "results.txt")
                results_age = None
                if os.path.exists(results_file):
                    results_age = self.get_file_age_minutes(results_file)
                
                should_cleanup = self.should_cleanup_folder(upload_id)
                
                folders.append({
                    'upload_id': upload_id,
                    'size': folder_size,
                    'size_formatted': self.format_size(folder_size),
                    'folder_age_minutes': folder_age,
                    'results_age_minutes': results_age,
                    'should_cleanup': should_cleanup
                })
                
                total_size += folder_size
            
            return {
                'status': 'success',
                'total_folders': len(folders),
                'total_size': total_size,
                'total_size_formatted': self.format_size(total_size),
                'folders': folders
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'total_folders': 0,
                'total_size': 0,
                'folders': []
            }

# Global cleanup manager instance
cleanup_manager = CleanupManager()

def start_cleanup_service(interval_minutes=30):
    """Start the cleanup service with specified interval"""
    cleanup_manager.start_scheduled_cleanup(interval_minutes)

def stop_cleanup_service():
    """Stop the cleanup service"""
    cleanup_manager.stop_scheduled_cleanup()

def manual_cleanup():
    """Trigger manual cleanup"""
    cleanup_manager.manual_cleanup()

def get_cleanup_status():
    """Get cleanup status"""
    return cleanup_manager.get_cleanup_status()