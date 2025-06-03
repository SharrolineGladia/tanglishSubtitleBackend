import os
import shutil
import time
import threading
import schedule
import fcntl  # For file locking on Unix systems
import tempfile
from datetime import datetime, timedelta
import logging
import psutil  # For process checking

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProductionCleanupManager:
    def __init__(self, temp_dir="static/temp"):
        self.temp_dir = temp_dir
        self.cleanup_thread = None
        self.stop_cleanup = False
        self.lock_file = os.path.join(tempfile.gettempdir(), 'flask_cleanup.lock')
        self.is_master_process = False
        
    def acquire_cleanup_lock(self):
        """Acquire exclusive lock to ensure only one process runs cleanup"""
        try:
            self.lock_fd = open(self.lock_file, 'w')
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_fd.write(str(os.getpid()))
            self.lock_fd.flush()
            self.is_master_process = True
            logger.info(f"Acquired cleanup lock for PID {os.getpid()}")
            return True
        except (IOError, OSError):
            logger.info(f"Another process is handling cleanup (PID {os.getpid()})")
            return False
    
    def release_cleanup_lock(self):
        """Release the cleanup lock"""
        try:
            if hasattr(self, 'lock_fd'):
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                self.lock_fd.close()
                if os.path.exists(self.lock_file):
                    os.remove(self.lock_file)
                logger.info("Released cleanup lock")
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")
    
    def check_permissions(self):
        """Check if we have necessary permissions"""
        if not os.path.exists(self.temp_dir):
            try:
                os.makedirs(self.temp_dir, exist_ok=True)
                logger.info(f"Created temp directory: {self.temp_dir}")
            except PermissionError:
                logger.error(f"Cannot create temp directory: {self.temp_dir}")
                return False
        
        # Test write permissions
        try:
            test_dir = os.path.join(self.temp_dir, 'permission_test')
            os.makedirs(test_dir, exist_ok=True)
            os.rmdir(test_dir)
            return True
        except PermissionError:
            logger.error(f"No write permission to {self.temp_dir}")
            return False
    
    def get_folder_age_minutes(self, folder_path):
        """Get the age of a folder in minutes based on creation time"""
        try:
            creation_time = os.path.getctime(folder_path)
            current_time = time.time()
            age_seconds = current_time - creation_time
            return age_seconds / 60
        except OSError as e:
            logger.warning(f"Could not get folder age for {folder_path}: {e}")
            return 0
    
    def get_file_age_minutes(self, file_path):
        """Get the age of a file in minutes based on modification time"""
        try:
            modification_time = os.path.getmtime(file_path)
            current_time = time.time()
            age_seconds = current_time - modification_time
            return age_seconds / 60
        except OSError as e:
            logger.warning(f"Could not get file age for {file_path}: {e}")
            return 0
    
    def should_cleanup_folder(self, upload_id_folder):
        """Determine if a folder should be cleaned up"""
        folder_path = os.path.join(self.temp_dir, upload_id_folder)
        
        if not os.path.isdir(folder_path):
            return False
        
        try:
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
        except Exception as e:
            logger.error(f"Error checking folder {upload_id_folder}: {e}")
            return False
    
    def safe_remove_folder(self, folder_path):
        """Safely remove a folder with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                shutil.rmtree(folder_path)
                return True
            except OSError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Attempt {attempt + 1} failed to remove {folder_path}: {e}")
                    time.sleep(1)  # Wait before retry
                else:
                    logger.error(f"Failed to remove {folder_path} after {max_retries} attempts: {e}")
                    return False
        return False
    
    def cleanup_old_files(self):
        """Remove old upload folders based on cleanup criteria"""
        if not self.is_master_process:
            logger.debug("Not master process, skipping cleanup")
            return
            
        if not self.check_permissions():
            logger.error("Insufficient permissions for cleanup")
            return
        
        if not os.path.exists(self.temp_dir):
            logger.info(f"Temp directory {self.temp_dir} does not exist")
            return
        
        cleaned_count = 0
        total_size_freed = 0
        failed_count = 0
        
        try:
            upload_folders = [f for f in os.listdir(self.temp_dir) 
                            if os.path.isdir(os.path.join(self.temp_dir, f))]
            
            logger.info(f"Found {len(upload_folders)} upload folders to check")
            
            for upload_id in upload_folders:
                folder_path = os.path.join(self.temp_dir, upload_id)
                
                if self.should_cleanup_folder(upload_id):
                    try:
                        folder_size = self.get_folder_size(folder_path)
                        
                        if self.safe_remove_folder(folder_path):
                            cleaned_count += 1
                            total_size_freed += folder_size
                            logger.info(f"✓ Cleaned up folder: {upload_id} (Size: {self.format_size(folder_size)})")
                        else:
                            failed_count += 1
                            
                    except Exception as e:
                        logger.error(f"Error cleaning up folder {upload_id}: {e}")
                        failed_count += 1
            
            if cleaned_count > 0 or failed_count > 0:
                logger.info(f"Cleanup completed: {cleaned_count} folders removed, "
                          f"{failed_count} failed, {self.format_size(total_size_freed)} freed")
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
        """Start scheduled cleanup - only if master process"""
        if not self.acquire_cleanup_lock():
            logger.info("Another process is handling cleanup, this process will skip")
            return
        
        schedule.clear()
        schedule.every(interval_minutes).minutes.do(self.cleanup_old_files)
        
        def run_scheduler():
            logger.info(f"Starting scheduled cleanup every {interval_minutes} minutes (Master Process)")
            while not self.stop_cleanup:
                try:
                    schedule.run_pending()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"Error in scheduler: {e}")
                    time.sleep(60)
        
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
        self.release_cleanup_lock()
        logger.info("Scheduled cleanup stopped")
    
    def manual_cleanup(self):
        """Manually trigger cleanup"""
        logger.info("Manual cleanup triggered")
        if not self.is_master_process:
            # For manual cleanup, temporarily become master
            if self.acquire_cleanup_lock():
                try:
                    self.cleanup_old_files()
                finally:
                    self.release_cleanup_lock()
                    self.is_master_process = False
            else:
                logger.warning("Could not acquire lock for manual cleanup")
        else:
            self.cleanup_old_files()
    
    def get_cleanup_status(self):
        """Get current status of temp directory"""
        if not os.path.exists(self.temp_dir):
            return {
                'status': 'temp_dir_not_found',
                'total_folders': 0,
                'total_size': 0,
                'folders': [],
                'is_master_process': self.is_master_process,
                'process_id': os.getpid()
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
                'folders': folders,
                'is_master_process': self.is_master_process,
                'process_id': os.getpid(),
                'permissions_ok': self.check_permissions()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'total_folders': 0,
                'total_size': 0,
                'folders': [],
                'is_master_process': self.is_master_process,
                'process_id': os.getpid()
            }

# Global cleanup manager instance
cleanup_manager = ProductionCleanupManager()

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